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
"""

from src.core.event_bus       import subscribe_once, publish
from src.services.learning_event import track_generated, track_filtered
import math, time

prices     = {}   # symbol -> list[float], capped at 600
_macd_vals = {}   # symbol -> list[float]
_last_ts   = {}   # symbol -> float (last signal timestamp, time-based debounce)
_side_hist = {}   # symbol -> deque[action], last 10 actions
_adx_hist  = {}   # symbol -> float (last adx, for slope)
_rsi_hist  = {}   # symbol -> float (last rsi, for slope)

# Flat TP/SL (must match trade_executor._TP_MULT/_SL_MULT + realtime_decision_engine)
_TP_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0,
            "RANGING":    1.0, "QUIET_RANGE": 1.0}
_SL_MULT = {"BULL_TREND": 0.8, "BEAR_TREND": 0.8,
            "RANGING":    0.8, "QUIET_RANGE": 0.8}
MIN_TP_PCT = 0.0025
MIN_SL_PCT = 0.0020

MIN_TICKS    = 50
DEBOUNCE_S   = 30    # seconds between signals per symbol
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


def _bb(series, n=20):
    w   = series[-n:]
    mid = sum(w) / len(w)
    std = math.sqrt(sum((x - mid) ** 2 for x in w) / len(w)) or 1e-9
    return mid - 2 * std, mid, mid + 2 * std


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
    bb_lo, bb_mid, bb_hi = _bb(series)
    bb_w = (bb_hi - bb_lo) / bb_mid if bb_mid else 0

    if atr_pct > 0.012:          return "HIGH_VOL"
    if adx > 25 and di_p > di_m: return "BULL_TREND"
    if adx > 25 and di_m > di_p: return "BEAR_TREND"
    if adx < 20 and bb_w < 0.015: return "QUIET_RANGE"
    return "RANGING"


# ── Score (regime-aware) ──────────────────────────────────────────────────────

def _score(action, curr, e10, e50, e200, rsi_v, rsi_slope,
           macd_l, macd_s, bb_lo, bb_hi, adx_v, regime, htf=None):
    sc = 0
    reasons = []

    if action == "BUY":
        if e10 > e50:                              sc += 1; reasons.append("EMA↑")
        if curr > e200:                            sc += 1; reasons.append("HTF↑")
        if 45 < rsi_v < 70:                        sc += 1; reasons.append(f"RSI{rsi_v:.0f}")
        if macd_l > macd_s and macd_l > 0:         sc += 1; reasons.append("MACD0↑")
        elif macd_l > macd_s:                      sc += 1; reasons.append("MACD↑")
        if regime == "BULL_TREND":                  sc += 1; reasons.append("ADX↑")
        if curr <= bb_lo * 1.003 and rsi_v < 35:   sc += 2; reasons.append("BB↩L")
        elif curr <= bb_lo * 1.005 and rsi_v < 40: sc += 1; reasons.append("BBlo")
        # Mean-reversion bonus: RSI slope confirms bounce direction
        if regime in ("RANGING", "QUIET_RANGE"):
            if rsi_v < 30:
                if rsi_slope > 0: sc += 3; reasons.append("MR↓↓✓")
                else:             sc += 2; reasons.append("MR↓↓")
            elif rsi_v < 42:      sc += 1; reasons.append("MR↓")
    else:
        if e10 < e50:                              sc += 1; reasons.append("EMA↓")
        if curr < e200:                            sc += 1; reasons.append("HTF↓")
        if 30 < rsi_v < 55:                        sc += 1; reasons.append(f"RSI{rsi_v:.0f}")
        if macd_l < macd_s and macd_l < 0:         sc += 1; reasons.append("MACD0↓")
        elif macd_l < macd_s:                      sc += 1; reasons.append("MACD↓")
        if regime == "BEAR_TREND":                  sc += 1; reasons.append("ADX↓")
        if curr >= bb_hi * 0.997 and rsi_v > 65:   sc += 2; reasons.append("BB↩H")
        elif curr >= bb_hi * 0.995 and rsi_v > 60: sc += 1; reasons.append("BBhi")
        # Mean-reversion bonus: RSI slope confirms reversal
        if regime in ("RANGING", "QUIET_RANGE"):
            if rsi_v > 70:
                if rsi_slope < 0: sc += 3; reasons.append("MR↑↑✓")
                else:             sc += 2; reasons.append("MR↑↑")
            elif rsi_v > 58:      sc += 1; reasons.append("MR↑")

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

def _prefilter(hist, atr_v, price):
    """
    Require volatility expansion: recent 20-bar avg range > 50-bar avg range.
    Maps to spec: vol.rolling(20).std().iloc[-1] > vol.mean()
    Ensures market is active and directional, not dead-flat.
    """
    if len(hist) < 51:
        return False
    diffs = [abs(hist[i] - hist[i-1]) for i in range(1, len(hist))]
    r20   = sum(diffs[-20:]) / 20
    r50   = sum(diffs[-50:]) / 50
    return r20 > r50   # expanding vol: recent range > longer-term average


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


def _get_scored_edge(hist, e50, e200, breakout_up, breakout_down, mom5):
    """
    Score BUY and SELL setups; pick direction with base_score >= SCORE_MIN.
    Apply weighted_score >= W_SCORE_MIN gate (self-learning).
    Returns (base_score, w_score, action, edge_type, features) or (0,0,None,None,{}).
    """
    if len(hist) < 51:
        return 0, 0.0, None, None, {}

    buy_sc,  buy_f  = _score_direction(hist, e50, e200, breakout_up, breakout_down, mom5, "BUY")
    sell_sc, sell_f = _score_direction(hist, e50, e200, breakout_up, breakout_down, mom5, "SELL")

    # Pick direction with higher score; require minimum SCORE_MIN
    from src.services.realtime_decision_engine import weighted_score as _ws, SCORE_MIN
    if buy_sc >= sell_sc and buy_sc >= SCORE_MIN:
        action, base_score, features = "BUY",  buy_sc,  buy_f
    elif sell_sc > buy_sc and sell_sc >= SCORE_MIN:
        action, base_score, features = "SELL", sell_sc, sell_f
    else:
        return 0, 0.0, None, None, {}

    # Self-learning weighted score gate (adaptive threshold + stability guard)
    from src.services.realtime_decision_engine import (
        get_ws_threshold as _thr, score_history as _sh, _std)
    w_score = _ws(features)
    _sh.append(w_score)           # track all evaluated scores (including rejected)

    # Stability guard: collapsed score distribution = no edge differentiation
    if len(_sh) >= 50 and _std(list(_sh)) < 0.05:
        return base_score, w_score, None, None, {}

    if w_score < _thr():
        return base_score, w_score, None, None, {}

    # Edge type classification for TP/SL selection
    if features["trend"] and features["pullback"] and features["bounce"]:
        edge = "trend_pullback"
    elif features["vol"] and features["breakout"]:
        edge = "vol_breakout"
    else:
        edge = "fake_breakout"

    return base_score, w_score, action, edge, features


# ── Exploration mode ──────────────────────────────────────────────────────────

def _is_exploration():
    """True if no signal accepted in last 15 min, OR no signals ever sent (startup)."""
    if not _last_ts:
        return True   # startup: no signals yet → exploration from the start
    return all(time.time() - ts > 900 for ts in _last_ts.values())


# ── Main handler ──────────────────────────────────────────────────────────────

def on_price(data):
    s, p = data["symbol"], data["price"]
    hist = prices.setdefault(s, [])
    hist.append(p)
    if len(hist) > 600:
        hist.pop(0)

    if len(hist) < MIN_TICKS:
        return

    track_generated()

    # ── Indicators ────────────────────────────────────────────────────────────
    e10  = _ema(hist, 10)
    e50  = _ema(hist, 50)
    e200 = _ema(hist, min(200, len(hist)))
    rsi_v = _rsi(hist[-50:])
    atr_v = _atr(hist)

    bb_lo, bb_mid, bb_hi = _bb(hist)

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

    reg = _regime(hist, adx_v, di_p, di_m, atr_v)
    htf = _htf_trend(hist)

    # ── Alpha features: breakout + momentum ───────────────────────────────────
    breakout_up   = int(p > max(hist[-21:-1])) if len(hist) >= 21 else 0
    breakout_down = int(p < min(hist[-21:-1])) if len(hist) >= 21 else 0
    returns       = [hist[i] / hist[i-1] - 1 for i in range(max(1, len(hist)-10), len(hist))]
    mom5          = sum(returns[-5:])  if len(returns) >= 5  else 0.0
    mom10         = sum(returns[-10:]) if len(returns) >= 10 else 0.0

    # ── Volatility prefilter (hard gate — no exploration bypass) ─────────────
    if not _prefilter(hist, atr_v, p):
        track_filtered()
        return

    # ── Edge scoring: 7-feature self-learning gate ────────────────────────────
    base_sc, w_sc, action, edge, edge_features = _get_scored_edge(
        hist, e50, e200, breakout_up, breakout_down, mom5)
    if action is None:
        track_filtered()
        return

    # Confidence penalty flags (soft, EV gate is authoritative)
    _high_vol      = reg == "HIGH_VOL"
    _counter_trend = (reg == "BULL_TREND" and action != "BUY") or \
                     (reg == "BEAR_TREND" and action != "SELL")
    _weak_spread   = abs(e10 - e50) < atr_v * 0.2

    # ── Time-based debounce (30 s per symbol) ─────────────────────────────────
    if time.time() - _last_ts.get(s, 0) < DEBOUNCE_S:
        track_filtered()
        return

    # ── Score ─────────────────────────────────────────────────────────────────
    score, reasons = _score(
        action, p, e10, e50, e200, rsi_v, rsi_slope,
        macd_l, macd_s, bb_lo, bb_hi, adx_v, reg, htf
    )

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

    vol_pct = atr_v / p if p else 0

    # ── Record + emit ─────────────────────────────────────────────────────────
    # EV gate is handled exclusively in realtime_decision_engine (single calc)
    _last_ts[s] = time.time()
    _record_side(s, action)

    signal = {
        "symbol":     s,
        "action":     action,
        "price":      p,
        "confidence": confidence,   # raw penalised conf; RDE calibrates to win_prob
        "atr":        atr_v,
        "regime":     reg,
        "edge":       edge,
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
    # EV-rejected: track_blocked() already called inside evaluate_signal()


def warmup(symbols=("BTCUSDT", "ETHUSDT", "ADAUSDT"), candles=80):
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
