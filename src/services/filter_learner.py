"""
Filter Learner v2 — Fixes: TIMING static at 514 → filters never calibrate from outcomes.

Tracks pass_wr and block_counterfactual per filter.
Auto-adjusts thresholds by ±3% based on actual performance.
"""

import numpy as np
from collections import defaultdict, deque
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class FilterLearner:
    """Learn which filters are too strict/loose by tracking outcomes."""

    STEP = 0.03  # Threshold adjustment size
    MIN_N = 20  # Need 20 samples before adjusting
    PROTECT_T = 0.55  # Protection threshold for blocked trades

    def __init__(self):
        # Track win rate for trades that passed filter
        self._pass: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        # Track counterfactual: would blocked trades have won?
        self._block: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        # Threshold adjustments per filter
        self._adj: Dict[str, float] = defaultdict(float)

    def __call__(self, o):
        """Called when outcome arrives."""
        val = 1 if o.won else 0
        # Record outcome for filters that passed
        for f in o.filters_passed:
            self._pass[f].append(val)
        self._adjust()

    def record_block(self, fname: str, would_win: bool):
        """Track counterfactual: what if this filter had passed?"""
        self._block[fname].append(1 if would_win else 0)

    def _adjust(self):
        """Recalibrate filter thresholds based on outcome patterns."""
        for f, d in self._pass.items():
            if len(d) < self.MIN_N:
                continue
            wr = np.mean(d)
            if wr < 0.45:
                # Filter is passing too many losers → tighten
                self._adj[f] = max(-0.25, self._adj[f] - self.STEP)
                logger.info(f"Filter {f} TIGHTENED to {self._adj[f]:+.2f} (WR={wr:.0%})")
            elif wr > 0.62:
                # Filter is passing mostly winners → loosen
                self._adj[f] = min(0.25, self._adj[f] + self.STEP)
                logger.info(f"Filter {f} LOOSENED to {self._adj[f]:+.2f} (WR={wr:.0%})")

    def adjustment(self, f: str) -> float:
        """Get current threshold adjustment for filter f."""
        return self._adj.get(f, 0.0)

    def effective(self, f: str) -> bool:
        """Is this filter protecting against losses?"""
        d = self._block[f]
        if len(d) < self.MIN_N:
            return True
        protection = np.mean(d)
        return protection < self.PROTECT_T

    def report(self) -> dict:
        """Detailed status of all filters."""
        out = {}
        for f in set(list(self._pass) + list(self._block)):
            pd_ = self._pass.get(f, [])
            bd_ = self._block.get(f, [])
            out[f] = {
                "pass_wr": f"{np.mean(pd_):.0%}" if len(pd_) >= 5 else "n/a",
                "block_protect": f"{1-np.mean(bd_):.0%}" if len(bd_) >= 5 else "n/a",
                "adj": f"{self.adjustment(f):+.2f}",
            }
        return out
