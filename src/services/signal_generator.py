"""
Multi-indicator signal generator.

Regime-aware logic:
  BULL_TREND / BEAR_TREND  → trend-following (EMA × ADX × MACD)
  RANGING                  → mean-reversion  (RSI extremes + BB)
  QUIET_RANGE              → mean-reversion, strict score ≥ 3
  HIGH_VOL                 → skip (too noisy)

Score thresholds:
  trending:        ≥ 3
  ranging/quiet:   ≥ 2   (RSI extreme + BB already gives ≥ 3)
  fallback mode:   ≥ 2   (no trades ≥ 15 min)

Side balance:  if >60% one side in last 10 signals → penalise score −1
Time debounce: 30 s per symbol (regardless of direction)
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

# Regime-aware TP/SL (must match trade_executor._TP_MULT/_SL_MULT)
_TP_MULT = {"BULL_TREND": 3.0, "BEAR_TREND": 3.0,
            "RANGING": 1.8, "QUIET_RANGE": 1.6}
_SL_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0,
            "RANGING": 1.2, "QUIET_RANGE": 1.0}
MIN_TP_PCT = 0.0050
MIN_SL_PCT = 0.0025

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
           macd_l, macd_s, bb_lo, bb_hi, adx_v, regime):
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

    # ── Regime gate ───────────────────────────────────────────────────────────
    if reg == "HIGH_VOL":
        track_filtered()
        return

    # ── Direction — regime-aware ───────────────────────────────────────────────
    if reg in ("RANGING", "QUIET_RANGE"):
        # Mean-reversion: RSI extremes only
        if   rsi_v < 30: action = "BUY"
        elif rsi_v > 70: action = "SELL"
        else:
            # Looser trigger in exploration mode
            if _is_exploration():
                if   rsi_v < 40: action = "BUY"
                elif rsi_v > 60: action = "SELL"
                else:
                    track_filtered(); return
            else:
                track_filtered(); return
    else:
        # Trend-following: EMA crossover
        if   e10 > e50: action = "BUY"
        elif e10 < e50: action = "SELL"
        else:
            track_filtered(); return

        # Trend-direction alignment
        if reg == "BULL_TREND" and action != "BUY":
            track_filtered(); return
        if reg == "BEAR_TREND" and action != "SELL":
            track_filtered(); return

        # HTF confirmation: block only hard disagreement (not FLAT)
        if reg == "BULL_TREND" and htf == "DOWN":
            track_filtered(); return
        if reg == "BEAR_TREND" and htf == "UP":
            track_filtered(); return

        # EMA spread filter (trend only — not RANGING)
        ema_spread = abs(e10 - e50)
        if ema_spread < atr_v * 0.2:
            track_filtered(); return

    # ── Time-based debounce (30 s per symbol) ─────────────────────────────────
    if time.time() - _last_ts.get(s, 0) < DEBOUNCE_S:
        track_filtered()
        return

    # ── Score ─────────────────────────────────────────────────────────────────
    score, reasons = _score(
        action, p, e10, e50, e200, rsi_v, rsi_slope,
        macd_l, macd_s, bb_lo, bb_hi, adx_v, reg
    )

    # Side-balance penalty
    score -= _side_penalty(s, action)

    # Threshold: 2 in ranging, 2 in exploration, 3 normally
    exploration = _is_exploration()
    min_score   = 2 if (reg in ("RANGING", "QUIET_RANGE") or exploration) else 3

    if score < min_score:
        track_filtered()
        return

    # ── Filter guard: anti-collapse (pass-rate < 2% → force pass score ≥ 1) ──
    from src.services.learning_event import get_metrics as _gm
    _m  = _gm()
    gen = _m.get("signals_generated", 0)
    flt = _m.get("signals_filtered",  0)
    blk = _m.get("blocked", 0)
    _collapsed = False
    if gen > 50:
        passed   = max(0, gen - flt - blk)
        pass_pct = passed / gen
        if pass_pct < 0.05:
            _collapsed = True   # collapse: pass anything with score ≥ 1

    if not _collapsed and score < min_score:
        track_filtered()
        return

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
    vol_pct = atr_v / p if p else 0

    # ── EV gate: regime-aware TP/SL ratio ────────────────────────────────────
    tp_move = max(atr_v * _TP_MULT.get(reg, 2.2) / p, MIN_TP_PCT)
    sl_move = max(atr_v * _SL_MULT.get(reg, 1.3) / p, MIN_SL_PCT)
    rr      = tp_move / sl_move
    ev      = confidence * rr - (1 - confidence)
    if ev <= 0:
        track_filtered()
        return

    # ── Record + emit ─────────────────────────────────────────────────────────
    _last_ts[s] = time.time()
    _record_side(s, action)

    signal = {
        "symbol":     s,
        "action":     action,
        "price":      p,
        "confidence": confidence,
        "atr":        atr_v,
        "regime":     reg,
        "ev":         round(ev, 4),
        "features": {
            "ema_diff":   e10 - e50,
            "rsi":        rsi_v,
            "rsi_slope":  round(rsi_slope, 4),
            "volatility": vol_pct,
            "macd":       macd_l,
            "adx":        adx_v,
            "adx_slope":  round(adx_slope, 4),
        },
    }

    short = s.replace("USDT", "")
    icon  = "🟢" if action == "BUY" else "🔴"
    expl  = "  [EXPLORE]" if exploration else ""
    print(f"  {icon} {short} ${p:,.4f} | "
          f"score:{score} [{','.join(reasons)}] | {reg} | conf:{confidence:.0%}{expl}")

    from src.services.realtime_decision_engine import evaluate_signal
    result = evaluate_signal(signal)

    if result:
        publish("signal_created", result)
    else:
        track_filtered()


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
