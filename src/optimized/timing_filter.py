from __future__ import annotations
from datetime import datetime


class AdaptiveTimingFilter:
    """ATR-regime adaptive entry windows.

    Regime → max candle-time fraction:
      low     → 20%
      normal  → 35%
      high    → 60%
      extreme → 80%

    ENTER_REDUCED = positive EV + uncertainty → Kelly-smaller size.
    Sources: Maven Securities alpha decay, LuxAlgo +34% profitability.
    """

    REGIME_WINDOWS = {"low": 0.20, "normal": 0.35, "high": 0.60, "extreme": 0.80}

    def __init__(self, candle_seconds: int = 3600):
        self.candle_seconds = candle_seconds

    def evaluate(
        self,
        signal_time: datetime,
        candle_open_time: datetime,
        current_price: float,
        candle_open: float,
        candle_high: float,
        candle_low: float,
        atr: float,
        atr_pct_history: list,
    ) -> dict:
        elapsed = (signal_time - candle_open_time).total_seconds()
        time_frac = elapsed / self.candle_seconds
        atr_pct = (atr / current_price) * 100 if current_price > 0 else 0
        regime = self._classify(atr_pct, atr_pct_history)
        max_time = self.REGIME_WINDOWS[regime]
        disp = abs(current_price - candle_open) / atr if atr > 0 else 999
        range_ratio = (candle_high - candle_low) / atr if atr > 0 else 0

        if time_frac <= max_time and range_ratio < 0.8:
            return {"action": "ENTER", "size": 1.0, "regime": regime}
        if disp < 0.25:
            return {"action": "ENTER_REDUCED", "size": 0.5, "regime": regime}
        if disp < 0.15 and range_ratio < 0.8:
            return {"action": "ENTER_REDUCED", "size": 0.3, "regime": regime}
        return {"action": "REJECT", "size": 0.0, "regime": regime}

    def _classify(self, atr_pct: float, history: list) -> str:
        if len(history) < 20:
            return "normal"
        s = sorted(history)
        n = len(s)
        if atr_pct > s[int(n * 0.95)]:
            return "extreme"
        if atr_pct > s[int(n * 0.75)]:
            return "high"
        if atr_pct < s[int(n * 0.25)]:
            return "low"
        return "normal"
