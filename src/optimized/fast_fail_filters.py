from __future__ import annotations
import numpy as np
from collections import deque


class AdaptiveVolumeFilter:
    """Time-of-day RVOL gate.

    Sources: Springer2024 38-exchange study — peak 16-17 UTC, trough 3-4 UTC, 42% swing.
    """

    def __init__(self, min_rvol: float = 1.2, max_rvol: float = 5.0):
        self.min_rvol = min_rvol
        self.max_rvol = max_rvol
        self.tod: dict[int, deque] = {h: deque(maxlen=100) for h in range(24)}

    def check(self, volume: float, hour: int) -> tuple[bool, str]:
        hist = self.tod[hour]
        if len(hist) < 5:
            self.tod[hour].append(volume)
            return True, "insufficient_history"
        rvol = volume / np.mean(hist)
        self.tod[hour].append(volume)
        if rvol < self.min_rvol:
            return False, f"FF:LOW_RVOL {rvol:.2f}x"
        if rvol > self.max_rvol:
            return False, f"FF:EXTREME_RVOL {rvol:.2f}x"
        return True, f"RVOL {rvol:.2f}x"


class AdaptiveSpreadFilter:
    """Z-score spread gate.

    Sources: Kaiko — BTC ~1 bps, mid-cap alts 3-8 bps, small-caps 8-20+ bps.
    """

    def __init__(self, z_threshold: float = 2.5):
        self.z_threshold = z_threshold
        self.history: deque = deque(maxlen=100)

    def check(self, bid: float, ask: float) -> tuple[bool, str]:
        mid = (bid + ask) / 2
        spread_bps = (ask - bid) / mid * 10000 if mid > 0 else 0
        self.history.append(spread_bps)
        if len(self.history) < 10:
            return True, "insufficient_history"
        std = np.std(self.history)
        z = (spread_bps - np.mean(self.history)) / std if std > 0 else 0
        if z > self.z_threshold:
            return False, f"FF:HIGH_SPREAD z={z:.2f}"
        return True, f"spread {spread_bps:.1f}bps z={z:.2f}"


class MovementFilter:
    """Candle range exhaustion gate — reject if range > 0.8× ATR."""

    def check(
        self, candle_high: float, candle_low: float, atr: float
    ) -> tuple[bool, str]:
        if atr <= 0:
            return True, ""
        ratio = (candle_high - candle_low) / atr
        if ratio > 0.8:
            return False, f"FF:EXHAUSTED range={ratio:.2f}xATR"
        return True, f"range {ratio:.2f}xATR"
