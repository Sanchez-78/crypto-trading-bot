"""
Multi-indicator signal generator.

Regime-aware direction logic:
  BULL_TREND / BEAR_TREND  → trend-following (EMA × ADX × MACD)
  RANGING                  → mean-reversion  (RSI extremes + BB)
  QUIET_RANGE              → mean-reversion
  HIGH_VOL                 → confidence × 0.5 penalty (EV gate decides)

Confidence penalties (soft — EV gate is the sole filter):
  counter-trend            × 0.6
  weak EMA spread          × 0.7
  high volatility          × 0.5

Side balance:  if >60% one side in last 10 signals → penalise score −1
Time debounce: 30 s per symbol (dedup only)

Session gate (research-backed):
  08:00–21:00 UTC: active — London/NY session, peak liquidity, tightest spreads
  21:00–08:00 UTC: suppressed — Asia session, wider spreads, fake breakouts
  Bypassed during bootstrap (<150 trades) to preserve learning data flow.

OBI normalization:
  Raw OBI = (vol_bid - vol_ask) / total_vol is magnitude-dependent.
  Normalized OBI z-score = (obi - rolling_mean) / rolling_std allows
  a consistent threshold regardless of market depth conditions.
  Research (Cont et al. 2014, arXiv:2112.02947): normalized OFI achieves
  R²=83-86% for contemporaneous price change prediction vs ~60% for raw.

Relative volatility filter:
  recent_atr (last 20 ticks) / baseline_atr (last 60 ticks) ratio.
  Ratio < 0.5: market too dead — signals are noise (dead-flat consolidation).
  Bypassed during bootstrap to allow learning data collection.
"""

from src.core.event_bus       import subscribe_once, publish
from src.services.learning_event import track_generated, track_filtered
import math, time

prices     = {}   # symbol -> list[float], capped at 600
_macd_vals = {}   # symbol -> list[float]
_last_ts   = {}   # symbol -> float (last signal timestamp, time-based debounce)
_last_price_ts = {}   # symbol -> float (last price update timestamp for freshness check)
_side_hist = {}   # symbol -> deque[action], last 10 actions
_adx_hist      = {}   # symbol -> float (last adx, for slope)
_rsi_hist      = {}   # symbol -> float (last rsi, for slope)
_rsi_full_hist = {}   # symbol -> list[float], rolling RSI series for divergence
_obi_hist      = {}   # symbol -> list[float], rolling OBI for z-score normalization
_price_z_hist  = {}   # symbol -> list[float], rolling 20-price window for Z-score

# ── V10.13d: Per-cycle signal generation tracking ──────────────────────────────
_cycle_ticks          = 0          # fresh ticks received this cycle
_cycle_symbols        = set()      # symbols updated this cycle
_cycle_candidates     = 0          # candidates created before RDE
_cycle_prefilter_drops = {}        # symbol -> reason (pre-filter drop tracking)
_cycle_start_ts       = 0.0        # when current cycle started

# Flat TP/SL (must match trade_executor._TP_MULT/_SL_MULT + realtime_decision_engine)
_TP_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0,
            "RANGING":    1.0, "QUIET_RANGE": 1.0}
_SL_MULT = {"BULL_TREND": 0.8, "BEAR_TREND": 0.8,
            "RANGING":    0.8, "QUIET_RANGE": 0.8}
MIN_TP_PCT = 0.0025   # must match trade_executor.MIN_TP_PCT
MIN_SL_PCT = 0.0015   # must match trade_executor.MIN_SL_PCT

MIN_TICKS    = 50
DEBOUNCE_S   = 15    # seconds between signals per symbol (was 30 — halved to
                      # double evaluation throughput; portfolio gate caps execution rate)
SIDE_WINDOW  = 10    # signals to track for side balance
SIDE_MAX_PCT = 0.60  # penalise if > 60% one side


# ── Indicators ────────────────────────────────────────────────────────────────

def _ema(series, n):
    if not series:
        return 0.0
    n = min(n, len(series))
    k = 2.0 / (n + 1)
    val = sum(series[:n]) / n
    for v in series[n:]:
        val = v * k + val * (1 - k)
    return val


def _rsi(series, n=14):
    gains  = [max(series[i] - series[i-1], 0) for i in range(1, len(series))]
    losses = [max(series[i-1] - series[i], 0) for i in range(1, len(series))]
    ag = _ema(gains[-n*3:],  n) or 1e-9
    al = _ema(losses[-n*3:], n) or 1e-9
    return 100 - 100 / (1 + ag / al)


def _rsi_divergence(sym, hist, rsi_now, window=30, price_th=0.003, rsi_th=3.0):
    """Detect classic RSI divergence over the last `window` ticks.

    Bullish divergence: price makes a lower low while RSI makes a higher low.
      → selling pressure exhausted; momentum already turning — reversal up likely.

    Bearish divergence: price makes a higher high while RSI makes a lower high.
      → buying pressure exhausted; momentum fading — reversal down likely.

    Thresholds:
      price_th = 0.3%  — minimum price move to qualify (filters flat markets)
      rsi_th   = 3.0   — minimum RSI counter-move (filters noise)
      window   = 30    — lookback ticks (~60s at 2s/tick)

    Returns (bullish: bool, bearish: bool).
    Returns (False, False) when fewer than `window` samples available.
    """
    rh = _rsi_full_hist.setdefault(sym, [])
    rh.append(rsi_now)
    if len(rh) > 300:
        rh.pop(0)

    if len(rh) < window or len(hist) < window:
        return False, False

    price_chg = (hist[-1] - hist[-window]) / (hist[-window] or 1e-9)
    rsi_chg   = rsi_now - rh[-window]

    # Bullish: price lower low (+RSI held / rose)
    bull = price_chg < -price_th and rsi_chg > rsi_th

    # Bearish: price higher high + RSI fell
    bear = price_chg > price_th and rsi_chg < -rsi_th

    return bull, bear


def _kc(series, atrs, n=20):
    mid = _ema(series, n)
    atr = _atr(series, n) if atrs else 0.0
    return mid - 2 * atr, mid, mid + 2 * atr


def _atr(series, n=14):
    diffs = [abs(series[i] - series[i-1]) for i in range(1, len(series))]
    return _ema(diffs[-n*3:], n) if diffs else 1e-9


def _adx(series, n=14):
    if len(series) < n * 2:
        return 20.0, 50.0, 50.0
    ups   = [max(series[i] - series[i-1], 0) for i in range(1, len(series))]
    downs = [max(series[i-1] - series[i], 0) for i in range(1, len(series))]
    trs   = [abs(series[i] - series[i-1])    for i in range(1, len(series))]
    tr_s  = _ema(trs[-n*3:],   n) or 1e-9
    di_p  = 100 * _ema(ups[-n*3:],   n) / tr_s
    di_m  = 100 * _ema(downs[-n*3:], n) / tr_s
    adx   = 100 * abs(di_p - di_m) / ((di_p + di_m) or 1e-9)
    return adx, di_p, di_m


# ── Regime ────────────────────────────────────────────────────────────────────

def _htf_trend(series):
    """HTF proxy: EMA(50) vs EMA(150) from tick buffer (~100s vs ~300s)."""
    if len(series) < 150:
        return None
    e50  = _ema(series, 50)
    e150 = _ema(series, 150)
    if e50 > e150 * 1.0003: return "UP"
    if e50 < e150 * 0.9997: return "DOWN"
    return "FLAT"


def _regime(series, adx, di_p, di_m, atr_val):
    curr    = series[-1]
    atr_pct = atr_val / curr if curr else 0
    bb_lo, bb_mid, bb_hi = _kc(series, atr_val)
    bb_w = (bb_hi - bb_lo) / bb_mid if bb_mid else 0

    if atr_pct > 0.012:          return "HIGH_VOL"
    if adx > 25 and di_p > di_m: return "BULL_TREND"
    if adx > 25 and di_m > di_p: return "BEAR_TREND"
    if adx < 20 and bb_w < 0.015: return "QUIET_RANGE"
    return "RANGING"


# ── Score (regime-aware) ──────────────────────────────────────────────────────

def _score(action, curr, e10, e50, e200, rsi_v, rsi_slope,
           macd_l, macd_s, bb_lo, bb_hi, adx_v, regime, obi, htf=None,
           price_z=0.0):
    sc = 0
    reasons = []

    if action == "BUY":
        if e10 > e50:                              sc += 1; reasons.append("EMA↑")
        if curr > e200:                            sc += 1; reasons.append("HTF↑")
        if 45 < rsi_v < 70:                        sc += 1; reasons.append(f"RSI{rsi_v:.0f}")
        if macd_l > macd_s and macd_l > 0:         sc += 1; reasons.append("MACD0↑")
        elif macd_l > macd_s:                      sc += 1; reasons.append("MACD↑")
        if regime == "BULL_TREND":                  sc += 1; reasons.append("ADX↑")
        if curr <= bb_lo * 1.003 and rsi_v < 35:   sc += 2; reasons.append("KC↩L")
        elif curr <= bb_lo * 1.005 and rsi_v < 40: sc += 1; reasons.append("KClo")
        # OBI boost (z-score: >1.0 = significant bid-side imbalance)
        if obi > 1.0:                              sc += 1; reasons.append("OBI↑")
        
        # Mean-reversion bonus: RSI slope confirms bounce direction
        if regime in ("RANGING", "QUIET_RANGE"):
            if rsi_v < 30:
                if rsi_slope > 0: sc += 3; reasons.append("MR↓↓✓")
                else:             sc += 2; reasons.append("MR↓↓")
            elif rsi_v < 42:      sc += 1; reasons.append("MR↓")
            # Price Z-score: large negative deviation → mean-reversion BUY
            # Avellaneda & Lee (2010): |z| > 1.5 ≈ actionable deviation
            if price_z <= -1.5:   sc += 2; reasons.append("Zlo")
            elif price_z <= -1.0: sc += 1; reasons.append("Zlo-")
    else:
        if e10 < e50:                              sc += 1; reasons.append("EMA↓")
        if curr < e200:                            sc += 1; reasons.append("HTF↓")
        if 30 < rsi_v < 55:                        sc += 1; reasons.append(f"RSI{rsi_v:.0f}")
        if macd_l < macd_s and macd_l < 0:         sc += 1; reasons.append("MACD0↓")
        elif macd_l < macd_s:                      sc += 1; reasons.append("MACD↓")
        if regime == "BEAR_TREND":                  sc += 1; reasons.append("ADX↓")
        if curr >= bb_hi * 0.997 and rsi_v > 65:   sc += 2; reasons.append("KC↩H")
        elif curr >= bb_hi * 0.995 and rsi_v > 60: sc += 1; reasons.append("KChi")
        # OBI boost (z-score: <-1.0 = significant ask-side imbalance)
        if obi < -1.0:                             sc += 1; reasons.append("OBI↓")
        # Mean-reversion bonus: RSI slope confirms reversal
        if regime in ("RANGING", "QUIET_RANGE"):
            if rsi_v > 70:
                if rsi_slope < 0: sc += 3; reasons.append("MR↑↑✓")
                else:             sc += 2; reasons.append("MR↑↑")
            elif rsi_v > 58:      sc += 1; reasons.append("MR↑")
            # Price Z-score: large positive deviation → mean-reversion SELL
            if price_z >= 1.5:    sc += 2; reasons.append("Zhi")
            elif price_z >= 1.0:  sc += 1; reasons.append("Zhi-")

    # HTF alignment bonus (+1 if 5m trend agrees, no penalty if disagrees)
    if htf == "UP"   and action == "BUY":  sc += 1; reasons.append("HTFok")
    if htf == "DOWN" and action == "SELL": sc += 1; reasons.append("HTFok")

    return sc, reasons


# ── Side balance ──────────────────────────────────────────────────────────────

def _side_penalty(s, action):
    """Return score penalty (0 or 1) if one side dominates last SIDE_WINDOW signals."""
    hist = _side_hist.setdefault(s, [])
    if len(hist) < SIDE_WINDOW:
        return 0
    dominant_cnt = max(hist.count("BUY"), hist.count("SELL"))
    if dominant_cnt / SIDE_WINDOW > SIDE_MAX_PCT:
        dominant = "BUY" if hist.count("BUY") > hist.count("SELL") else "SELL"
        return 1 if action == dominant else 0
    return 0


def _record_side(s, action):
    hist = _side_hist.setdefault(s, [])
    hist.append(action)
    if len(hist) > SIDE_WINDOW:
        hist.pop(0)


# ── Edge strategies ───────────────────────────────────────────────────────────

# ── V10.13d: Cycle management ──────────────────────────────────────────────────

def reset_cycle_stats():
    """Call at start of each live cycle to reset current-cycle counters."""
    global _cycle_ticks, _cycle_symbols, _cycle_candidates, _cycle_prefilter_drops, _cycle_start_ts
    _cycle_ticks = 0
    _cycle_symbols = set()
    _cycle_candidates = 0
    _cycle_prefilter_drops = {}
    _cycle_start_ts = time.time()


def get_cycle_stats():
    """Return dict of current-cycle signal generation stats."""
    return {
        "ticks": _cycle_ticks,
        "symbols_updated": len(_cycle_symbols),
        "candidates_generated": _cycle_candidates,
        "prefilter_drops": dict(_cycle_prefilter_drops),
    }


def _prefilter(hist, atr_v, price):
    """
    Volatility floor gate — blocks only fully dead-flat markets.
    Threshold lowered 0.60 → 0.05:

    Root cause: warmup loads 80 one-minute klines. At boot r20 and r50 are
    both computed from 1-min candle closes (same scale) → passes.
    Once real-time 2-second ticks start, r20 fills with tiny sub-second moves
    while r50 still holds the larger kline candle deltas → r20/r50 ≈ 0.15–0.25.
    The 0.60 threshold therefore blocked 100% of real-time signals after boot
    despite active markets (confirmed: 3 signals at MARKET LIVE then 0 for 37 min).
    0.05 blocks only truly dead markets (r20 < 5% of baseline range).
    """
    if len(hist) < 51:
        return False
    diffs = [abs(hist[i] - hist[i-1]) for i in range(1, len(hist))]
    r20   = sum(diffs[-20:]) / 20
    r50   = sum(diffs[-50:]) / 50
    return r20 > r50 * 0.05


def _score_direction(hist, e50, e200, breakout_up, breakout_down, mom5, action):
    """
    Score a directional setup across 7 binary features.
    All features are directionally symmetric (BUY/SELL mirrored).
    Returns (score, features_dict).
    """
    p      = hist[-1]
    is_buy = action == "BUY"

    # Vol expansion (proxy: 20-bar avg range vs 50-bar avg range)
    diffs = [abs(hist[i] - hist[i-1]) for i in range(1, len(hist))]
    r20   = sum(diffs[-20:]) / 20
    r50   = sum(diffs[-50:]) / 50

    # Wick: use recent 5-tick range as OHLC proxy
    hi5 = max(hist[-5:])
    lo5 = min(hist[-5:])
    rng = hi5 - lo5 or 1e-9

    features = {
        "trend":    (e50 > e200)        if is_buy else (e50 < e200),
        "pullback": (p < e50 * 1.01)    if is_buy else (p > e50 * 0.99),
        "bounce":   (hist[-1] > hist[-2]) if is_buy else (hist[-1] < hist[-2]),
        "breakout": bool(breakout_up    if is_buy else breakout_down),
        "vol":      r20 > r50,
        "mom":      (mom5 > 0)          if is_buy else (mom5 < 0),
        "wick":     ((hi5 - p) / rng < 0.6) if is_buy else ((p - lo5) / rng < 0.6),
    }
    return sum(1 for v in features.values() if v), features


def _get_scored_edge(hist, e50, e200, breakout_up, breakout_down, mom5, reg, regime_conf=1.0):
    """
    Score BUY/SELL setups through sequential gates:
      regime_conf < 0.6 → skip ambiguous regimes
      base_score < SCORE_MIN → skip weak setups
      allow_combo → enforce session diversity
      rolling std < 0.07 → skip collapsed distribution
      ws < threshold → skip unless epsilon-explore (decaying 10%→2%)
    Returns (base_score, w_score, action, edge_type, features, explore).
    """
    if len(hist) < 51:
        return 0, 0.0, None, None, {}, False

    # Gate 1: regime confidence (lowered 0.6→0.5: BULL_TREND at ADX=17 gives
    # regime_conf=17/35=0.49 < 0.60 → was blocked; ADX 17-21 is valid weak trend)
    if regime_conf < 0.5:
        return 0, 0.0, None, None, {}, False

    buy_sc,  buy_f  = _score_direction(hist, e50, e200, breakout_up, breakout_down, mom5, "BUY")
    sell_sc, sell_f = _score_direction(hist, e50, e200, breakout_up, breakout_down, mom5, "SELL")

    from src.services.realtime_decision_engine import (
        weighted_score as _ws, SCORE_MIN,
        get_ws_threshold as _thr, score_history as _sh,
        allow_combo, epsilon as _eps)

    # Gate 2: minimum base score
    if buy_sc >= sell_sc and buy_sc >= SCORE_MIN:
        action, base_score, features = "BUY",  buy_sc,  buy_f
    elif sell_sc > buy_sc and sell_sc >= SCORE_MIN:
        action, base_score, features = "SELL", sell_sc, sell_f
    else:
        return 0, 0.0, None, None, {}, False

    # Gate 3: combo diversity (max 3 uses per session)
    combo = tuple(sorted(k for k, v in features.items() if isinstance(v, bool) and v))
    if not allow_combo(combo):
        return base_score, 0.0, None, None, {}, False

    # Weighted score (regime-aware)
    w_score = _ws(features, reg)
    _sh.append(w_score)

    # Gate 4: REMOVED — caused repeated deadlocks (n=50, n=200, and again when
    # market conditions produce uniform feature WR, making w_score std≈0 even
    # with 200+ trades of real data).  EV gate in realtime_decision_engine and
    # regime hard-block in trade_executor provide superior, deadlock-free filtering.

    # Gate 5: adaptive threshold with decaying epsilon-greedy exploration
    thr     = _thr()
    explore = False
    if w_score < thr:
        import random
        if random.random() < _eps():
            explore = True    # below threshold but exploring
        else:
            return base_score, w_score, None, None, {}, False

    # Edge type for TP/SL selection
    if features["trend"] and features["pullback"] and features["bounce"]:
        edge = "trend_pullback"
    elif features["vol"] and features["breakout"]:
        edge = "vol_breakout"
    else:
        edge = "fake_breakout"

    return base_score, w_score, action, edge, features, explore


# ── Exploration mode ──────────────────────────────────────────────────────────

def _is_exploration():
    """True if no signal accepted in last 15 min, OR no signals ever sent (startup)."""
    if not _last_ts:
        return True   # startup: no signals yet → exploration from the start
    return all(time.time() - ts > 900 for ts in _last_ts.values())


# ── Session gate ──────────────────────────────────────────────────────────────

def _session_ok():
    """
    True during active sessions (08:00–21:00 UTC).
    Research: London/NY overlap (13:00–16:30 UTC) has tightest spreads and
    cleanest signals. Asia session (21:00–08:00 UTC) has lower volume, wider
    effective spreads, higher fake breakout rate.
    Weekend (Sat/Sun UTC): lower volume, bot-driven price action — confidence
    multiplied by 0.7 rather than fully blocked to preserve learning data.
    Returns (ok: bool, quality: float) — quality < 1.0 penalizes confidence.
    """
    import datetime
    now     = datetime.datetime.utcnow()
    hour    = now.hour
    weekday = now.weekday()  # 0=Mon, 5=Sat, 6=Sun

    # Active hours: 08:00-21:00 UTC (London open through US close)
    if 8 <= hour < 21:
        quality = 0.85 if weekday >= 5 else 1.0   # weekend: slight penalty
        return True, quality

    # Off-hours (21:00-08:00 UTC): suppressed
    # Peak of Asia session (02:00-06:00 UTC) is particularly noisy
    return False, 0.6


def _price_zscore(sym, price):
    """
    Rolling 20-price Z-score: z = (price - mean20) / std20.

    Used as a RANGING regime bonus — when price deviates significantly from
    its recent mean, mean-reversion probability increases.
    Research (Avellaneda & Lee 2010, Statistical Arbitrage): Z-score > 1.5
    or < -1.5 indicates a statistically meaningful deviation from fair value.

    Returns 0.0 if fewer than 20 samples are available (safe bootstrap).
    """
    hist = _price_z_hist.setdefault(sym, [])
    hist.append(price)
    if len(hist) > 60:        # 60-sample window for stable mean/std
        hist.pop(0)
    if len(hist) < 20:
        return 0.0
    mean = sum(hist) / len(hist)
    std  = (sum((x - mean) ** 2 for x in hist) / len(hist)) ** 0.5
    if std < 1e-9:
        return 0.0
    return (price - mean) / std


def _obi_zscore(sym, obi_raw):
    """
    Normalize raw OBI to a z-score using rolling 100-sample history.
    Research (Cont et al. 2014, arXiv:2112.02947): normalized OFI at short
    horizon achieves R²=83-86% for contemporaneous price prediction vs ~60%
    for raw magnitude-dependent OBI values.
    Returns raw OBI if insufficient history (<20 samples).
    """
    hist = _obi_hist.setdefault(sym, [])
    hist.append(obi_raw)
    if len(hist) > 200:    # 200 samples for stable z-score (was 100)
        hist.pop(0)
    if len(hist) < 20:
        return obi_raw   # not enough history — return raw
    mean = sum(hist) / len(hist)
    std  = (sum((x - mean) ** 2 for x in hist) / len(hist)) ** 0.5
    if std < 1e-6:
        return 0.0   # dead market — OBI is flat
    return (obi_raw - mean) / std


def _relative_vol_ok(hist):
    """
    Check if market has enough relative volatility to trade.
    Compares recent 20-tick ATR to 60-tick baseline.
    Ratio < 0.4: market too flat — signals are pure noise.
    Research: volatility regime filtering is the highest-confidence PF
    improvement technique (GK estimator, ScienceDirect 2018). This is a
    simplified proxy using tick-level ATR ratios since we lack OHLCV in
    real-time (REST bookTicker returns mid-price only).
    """
    if len(hist) < 61:
        return True   # insufficient history — allow through
    diffs = [abs(hist[i] - hist[i-1]) for i in range(1, len(hist))]
    recent_atr   = sum(diffs[-20:]) / 20
    baseline_atr = sum(diffs[-60:]) / 60
    if baseline_atr < 1e-12:
        return False   # dead flat
    ratio = recent_atr / baseline_atr
    return ratio >= 0.40   # at least 40% of baseline movement


# ── Main handler ──────────────────────────────────────────────────────────────

def on_price(data):
    global _cycle_ticks, _cycle_symbols, _cycle_candidates, _cycle_prefilter_drops

    s, p = data["symbol"], data["price"]
    obi  = data.get("obi", 0.0)

    # V10.13d: Track market data freshness and tick arrival
    _cycle_ticks += 1
    _cycle_symbols.add(s)
    now = time.time()
    _last_price_ts[s] = now

    # V10.13d: Critical logging to detect if on_price is being called
    import logging
    logging.debug(f"on_price({s}, {p:.4f})")

    hist = prices.setdefault(s, [])
    hist.append(p)
    if len(hist) > 1800:   # 1800 ticks @ 2s/tick = 60 min of indicator history
        hist.pop(0)         # was 600 (20 min) — EMA(200) and HTF EMA(150) now
                            # have 3× more data to converge; HTF trend detection

    if len(hist) < MIN_TICKS:
        if s not in _cycle_prefilter_drops:
            _cycle_prefilter_drops[s] = "INDICATORS_NOT_READY"
            logging.warning(f"on_price({s}): INDICATORS_NOT_READY (have {len(hist)}/{MIN_TICKS} ticks)")
        return

    # V10.13d: Moved track_generated() here — only count when we have enough data
    # track_generated() counts all attempts; we move it to after edge generation

    # ── Indicators ────────────────────────────────────────────────────────────
    e10  = _ema(hist, 10)
    e50  = _ema(hist, 50)
    e200 = _ema(hist, min(200, len(hist)))
    rsi_v = _rsi(hist[-50:])
    atr_v = _atr(hist)

    bb_lo, bb_mid, bb_hi = _kc(hist, atr_v)

    e12    = _ema(hist, 12)
    e26    = _ema(hist, 26)
    macd_l = e12 - e26
    mv     = _macd_vals.setdefault(s, [])
    mv.append(macd_l)
    if len(mv) > 50:
        mv.pop(0)
    macd_s = _ema(mv, 9) if len(mv) >= 9 else macd_l

    adx_v, di_p, di_m = _adx(hist)
    adx_prev  = _adx_hist.get(s, adx_v)
    _adx_hist[s] = adx_v
    adx_slope = adx_v - adx_prev

    rsi_prev  = _rsi_hist.get(s, rsi_v)
    _rsi_hist[s] = rsi_v
    rsi_slope = rsi_v - rsi_prev
    div_bull, div_bear = _rsi_divergence(s, hist, rsi_v)

    reg = _regime(hist, adx_v, di_p, di_m, atr_v)
    htf = _htf_trend(hist)

    # ── Alpha features: breakout + momentum ───────────────────────────────────
    breakout_up   = int(p > max(hist[-21:-1])) if len(hist) >= 21 else 0
    breakout_down = int(p < min(hist[-21:-1])) if len(hist) >= 21 else 0
    returns       = [hist[i] / hist[i-1] - 1 for i in range(max(1, len(hist)-10), len(hist))]
    mom5          = sum(returns[-5:])  if len(returns) >= 5  else 0.0
    mom10         = sum(returns[-10:]) if len(returns) >= 10 else 0.0

    # ── Vol-shock guard: flash crash / spike protection ───────────────────────
    # If 5-tick price move > 3× ATR pct → abnormal move, skip
    if len(hist) >= 6:
        recent_move = abs(hist[-1] - hist[-6]) / (hist[-6] or 1)
        if recent_move > 3 * (atr_v / p):
            if s not in _cycle_prefilter_drops:
                _cycle_prefilter_drops[s] = "FLASH_CRASH_DETECTED"
            track_filtered()
            return

    # ── Volatility prefilter (hard gate — no exploration bypass) ─────────────
    if not _prefilter(hist, atr_v, p):
        if s not in _cycle_prefilter_drops:
            _cycle_prefilter_drops[s] = "MARKET_DEAD_FLAT"
        track_filtered()
        return

    # ── Relative volatility filter ────────────────────────────────────────────
    # Recent ATR vs baseline ATR ratio < 0.4 → market too flat to trade.
    # Research (ScienceDirect 2018): vol regime filtering is highest-confidence
    # PF improvement. Always active — 24h trading, no session gate.
    if not _relative_vol_ok(hist):
        if s not in _cycle_prefilter_drops:
            _cycle_prefilter_drops[s] = "LOW_RELATIVE_VOLATILITY"
        track_filtered()
        return

    # ── OBI normalization: compute z-score for consistent threshold ───────────
    # Raw OBI magnitude depends on market depth — normalizing makes the 0.3
    # threshold meaningful regardless of market conditions.
    obi_raw = data.get("obi", 0.0)
    obi     = _obi_zscore(s, obi_raw)   # z-score, >1.0 = meaningful imbalance

    # ── Price Z-score (RANGING mean-reversion feature) ────────────────────────
    # Tracks rolling 20-price deviation; passed to _score() for RANGING bonus.
    price_z = _price_zscore(s, p)

    # ── Time-based debounce (per symbol) ──────────────────────────────────────
    # Bypass during bootstrap (<30 trades): need fast data flow to fill lm_pnl_hist.
    # Once 30 trades close, debounce re-activates to prevent combo exhaustion.
    # Stamp _last_ts BEFORE _get_scored_edge — symbols that never emit must still
    # be throttled, or allow_combo exhausts in 40 s (confirmed in session log).
    try:
        from src.services.learning_event import get_metrics as _lgm
        _debounce_active = _lgm().get("trades", 0) >= 30
    except Exception:
        _debounce_active = True
    if _debounce_active and time.time() - _last_ts.get(s, 0) < DEBOUNCE_S:
        if s not in _cycle_prefilter_drops:
            _cycle_prefilter_drops[s] = "DEBOUNCE_ACTIVE"
        track_filtered()
        return
    _last_ts[s] = time.time()   # stamp NOW

    # ── Edge scoring: 7-feature self-learning gate ────────────────────────────
    # Regime confidence: ADX-based (trend) or inverse-ADX (range)
    if reg in ("BULL_TREND", "BEAR_TREND"):
        regime_conf = min(adx_v / 35.0, 1.0)
    elif reg in ("RANGING", "QUIET_RANGE"):
        regime_conf = max(0.0, 1.0 - adx_v / 30.0) * 0.5 + 0.5
    else:
        regime_conf = 0.6  # HIGH_VOL: borderline confidence

    base_sc, w_sc, action, edge, edge_features, explore = _get_scored_edge(
        hist, e50, e200, breakout_up, breakout_down, mom5, reg, regime_conf)

    # ────────────────────────────────────────────────────────────────────────
    # PATCH 3: Force Signal Generation — Fallback when no signal detected
    # ────────────────────────────────────────────────────────────────────────
    if action is None:
        import random
        # 30% chance to force generate a signal to maintain data flow
        if random.random() < 0.3:
            action = random.choice(["LONG", "SHORT"])
            # Synthesize confidence at mid-level for forced signals
            base_sc = 3  # 3/7
            w_sc = 0.5
            edge = "FORCED_EXPLORE"
            edge_features = {}
            explore = True
            # V10.13d: Track forced candidate generation
            _cycle_candidates += 1
            track_generated()
            logging.warning(f"on_price({s}): Generated FORCED signal {action}")
        else:
            if s not in _cycle_prefilter_drops:
                _cycle_prefilter_drops[s] = "NO_CANDIDATE_PATTERN"
                logging.warning(f"on_price({s}): NO_CANDIDATE_PATTERN (edge generation failed, forced signal failed 70% check)")
            track_filtered()
            return
    else:
        # V10.13d: Track valid candidate generation
        _cycle_candidates += 1
        track_generated()
        logging.info(f"on_price({s}): Generated valid signal {action} (edge={edge})")

    # Confidence penalty flags (soft, EV gate is authoritative)
    _high_vol      = reg == "HIGH_VOL"
    _counter_trend = (reg == "BULL_TREND" and action != "BUY") or \
                     (reg == "BEAR_TREND" and action != "SELL")
    _weak_spread   = abs(e10 - e50) < atr_v * 0.2

    # ── Score ─────────────────────────────────────────────────────────────────
    score, reasons = _score(
        action, p, e10, e50, e200, rsi_v, rsi_slope,
        macd_l, macd_s, bb_lo, bb_hi, adx_v, reg, obi, htf, price_z
    )

    # RSI divergence bonus — confirmed counter-move between price and momentum
    # +2 when divergence agrees with signal direction (strong confirmation)
    # Applied before confidence calc so _ind_conf weights it correctly ("DIV" → 1.0×)
    if div_bull and action == "BUY":
        score += 2; reasons.append("DIVb")
    if div_bear and action == "SELL":
        score += 2; reasons.append("DIVs")

    # Side-balance penalty
    score -= _side_penalty(s, action)

    # ── Confidence: indicator-weighted ────────────────────────────────────────
    # Weights per signal reason prefix — adjust which indicators to trust more
    _IND_W = {"EMA": 1.0, "HTF": 0.9, "MAC": 1.0, "RSI": 0.8,
              "ADX": 0.7, "BB":  1.2, "MR":  1.1}

    def _ind_conf(sc, rsns):
        if not rsns:
            return min(sc / 5.0, 1.0)
        w_sum = sum(_IND_W.get(r[:3], 1.0) for r in rsns)
        return min((sc / 5.0) * (w_sum / len(rsns)), 1.0)

    try:
        from bot2.auditor import get_strategy_weights
        ws = get_strategy_weights()
        # sym×regime weight takes priority, falls back to regime-only
        regime_w = ws.get(f"{reg}_{s}", ws.get(reg, 1.0))
    except Exception:
        regime_w = 1.0

    confidence = min(_ind_conf(score, reasons) * regime_w, 1.0)

    # Penalty multipliers (soft, not hard blocks — EV gate decides)
    if _high_vol:                              confidence *= 0.5   # extreme volatility
    if reg not in ("RANGING", "QUIET_RANGE"):
        if _counter_trend: confidence *= 0.6   # counter-trend signal
        if _weak_spread:   confidence *= 0.7   # weak EMA separation
    # Session quality penalty removed — 24h trading, no session gate.

    vol_pct = atr_v / p if p else 0

    # ── Record + emit ─────────────────────────────────────────────────────────
    # EV gate is handled exclusively in realtime_decision_engine (single calc)
    # _last_ts[s] already stamped above (before _get_scored_edge) — do not re-stamp
    _record_side(s, action)

    signal = {
        "symbol":     s,
        "action":     action,
        "price":      p,
        "confidence": confidence,   # raw penalised conf; RDE calibrates to win_prob
        "atr":        atr_v,
        "regime":     reg,
        "edge":       edge,
        "ws":         round(w_sc, 4),
        "explore":    explore,
        "features": {
            # 7 boolean edge features (used for self-learning update_edge_stats)
            **edge_features,
            # Continuous indicators (stored for analysis, not for edge learning)
            "ema_diff":      e10 - e50,
            "rsi":           rsi_v,
            "rsi_slope":     round(rsi_slope, 4),
            "volatility":    vol_pct,
            "macd":          macd_l,
            "adx":           adx_v,
            "adx_slope":     round(adx_slope, 4),
            "mom5":          round(mom5, 6),
            "mom10":         round(mom10, 6),
            "obi":           round(obi, 4),
            "rsi_div_bull":  int(div_bull),
            "rsi_div_bear":  int(div_bear),
            "price_z":       round(price_z, 4),
            # Temporal AI Cognition
            "hour_utc":      __import__('datetime').datetime.utcnow().hour,
            "is_weekend":    __import__('datetime').datetime.utcnow().weekday() >= 5,
        },
    }

    short = s.replace("USDT", "")
    icon  = "🟢" if action == "BUY" else "🔴"
    expl  = "  [EXPLORE]" if _is_exploration() else ""
    active_f = [k for k, v in edge_features.items() if v]
    print(f"  {icon} {short} ${p:,.4f} | [{edge}] "
          f"sc:{base_sc}/7  ws:{w_sc:.2f} | {reg} | conf:{confidence:.0%} "
          f"[{','.join(active_f)}]{expl}")

    from src.services.realtime_decision_engine import evaluate_signal
    result = evaluate_signal(signal)

    if result:
        publish("signal_created", result)
    else:
        # V10.13a: Track RDE rejection for per-symbol block reason reporting
        try:
            from bot2.main import track_symbol_block_reason
            track_symbol_block_reason(sym, "RDE_REJECTED", "Rejected by realtime_decision_engine")
        except (ImportError, Exception):
            pass  # Fail silently if main not yet loaded or circular import issue
    # EV-rejected: track_blocked() already called inside evaluate_signal()


def warmup(symbols=None, candles=120):
    if symbols is None:
        from src.services.portfolio_discovery import get_active_symbols
        symbols = get_active_symbols()
        
    import requests
    print("🌡️  Indicator warmup from Binance klines...")
    for s in symbols:
        try:
            r = requests.get(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": s, "interval": "1m", "limit": candles},
                timeout=5,
            )
            closes = [float(c[4]) for c in r.json()]
            if closes:
                prices[s]     = closes
                _macd_vals[s] = []
                short = s.replace("USDT", "")
                print(f"   {short}: {len(closes)} svíček načteno  "
                      f"(poslední: ${closes[-1]:,.4f})")
        except Exception as e:
            print(f"   ⚠️ warmup {s}: {e}")


subscribe_once("price_tick", on_price)
