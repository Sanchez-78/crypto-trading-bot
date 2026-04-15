"""
Rejection Fix 4: Calibrated OFI Filter (self-tuning threshold)

OFI_TOXIC=24 (new filter) → self-calibrating threshold 0.30-0.70.

Adjusts if blocking profitable trades (loosen) or losers (tighten).

Current: static threshold
Better: learns optimal threshold from outcomes

Strategy:
- Track what would have happened if blocked trade had executed
- If blocked winners: loosen
- If blocked losers: tighten (filter is working)
"""

import numpy as np
from collections import deque
import logging

logger = logging.getLogger(__name__)


class CalibratedOFIFilter:
    """Self-calibrating OFI toxicity filter."""

    T0 = 0.40  # Initial threshold
    T_MIN = 0.30
    T_MAX = 0.70
    STEP = 0.03
    MIN_N = 15

    def __init__(self):
        self._t = self.T0
        self._blk: deque = deque(maxlen=100)  # Blocked trade outcomes (counterfactual)
        self._pass: deque = deque(maxlen=100)  # Passed trade outcomes

    def check(self, adj_obi: float, spoof: float) -> tuple:
        """
        Check if signal should be blocked (OFI too toxic).
        
        Returns: (should_block, reason)
        """
        # High spoof factor (order book manipulation)
        if spoof > self._t:
            return True, f"OFI_TOXIC:spoof={spoof:.2f}>{self._t:.2f}"
        
        # OFI too weak (no signal)
        if abs(adj_obi) < 0.08:
            return True, f"OFI_TOXIC:obi={adj_obi:.3f}<0.08"
        
        return False, f"OFI_OK:spoof={spoof:.2f} obi={adj_obi:.3f}"

    def record_pass(self, won: bool):
        """Record outcome of trade that passed filter."""
        self._pass.append(1 if won else 0)

    def record_block_cf(self, would_win: bool):
        """Record counterfactual: would blocked trade have won?"""
        self._blk.append(1 if would_win else 0)
        
        # Auto-calibration
        if len(self._blk) >= self.MIN_N and self._pass:
            bwr = np.mean(self._blk)  # Win rate of blocked trades
            pwr = np.mean(self._pass)  # Win rate of passed trades
            
            if bwr > pwr + 0.10:
                # Blocking too many winners → loosen
                self._t = min(self.T_MAX, self._t + self.STEP)
                logger.info(f"OFI loosened→{self._t:.2f} (blocking {bwr:.0%} winners)")
            elif bwr < pwr - 0.10:
                # Blocking mostly losers → tighten (good)
                self._t = max(self.T_MIN, self._t - self.STEP)
                logger.info(f"OFI tightened→{self._t:.2f} (blocking mostly losers)")

    def report(self) -> dict:
        """Filter performance report."""
        return {
            "threshold": self._t,
            "block_wr": f"{np.mean(self._blk):.0%}" if self._blk else "n/a",
            "pass_wr": f"{np.mean(self._pass):.0%}" if self._pass else "n/a",
        }
