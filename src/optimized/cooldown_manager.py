from __future__ import annotations
import numpy as np
from datetime import datetime, timedelta
from src.optimized.bot_types import CloseReason


def detect_regime(df) -> str:
    """ADX + ATR ratio + Choppiness Index → TRENDING / RANGING / VOLATILE.

    Choppiness > 61.8 = ranging, < 38.2 = trending.
    Sources: Corbet & Katsiampa (2020) BTC asymmetric mean reversion.
    """
    try:
        import ta
        adx = ta.trend.adx(df["high"], df["low"], df["close"], 14).iloc[-1]
        atr_f = ta.volatility.average_true_range(df["high"], df["low"], df["close"], 5)
        atr_s = ta.volatility.average_true_range(df["high"], df["low"], df["close"], 20)
        atr_ratio = (atr_f / atr_s).iloc[-1]
        h14 = df["high"].rolling(14).max()
        l14 = df["low"].rolling(14).min()
        atr1 = ta.volatility.average_true_range(df["high"], df["low"], df["close"], 1)
        chop = (
            100 * np.log10(atr1.rolling(14).sum() / (h14 - l14)) / np.log10(14)
        ).iloc[-1]
        sc = {"TRENDING": 0, "RANGING": 0, "VOLATILE": 0}
        if adx > 25:
            sc["TRENDING"] += 2
        if atr_ratio > 1.5:
            sc["VOLATILE"] += 2
        if chop > 61.8:
            sc["RANGING"] += 2
        return max(sc, key=sc.get)
    except Exception:
        return "RANGING"


class RegimeAdaptiveCooldown:
    """Per-symbol cooldown with regime-specific matrices.

    Cooldown matrix columns [big_win>2%, small_win, small_loss, big_loss, stoploss]
    in candles:
      TRENDING : [1,  2,  2,  3,  4]
      RANGING  : [4,  6,  8, 12, 16]
      VOLATILE : [3,  4,  5,  8, 10]

    Serial loss ≥ 3 consecutive → multiply 1.5×.
    """

    MATRIX = {
        "TRENDING": [1, 2, 2, 3, 4],
        "RANGING":  [4, 6, 8, 12, 16],
        "VOLATILE": [3, 4, 5, 8, 10],
    }

    def __init__(self, candle_seconds: int = 3600):
        self.candle_seconds = candle_seconds
        self._locks: dict[str, datetime] = {}
        self._consec: dict[str, int] = {}

    def lock(
        self,
        symbol: str,
        regime: str,
        pnl_pct: float,
        close_reason: CloseReason,
    ) -> None:
        m = self.MATRIX.get(regime, self.MATRIX["RANGING"])
        if close_reason == CloseReason.SL:
            c = m[4]
        elif pnl_pct > 2.0:
            c = m[0]
        elif pnl_pct > 0:
            c = m[1]
        elif pnl_pct > -1.0:
            c = m[2]
        else:
            c = m[3]

        if close_reason in (CloseReason.SL, CloseReason.TIMEOUT) and pnl_pct < 0:
            self._consec[symbol] = self._consec.get(symbol, 0) + 1
        else:
            self._consec[symbol] = 0

        if self._consec.get(symbol, 0) >= 3:
            c = int(c * 1.5)

        self._locks[symbol] = datetime.now() + timedelta(
            seconds=c * self.candle_seconds
        )

    def is_locked(self, symbol: str) -> tuple[bool, str]:
        if symbol not in self._locks:
            return False, ""
        rem = (self._locks[symbol] - datetime.now()).total_seconds()
        if rem <= 0:
            del self._locks[symbol]
            return False, ""
        return True, f"PAIR_BLOCK:{symbol} {rem:.0f}s"

    def force_unlock(self, symbol: str) -> None:
        self._locks.pop(symbol, None)
