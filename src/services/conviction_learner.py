"""
Conviction Calibrator v2 — Fixes: position size not calibrated → model confidence ≠ actual WR.

Isotonic calibration: 10 bins, tracks actual WR per conviction bucket.
Enables Kelly-sized position based on realistic win probability.
"""

import numpy as np
from collections import deque
import logging

logger = logging.getLogger(__name__)


class ConvictionCalibrator:
    """Learn true win rate at each confidence level."""

    N = 10  # Number of confidence buckets

    def __init__(self):
        # Track outcomes in each conviction bucket
        self._bins = [deque(maxlen=50) for _ in range(self.N)]
        # Empirical WR per bucket
        self._wr = [0.5] * self.N

    def __call__(self, o):
        """Called when outcome arrives."""
        # Place outcome in bucket based on conviction
        i = int(np.clip(o.conviction, 0, 0.999) * self.N)
        self._bins[i].append(1 if o.won else 0)
        # Update empirical WR for this bucket
        if len(self._bins[i]) >= 5:
            self._wr[i] = np.mean(self._bins[i])

    def calibrate(self, c: float) -> float:
        """Get actual win rate for conviction level c."""
        return self._wr[int(np.clip(c, 0, 0.999) * self.N)]

    def kelly_size(self, c: float, b: float = 1.5) -> float:
        """
        Kelly criterion position sizing.
        
        Kelly = (b*p - (1-p)) / b, clamped to 50% max per bet.
        p = empirical win rate at conviction c
        b = payoff ratio (1.5:1 assumed)
        """
        p = self.calibrate(c)
        kelly = (b * p - (1 - p)) / b
        return max(0, kelly * 0.5)

    def ece(self) -> float:
        """
        Expected Calibration Error: how well does confidence match reality?
        Lower is better (0 = perfect calibration).
        """
        n = sum(len(b) for b in self._bins)
        if n == 0:
            return 1.0

        error = sum(
            (len(b) / n * abs(np.mean(b) - (i + 0.5) / self.N))
            for i, b in enumerate(self._bins)
            if len(b) >= 3
        )
        return round(error, 4)

    def report(self) -> dict:
        """Detailed calibration status."""
        return {
            "bins": [
                {
                    "confidence": f"[{i/self.N:.1%}, {(i+1)/self.N:.1%})",
                    "n": len(self._bins[i]),
                    "actual_wr": f"{self._wr[i]:.1%}",
                }
                for i in range(self.N)
            ],
            "ece": self.ece(),
            "status": (
                "WELL_CALIBRATED" if self.ece() < 0.05 else "GOOD" if self.ece() < 0.10 else "POOR"
            ),
        }
