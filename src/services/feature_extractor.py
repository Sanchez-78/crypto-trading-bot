"""
Alpha feature engineering — separates win/loss trades via market structure.

Functions:
  regime(candles)   → EMA50/EMA200 trend + trend_strength (EMA50 slope)
  momentum(candles) → mom5, mom10, breakout_up, breakout_down
  vol(candles)      → vol (20-bar return std), atr (14-bar ATR)
  entry(candles)    → wick ratio, body size of last candle
  build(candles)    → all features combined; raises ValueError if < 200 candles

Breakout definition:
  breakout_up   = 1 if close[-1] > max(close[-21:-1])   (upside 20-bar breakout)
  breakout_down = 1 if close[-1] < min(close[-21:-1])   (downside 20-bar breakdown)
  Use in signal_generator: BUY requires breakout_up, SELL requires breakout_down
                            (trend regimes only — not RANGING/QUIET_RANGE)
"""

import numpy as np


def _ema_v(arr, n):
    """Scalar EMA of a list/array. Returns last value only."""
    if not len(arr):
        return 0.0
    n = min(n, len(arr))
    k = 2.0 / (n + 1)
    v = float(np.mean(arr[:n]))
    for x in arr[n:]:
        v = float(x) * k + v * (1 - k)
    return v


def _ema_arr(arr, n):
    """Full EMA array (same length as arr)."""
    if not len(arr):
        return np.array([])
    k = 2.0 / (n + 1)
    out = np.empty(len(arr))
    out[0] = arr[0]
    for i in range(1, len(arr)):
        out[i] = arr[i] * k + out[i-1] * (1 - k)
    return out


# ── Alpha features ─────────────────────────────────────────────────────────────

def regime(candles):
    """EMA50/EMA200 trend direction and slope-based strength."""
    closes = np.array([float(c["close"]) for c in candles])
    e50    = _ema_arr(closes, 50)
    e200   = _ema_arr(closes, 200)
    trend  = int(e50[-1] > e200[-1])                    # 1=bull, 0=bear
    trend_strength = float(e50[-1] - e50[-2]) if len(e50) >= 2 else 0.0
    return {"trend": trend, "trend_strength": trend_strength}


def momentum(candles):
    """5/10-bar momentum and 20-bar breakout."""
    closes  = np.array([float(c["close"]) for c in candles])
    returns = np.diff(closes) / closes[:-1]
    mom5    = float(returns[-5:].sum())  if len(returns) >= 5  else 0.0
    mom10   = float(returns[-10:].sum()) if len(returns) >= 10 else 0.0
    # Breakout: current close vs 20-bar range (excluding current bar)
    if len(closes) >= 21:
        hi20 = float(np.max(closes[-21:-1]))
        lo20 = float(np.min(closes[-21:-1]))
        breakout_up   = int(closes[-1] > hi20)
        breakout_down = int(closes[-1] < lo20)
    else:
        breakout_up = breakout_down = 0
    return {
        "mom5":          mom5,
        "mom10":         mom10,
        "breakout_up":   breakout_up,
        "breakout_down": breakout_down,
    }


def vol(candles):
    """20-bar return volatility and 14-bar ATR."""
    closes  = np.array([float(c["close"]) for c in candles])
    returns = np.diff(closes) / closes[:-1]
    v       = float(np.std(returns[-20:])) if len(returns) >= 20 else 0.0

    # ATR: use high/low if available, else abs return proxy
    if "high" in candles[0] and "low" in candles[0]:
        highs = np.array([float(c["high"]) for c in candles])
        lows  = np.array([float(c["low"])  for c in candles])
        trs   = highs[1:] - lows[1:]
        atr_v = float(np.mean(np.abs(trs[-14:]))) if len(trs) >= 14 else v * closes[-1]
    else:
        atr_v = float(np.mean(np.abs(np.diff(closes[-15:])))) if len(closes) >= 15 else 0.0

    return {"vol": v, "atr": atr_v}


def entry(candles):
    """Last-candle wick ratio and body size."""
    c = candles[-1]
    hi  = float(c.get("high",  c["close"]))
    lo  = float(c.get("low",   c["close"]))
    op  = float(c.get("open",  c["close"]))
    cl  = float(c["close"])
    rng = hi - lo or 1e-9
    wick = (hi - cl) / rng           # upper wick fraction (0→1)
    body = abs(cl - op)              # absolute body size
    return {"wick": wick, "body": body}


def build(candles):
    """
    Build full alpha feature dict from OHLCV candle list.
    Requires >= 200 candles for EMA200.
    Raises ValueError if insufficient data.
    """
    if len(candles) < 200:
        raise ValueError(f"build() needs ≥200 candles, got {len(candles)}")
    f = {}
    f.update(regime(candles))
    f.update(momentum(candles))
    f.update(vol(candles))
    f.update(entry(candles))
    return f


# ── Legacy wrappers (backward compat) ─────────────────────────────────────────

def extract_features(candles):
    if not candles or len(candles) < 20:
        return None
    closes = np.array([float(c["close"]) for c in candles])
    try:
        v_feat   = vol(candles)
        mom_feat = momentum(candles)
        return {
            "rsi":        float(np.mean(closes[-14:]) / closes[-1]),
            "macd":       float((closes[-1] - np.mean(closes[-26:])) / closes[-1]),
            "ema":        float((_ema_v(closes.tolist(), 10) - closes[-1]) / closes[-1]),
            "bb":         float((np.max(closes[-20:]) - closes[-1]) / closes[-1]),
            "atr":        v_feat["atr"] / closes[-1],
            "mom5":       mom_feat["mom5"],
            "mom10":      mom_feat["mom10"],
            "breakout_up":   mom_feat["breakout_up"],
            "breakout_down": mom_feat["breakout_down"],
        }
    except Exception as e:
        print("❌ Feature error:", e)
        return None


def extract_multi_tf_features(candles_m15, candles_h1, candles_h4):
    f15 = extract_features(candles_m15)
    f1  = extract_features(candles_h1)
    f4  = extract_features(candles_h4)
    if not f15 or not f1 or not f4:
        return None
    return {
        "rsi_m15": f15["rsi"], "macd_m15": f15["macd"],
        "ema_m15": f15["ema"], "bb_m15":   f15["bb"],  "atr_m15": f15["atr"],
        "rsi_h1":  f1["rsi"],  "macd_h1":  f1["macd"],
        "ema_h1":  f1["ema"],  "bb_h1":    f1["bb"],   "atr_h1":  f1["atr"],
        "rsi_h4":  f4["rsi"],  "macd_h4":  f4["macd"],
        "ema_h4":  f4["ema"],  "bb_h4":    f4["bb"],   "atr_h4":  f4["atr"],
        "trend":     "BULL" if f4["ema"] > 0 else "BEAR",
        "volatility": "HIGH" if f15["atr"] > 0.01 else "NORMAL",
        "regime":    "BULL_TREND" if f4["ema"] > 0 else "RANGE",
        "price":     candles_m15[-1]["close"],
        "breakout_up":   f15["breakout_up"],
        "breakout_down": f15["breakout_down"],
    }
