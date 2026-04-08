"""
V10.8 Regime Transition Predictor — deterministic regime switch detection.

Inputs consumed from signal dict:
  features.ema_diff   EMA10 - EMA50 (normalized): directional momentum
  features.rsi        RSI value [0, 100]
  features.rsi_slope  RSI rate of change (signal_generator computed)
  features.adx        ADX trend strength
  atr                 absolute ATR (normalized to % of price internally)
  price               current price

Derived signals:
  momentum_change  = ema_diff  (+ = bullish momentum building)
  vol_delta        = atr_pct / EMA(atr_pct)  (>1 = rising volatility)
  micro_score      = RSI direction + slope composite (+1=bull, -1=bear, 0=neutral)

Output:
  predicted_regime ∈ {BULL_TREND, BEAR_TREND, HIGH_VOL, <current_regime>}
  Returns current_regime when no transition is confidently predicted.

State:
  _atr_ema — per-symbol EMA of ATR% (in-memory; resets to current value on first
  observation, converges within ~20 ticks). Fully deterministic, no randomness.
"""

_atr_ema: dict = {}     # sym → smoothed ATR percentage
_ATR_ALPHA = 0.10       # EMA smoothing factor for ATR


def _update_atr_ema(sym: str, atr_pct: float) -> float:
    """EMA-smooth ATR percentage per symbol. Returns updated EMA."""
    prev = _atr_ema.get(sym)
    if prev is None:
        _atr_ema[sym] = atr_pct
        return atr_pct
    updated = _ATR_ALPHA * atr_pct + (1.0 - _ATR_ALPHA) * prev
    _atr_ema[sym] = updated
    return updated


def _micro_pattern_score(rsi: float, rsi_slope: float) -> int:
    """Classify micro-pattern from RSI level and slope.

    +1 (bullish) — RSI > 55 and rising
    -1 (bearish) — RSI < 45 and falling
     0 (neutral) — otherwise
    """
    if rsi > 55 and rsi_slope > 0:
        return 1
    if rsi < 45 and rsi_slope < 0:
        return -1
    return 0


def predicted_regime(signal: dict, current_regime: str, meta_mode: str) -> str:
    """Predict next regime deterministically from current signal features.

    Prediction hierarchy (first match wins):
      1. HIGH_VOL   — vol_delta > 1.4 AND atr_pct > 1.2%  (volatility surge)
      2. BULL_TREND — ema_diff > +0.0005, adx > 22, micro not bearish
      3. BEAR_TREND — ema_diff < -0.0005, adx > 22, micro not bullish
      4. current_regime — no transition predicted

    Defensive mode: only HIGH_VOL transition is surfaced; trend predictions
    are suppressed to avoid adding risk in a declining system.
    """
    sym      = signal.get("symbol", "")
    features = signal.get("features", {})
    price    = signal.get("price", 1.0) or 1.0
    atr      = signal.get("atr", 0.0) or 0.0

    ema_diff  = features.get("ema_diff",  0.0)
    rsi       = features.get("rsi",       50.0)
    rsi_slope = features.get("rsi_slope", 0.0)
    adx       = features.get("adx",       0.0)

    atr_pct   = atr / price
    atr_ema   = _update_atr_ema(sym, atr_pct)
    vol_delta = atr_pct / max(atr_ema, 1e-9)   # > 1 = current vol above average

    micro = _micro_pattern_score(rsi, rsi_slope)

    # HIGH_VOL: volatility surge — predict chaotic regime regardless of mode
    if vol_delta > 1.4 and atr_pct > 0.012:
        return "HIGH_VOL"

    # Defensive: suppress trend predictions — only volatility warnings surfaced
    if meta_mode == "defensive":
        return current_regime

    # BULL_TREND: positive EMA momentum + trend strength + non-bearish micro
    if ema_diff > 0.0005 and adx > 22 and micro >= 0:
        return "BULL_TREND"

    # BEAR_TREND: negative EMA momentum + trend strength + non-bullish micro
    if ema_diff < -0.0005 and adx > 22 and micro <= 0:
        return "BEAR_TREND"

    return current_regime
