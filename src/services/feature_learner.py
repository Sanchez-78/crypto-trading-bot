"""
Feature Learner v2 — Fixes: all features 27%WR → outcomes not updating feature weights.

Core logic:
- Drop threshold 42%, boost threshold 58%, min 30 samples before action
- Tracks win rate per feature
- Features that correlate with losses get dropped
- Features that predict wins get upweighted
"""

import numpy as np
from collections import defaultdict, deque
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class FeatureLearner:
    """Learn which signal features are predictive of wins vs losses."""

    DROP_T = 0.42  # If WR < 42%, drop feature (not predictive)
    BOOST_T = 0.58  # If WR > 58%, boost weight
    MIN_N = 30  # Need at least 30 samples before making decisions
    W_BOUNDS = (0.3, 2.0)  # Weight range

    def __init__(self):
        # Track outcomes per feature
        self._d: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        # Feature weights (multipliers)
        self._w: Dict[str, float] = {}
        # Features that failed consistently
        self._dropped: set = set()

    def __call__(self, o):
        """Called when outcome arrives. Learner is callable."""
        # Evaluate each signal feature against actual result
        for k, v in o.features.items():
            if k in self._dropped or abs(v) < 0.05:
                continue

            # Check if feature value aligned with winning direction
            is_long = o.direction == "LONG"
            bull_signal = v > 0  # Bullish feature
            correct = (
                (bull_signal and is_long and o.won)
                or (not bull_signal and not is_long and o.won)
                or (bull_signal and not is_long and not o.won)
                or (not bull_signal and is_long and not o.won)
            )

            self._d[k].append(1 if correct else 0)
            self._update(k)

    def _update(self, k: str):
        """Recalculate weight for feature k."""
        d = self._d[k]
        if len(d) < self.MIN_N:
            return

        wr = np.mean(d)

        if wr < self.DROP_T:
            # Feature is not predictive → drop
            self._dropped.add(k)
            self._w[k] = 0.0
            logger.info(f"Feature {k} DROPPED (WR={wr:.0%})")
        elif wr > self.BOOST_T:
            # Feature is highly predictive → boost weight
            boost = 1.0 + (wr - 0.55) * 4
            self._w[k] = min(self.W_BOUNDS[1], boost)
            logger.info(f"Feature {k} BOOSTED to {self._w[k]:.2f} (WR={wr:.0%})")
        else:
            # Feature is marginal → moderate adjustment
            self._w[k] = np.clip(1.0 + (wr - 0.50) * 2, *self.W_BOUNDS)

    def weight(self, k: str) -> float:
        """Get current weight multiplier for feature k."""
        if k in self._dropped:
            return 0.0
        return self._w.get(k, 1.0)

    def active(self) -> list:
        """List of features currently being tracked (not dropped)."""
        return [k for k in self._d if k not in self._dropped and len(self._d[k]) >= 5]

    def report(self) -> dict:
        """Detailed status of all features."""
        return {
            k: {
                "wr": f"{np.mean(d):.0%}",
                "w": round(self.weight(k), 2),
                "n": len(d),
                "status": (
                    "DROPPED"
                    if k in self._dropped
                    else "BOOST"
                    if self.weight(k) > 1.2
                    else "WEAK"
                    if np.mean(d) < 0.50
                    else "OK"
                ),
            }
            for k, d in self._d.items()
            if len(d) >= 5
        }
