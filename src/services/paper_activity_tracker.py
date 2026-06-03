"""
V10.13y: Unified PAPER Activity Timer

Single source of truth for last PAPER activity timestamps (entry, exit, learning).
Used by: watchdog, starvation bypass, learning monitor, dashboard.

Eliminates contradictory idle measurements across components.
"""

import time
import logging
from typing import Tuple

log = logging.getLogger(__name__)


class PaperActivityTracker:
    """Thread-safe tracker for last PAPER activity timestamps."""

    def __init__(self):
        self._last_entry_ts: float = time.time()
        self._last_exit_ts: float = time.time()
        self._last_learning_ts: float = time.time()

    def record_entry(self) -> None:
        """Record PAPER_ENTRY activity."""
        self._last_entry_ts = time.time()

    def record_exit(self) -> None:
        """Record PAPER_EXIT activity."""
        self._last_exit_ts = time.time()

    def record_learning(self) -> None:
        """Record LEARNING_UPDATE activity."""
        self._last_learning_ts = time.time()

    def get_idle_seconds(self, use_source: str = "any") -> Tuple[float, str]:
        """
        Get idle time in seconds since last activity.

        Args:
            use_source: "entry", "exit", "learning", or "any" (use most recent)

        Returns:
            (idle_seconds, source_used)
            - Tuple of idle time and which activity type was used as reference
            - source_used is one of: "entry", "exit", "learning"
        """
        now = time.time()

        if use_source == "entry":
            return (now - self._last_entry_ts, "entry")
        elif use_source == "exit":
            return (now - self._last_exit_ts, "exit")
        elif use_source == "learning":
            return (now - self._last_learning_ts, "learning")
        else:  # "any" — use most recent (minimum idle)
            idle_by_type = {
                "entry": now - self._last_entry_ts,
                "exit": now - self._last_exit_ts,
                "learning": now - self._last_learning_ts,
            }
            # Find activity type with minimum idle (most recent)
            most_recent_type = min(idle_by_type.items(), key=lambda x: x[1])[0]
            most_recent_idle = idle_by_type[most_recent_type]
            return (most_recent_idle, most_recent_type)

    def get_summary(self) -> dict:
        """
        Return full activity summary for logging and diagnostics.

        Returns:
            {idle_entry_s, idle_exit_s, idle_learning_s, idle_any_s}
        """
        now = time.time()
        idle_entry = now - self._last_entry_ts
        idle_exit = now - self._last_exit_ts
        idle_learning = now - self._last_learning_ts

        return {
            "idle_entry_s": idle_entry,
            "idle_exit_s": idle_exit,
            "idle_learning_s": idle_learning,
            "idle_any_s": min(idle_entry, idle_exit, idle_learning),
        }


# Global singleton instance
_tracker = PaperActivityTracker()


def record_entry() -> None:
    """Record PAPER_ENTRY to global tracker."""
    _tracker.record_entry()


def record_exit() -> None:
    """Record PAPER_EXIT to global tracker."""
    _tracker.record_exit()


def record_learning() -> None:
    """Record LEARNING_UPDATE to global tracker."""
    _tracker.record_learning()


def get_idle_seconds(source: str = "any") -> Tuple[float, str]:
    """
    Get idle seconds from global tracker.

    Args:
        source: "entry", "exit", "learning", or "any"

    Returns:
        (idle_seconds, source_used)
    """
    return _tracker.get_idle_seconds(source)


def get_summary() -> dict:
    """Get full activity summary from global tracker."""
    return _tracker.get_summary()
