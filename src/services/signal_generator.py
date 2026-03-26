"""
Professional multi-indicator signal generator.

Strategy (research-backed):
  BULL_TREND regime  → trend-following BUY
    confirm: EMA10>EMA50, price>EMA200, RSI 45-70, MACD cross above zero, ADX>25
  BEAR_TREND regime  → trend-following SELL (mirror)
  RANGING regime     → mean-reversion on BB extremes + RSI divergence
  HIGH_VOL / QUIET   → skip (too noisy / no edge)

Signal score ≥ 3 required before passing to decision engine.
Debounce prevents repeat signals in same direction.
"""

from src.core.event_bus import subscribe, publish
from src.services.learning_event import track_generated, track_filtered
import math

prices     = {}   # symbol -> list[float], capped at 600
_macd_vals = {}   # symbol -> list[float]  (MACD line history for signal EMA)
_last_act  = {}   # symbol -> last action  (debounce)

MIN_TICKS = 50    # warm-up ticks before generating any signals


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
    """ADX approximation from single-price stream (no OHLCV)."""
    if len(series) < n * 2:
        return 20.0, 50.0, 50.0

    ups   = [max(series[i] - series[i-1], 0) for i in range(1, len(series))]
    downs = [max(series[i-1] - series[i], 0) for i in range(1, len(series))]
    trs   = [abs(series[i] - series[i-1])    for i in range(1, len(series))]

    tr_s = _ema(trs[-n*3:],   n) or 1e-9
    di_p = 100 * _ema(ups[-n*3:],   n) / tr_s
    di_m = 100 * _ema(downs[-n*3:], n) / tr_s
    adx  = 100 * abs(di_p - di_m) / ((di_p + di_m) or 1e-9)

    return adx, di_p, di_m


# ── Regime ────────────────────────────────────────────────────────────────────

def _regime(series, adx, di_p, di_m, atr_val):
    curr    = series[-1]
    atr_pct = atr_val / curr if curr else 0

    # BB width for range detection
    bb_lo, bb_mid, bb_hi = _bb(series)
    bb_w = (bb_hi - bb_lo) / bb_mid if bb_mid else 0

    if atr_pct > 0.012:          return "HIGH_VOL"
    if adx > 25 and di_p > di_m: return "BULL_TREND"
    if adx > 25 and di_m > di_p: return "BEAR_TREND"
    if adx < 20 and bb_w < 0.015: return "QUIET_RANGE"
    return "RANGING"


# ── Signal score (triple-confirmation system) ─────────────────────────────────

def _score(action, curr, e10, e50, e200, rsi_v,
           macd_l, macd_s, bb_lo, bb_hi, adx_v, regime):
    """
    Return (score, reasons).
    Each confirming condition adds 1 point.
    BB mean-reversion adds 2 (strong signal).
    Minimum score 2 required.
    """
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
    else:
        if e10 < e50:                              sc += 1; reasons.append("EMA↓")
        if curr < e200:                            sc += 1; reasons.append("HTF↓")
        if 30 < rsi_v < 55:                        sc += 1; reasons.append(f"RSI{rsi_v:.0f}")
        if macd_l < macd_s and macd_l < 0:         sc += 1; reasons.append("MACD0↓")
        elif macd_l < macd_s:                      sc += 1; reasons.append("MACD↓")
        if regime == "BEAR_TREND":                  sc += 1; reasons.append("ADX↓")
        if curr >= bb_hi * 0.997 and rsi_v > 65:   sc += 2; reasons.append("BB↩H")

    return sc, reasons


# ── Main handler ──────────────────────────────────────────────────────────────

def on_price(data):
    s, p = data["symbol"], data["price"]
    hist = prices.setdefault(s, [])
    hist.append(p)
    if len(hist) > 600:
        hist.pop(0)

    if len(hist) < MIN_TICKS:
        return  # silent warm-up

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
    reg = _regime(hist, adx_v, di_p, di_m, atr_v)

    # ── Regime gate ───────────────────────────────────────────────────────────
    if reg in ("HIGH_VOL", "QUIET_RANGE"):
        track_filtered()
        return

    # ── Direction from EMA crossover ──────────────────────────────────────────
    if e10 > e50:
        action = "BUY"
    elif e10 < e50:
        action = "SELL"
    else:
        track_filtered()
        return

    # Regime-direction alignment: in a strong trend, only trade with the trend
    if reg == "BULL_TREND" and action != "BUY":
        track_filtered()
        return
    if reg == "BEAR_TREND" and action != "SELL":
        track_filtered()
        return

    # ── EMA spread filter: prevent weak/stale crossovers ──────────────────────
    # Require EMA10-EMA50 gap > 20% of ATR to confirm trend has strength
    ema_spread = abs(e10 - e50)
    if ema_spread < atr_v * 0.2:
        track_filtered()
        return

    # ── Score ─────────────────────────────────────────────────────────────────
    score, reasons = _score(
        action, p, e10, e50, e200, rsi_v,
        macd_l, macd_s, bb_lo, bb_hi, adx_v, reg
    )

    if score < 3:
        track_filtered()
        return

    # ── Debounce ──────────────────────────────────────────────────────────────
    if _last_act.get(s) == action:
        track_filtered()
        return
    _last_act[s] = action

    # ── Confidence: score/5  (score ≥ 3 required, max = 5+) ──────────────────
    confidence = min(score / 5.0, 1.0)
    vol_pct    = atr_v / p if p else 0

    signal = {
        "symbol":     s,
        "action":     action,
        "price":      p,
        "confidence": confidence,
        "atr":        atr_v,
        "regime":     reg,
        "features": {
            "ema_diff":   e10 - e50,
            "rsi":        rsi_v,
            "volatility": vol_pct,
            "macd":       macd_l,
            "adx":        adx_v,
        },
    }

    short = s.replace("USDT", "")
    icon  = "🟢" if action == "BUY" else "🔴"
    print(f"  {icon} {short} ${p:,.4f} | "
          f"score:{score} [{','.join(reasons)}] | {reg} | conf:{confidence:.0%}")

    from src.services.realtime_decision_engine import evaluate_signal
    result = evaluate_signal(signal)

    if result:
        publish("signal_created", result)
    else:
        track_filtered()


def warmup(symbols=("BTCUSDT", "ETHUSDT", "ADAUSDT"), candles=80):
    """
    Pre-fill price history from Binance 1-minute klines so indicators
    are ready immediately on startup (no 50-tick / ~5-min wait).
    Uses closing prices of last `candles` 1-minute candles per symbol.
    """
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
                _macd_vals[s] = []   # will rebuild from ticks
                short = s.replace("USDT", "")
                print(f"   {short}: {len(closes)} svíček načteno  "
                      f"(poslední: ${closes[-1]:,.4f})")
        except Exception as e:
            print(f"   ⚠️ warmup {s}: {e}")


subscribe("price_tick", on_price)
