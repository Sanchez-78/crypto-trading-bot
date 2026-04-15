"""
State History Manager v1 — Snapshot + rollback capability.

Keeps bounded circular buffer of state snapshots.
Enables rolling back to previous state if recovery needed.

Key: deepcopy ensures snapshots are independent.
"""

import copy
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class StateHistory:
    """
    Maintains bounded history of state snapshots.
    Enables rollback to recover from bad states.
    """

    def __init__(self, max_size: int = 100):
        """
        Initialize state history.
        
        Args:
            max_size: Max snapshots to keep (circular buffer)
        """
        self.history = []
        self.max_size = max_size
        self.timestamps = []

    def save(self, state):
        """
        Save current state snapshot.
        Automatically prunes oldest if buffer full.
        """
        # Deep copy to break references
        snapshot = copy.deepcopy(state)
        
        self.history.append(snapshot)
        self.timestamps.append(datetime.now())

        # Keep buffer bounded
        if len(self.history) > self.max_size:
            self.history.pop(0)
            self.timestamps.pop(0)

        logger.debug(f"StateHistory: saved snapshot #{len(self.history)}")

    def rollback(self, steps: int = 5):
        """
        Rollback to previous state.
        
        Args:
            steps: How many snapshots back (default 5)
        
        Returns:
            Restored state (or most recent if insufficient history)
        """
        if len(self.history) == 0:
            logger.warning("StateHistory: no snapshots available, returning None")
            return None

        if len(self.history) < steps:
            logger.warning(
                f"StateHistory: only {len(self.history)} snapshots, "
                f"rolling back to oldest"
            )
            steps = len(self.history) - 1

        if steps <= 0:
            steps = 1

        back_idx = -steps
        restored = copy.deepcopy(self.history[back_idx])
        restored_ts = self.timestamps[back_idx]

        logger.warning(
            f"🔄 ROLLBACK: restored state from {steps} steps ago "
            f"(timestamp: {restored_ts.isoformat()})"
        )

        return restored

    def rollback_if_needed(self, state, anomalies: list):
        """
        Auto-rollback if critical anomaly detected.
        
        Critical anomalies (trigger rollback):
        - EQUITY_DROP
        - HIGH_DRAWDOWN
        
        Returns:
            Either rolled-back state or current state
        """
        critical = {"EQUITY_DROP", "HIGH_DRAWDOWN"}
        
        if any(a in critical for a in anomalies):
            logger.error(f"StateHistory: critical anomaly detected: {anomalies}")
            rolled_back = self.rollback(steps=5)
            if rolled_back:
                return rolled_back

        return state

    def get_last_n(self, n: int = 5) -> list:
        """Get last n snapshots (for analysis/diagnostics)."""
        return copy.deepcopy(self.history[-n:])

    def status(self) -> dict:
        """Current history status."""
        return {
            "snapshots": len(self.history),
            "max_size": self.max_size,
            "oldest_ts": self.timestamps[0].isoformat() if self.timestamps else "none",
            "newest_ts": self.timestamps[-1].isoformat() if self.timestamps else "none",
        }
