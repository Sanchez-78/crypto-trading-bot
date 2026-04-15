"""
Rejection Fix 3: Adaptive Score Gate (no circular deadlock)

SKIP_SCORE=73 → circular deadlock: low score blocks trades → no trades → low score

Current: binary gate, blocks all signals below threshold
Problem: creates deadlocked state
Better: rate-limited gate (max 20% of signals blocked), graduated thresholds

Thresholds:
  <50 trades:    disabled (bootstrap)
  50-150 trades: threshold starts at 10
  150+ trades:   threshold 40+
  
Rate limit: never block >20% of signals in window
"""

import numpy as np
from collections import deque
import logging

logger = logging.getLogger(__name__)


class AdaptiveScoreGate:
    """Smart score-based signal gating with rate limiting."""

    MIN_TRADES = 50  # Don't gate until we have baseline
    MAX_SKIP = 0.20  # Never block >20% of signals
    T_PROD = 40.0  # Production threshold
    T_BOOT = 10.0  # Bootstrap threshold
    WIN = 50  # Window size for rate limiting

    def __init__(self):
        self._dec: deque = deque(maxlen=self.WIN)
        self._hist: deque = deque(maxlen=20)

    def check(self, score: float, n: int) -> tuple:
        """
        Check if signal should be gated.
        
        Returns: (should_skip, reason)
        """
        # Bootstrap: never gate
        if n < self.MIN_TRADES:
            self._dec.append(False)
            return False, f"GATE_OFF:boot({n}<{self.MIN_TRADES})"

        # Rate limiting: don't gate if already blocking >20% of signals
        if len(self._dec) >= 10:
            current_skip_rate = sum(self._dec) / len(self._dec)
            if current_skip_rate >= self.MAX_SKIP:
                self._dec.append(False)
                return False, f"GATE_RATELIMIT:skip_rate>={self.MAX_SKIP:.0%}"

        # Determine threshold
        t = self._threshold(n)
        
        if score < t:
            self._dec.append(True)
            return True, f"SKIP_SCORE:{score:.1f}<{t:.1f}"
        
        self._dec.append(False)
        return False, f"SCORE_OK:{score:.1f}"

    def _threshold(self, n: int) -> float:
        """Calibrate threshold based on progress."""
        # Linear interpolation from bootstrap to production
        p = min(1.0, (n - self.MIN_TRADES) / 100)
        t = self.T_BOOT + (self.T_PROD - self.T_BOOT) * p
        
        # Trend adjustment: if score improving, tighten threshold
        if len(self._hist) >= 5:
            trend = np.polyfit(range(len(self._hist)), list(self._hist), 1)[0]
            if trend > 0.5:  # Strong uptrend
                t *= 0.85
        
        return t

    def record_score(self, s: float):
        """Record score for trend analysis."""
        self._hist.append(s)

    def status(self) -> dict:
        """Current gating status."""
        r = sum(self._dec) / len(self._dec) if self._dec else 0
        return {
            "skip_rate": f"{r:.0%}",
            "rate_limited": r >= self.MAX_SKIP,
        }
