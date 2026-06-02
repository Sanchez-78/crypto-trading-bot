"""Phase 4C: Live PAPER Training Metrics

Collects real-time metrics from PAPER trading, learning, and starvation bypass systems.
Provides data for dashboard and diagnostic logging.
"""

import logging
import time
from typing import Dict, Any, Optional
from collections import deque

log = logging.getLogger(__name__)


class PaperTrainingMetrics:
    """Collects live PAPER training metrics from all subsystems."""

    def __init__(self):
        """Initialize metrics collector."""
        self._paper_entries_1h = deque(maxlen=3600)  # 1-second resolution, 1-hour window
        self._paper_exits_1h = deque(maxlen=3600)
        self._learning_updates_1h = deque(maxlen=3600)
        self._starvation_accepted_1h = deque(maxlen=3600)
        self._starvation_rejected_1h = deque(maxlen=3600)
        self._last_paper_entry_ts = None
        self._last_paper_exit_ts = None
        self._last_learning_update_ts = None
        self._lock = __import__('threading').RLock()

    def record_paper_entry(self, symbol: str, side: str, source: str = "unknown") -> None:
        """Record PAPER entry event."""
        with self._lock:
            ts = time.time()
            self._paper_entries_1h.append(ts)
            self._last_paper_entry_ts = ts
            log.debug(f"[PAPER_METRICS] entry recorded: {symbol} {side} source={source}")

    def record_paper_exit(self, symbol: str, side: str, outcome: str = "UNKNOWN") -> None:
        """Record PAPER exit event."""
        with self._lock:
            ts = time.time()
            self._paper_exits_1h.append(ts)
            self._last_paper_exit_ts = ts
            log.debug(f"[PAPER_METRICS] exit recorded: {symbol} {side} outcome={outcome}")

    def record_learning_update(self, symbol: str, trade_id: str = "") -> None:
        """Record learning update event."""
        with self._lock:
            ts = time.time()
            self._learning_updates_1h.append(ts)
            self._last_learning_update_ts = ts
            log.debug(f"[PAPER_METRICS] learning_update recorded: {symbol} {trade_id}")

    def record_starvation_bypass_accepted(self, symbol: str, bucket: str = "") -> None:
        """Record starvation bypass acceptance."""
        with self._lock:
            ts = time.time()
            self._starvation_accepted_1h.append(ts)
            log.debug(f"[PAPER_METRICS] starvation_bypass_accepted: {symbol} {bucket}")

    def record_starvation_bypass_rejected(self, symbol: str, reason: str = "") -> None:
        """Record starvation bypass rejection."""
        with self._lock:
            ts = time.time()
            self._starvation_rejected_1h.append(ts)
            log.debug(f"[PAPER_METRICS] starvation_bypass_rejected: {symbol} reason={reason}")

    def get_metrics(self, open_positions_count: int = 0,
                   v5_outbox_pending_open: int = 0,
                   v5_outbox_pending_close: int = 0,
                   v5_outbox_pending_learning: int = 0) -> Dict[str, Any]:
        """Get current metrics snapshot.

        Args:
            open_positions_count: Current number of open PAPER positions
            v5_outbox_pending_open: Pending paper_open events in V5 outbox
            v5_outbox_pending_close: Pending paper_close events in V5 outbox
            v5_outbox_pending_learning: Pending learning_update events in V5 outbox

        Returns:
            Dictionary with current metrics
        """
        with self._lock:
            now = time.time()
            cutoff = now - 3600  # 1 hour ago

            # Count events in 1-hour window
            entries_1h = sum(1 for ts in self._paper_entries_1h if ts > cutoff)
            exits_1h = sum(1 for ts in self._paper_exits_1h if ts > cutoff)
            learning_1h = sum(1 for ts in self._learning_updates_1h if ts > cutoff)
            accepted_1h = sum(1 for ts in self._starvation_accepted_1h if ts > cutoff)
            rejected_1h = sum(1 for ts in self._starvation_rejected_1h if ts > cutoff)

            # Age of last events (seconds)
            last_entry_age = (now - self._last_paper_entry_ts) if self._last_paper_entry_ts else None
            last_exit_age = (now - self._last_paper_exit_ts) if self._last_paper_exit_ts else None
            last_learning_age = (now - self._last_learning_update_ts) if self._last_learning_update_ts else None

            return {
                "open_positions": open_positions_count,
                "paper_entries_1h": entries_1h,
                "paper_exits_1h": exits_1h,
                "paper_learning_updates_1h": learning_1h,
                "starvation_bypass_accepted_1h": accepted_1h,
                "starvation_bypass_rejected_1h": rejected_1h,
                "last_paper_entry_age_s": last_entry_age,
                "last_paper_exit_age_s": last_exit_age,
                "last_learning_update_age_s": last_learning_age,
                "v5_outbox_pending_open": v5_outbox_pending_open,
                "v5_outbox_pending_close": v5_outbox_pending_close,
                "v5_outbox_pending_learning": v5_outbox_pending_learning,
            }


# Global instance
_metrics = None


def get_paper_metrics() -> PaperTrainingMetrics:
    """Get global metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = PaperTrainingMetrics()
    return _metrics


def record_paper_entry(symbol: str, side: str, source: str = "unknown") -> None:
    """Record PAPER entry event."""
    get_paper_metrics().record_paper_entry(symbol, side, source)


def record_paper_exit(symbol: str, side: str, outcome: str = "UNKNOWN") -> None:
    """Record PAPER exit event."""
    get_paper_metrics().record_paper_exit(symbol, side, outcome)


def record_learning_update(symbol: str, trade_id: str = "") -> None:
    """Record learning update event."""
    get_paper_metrics().record_learning_update(symbol, trade_id)


def record_starvation_bypass_accepted(symbol: str, bucket: str = "") -> None:
    """Record starvation bypass acceptance."""
    get_paper_metrics().record_starvation_bypass_accepted(symbol, bucket)


def record_starvation_bypass_rejected(symbol: str, reason: str = "") -> None:
    """Record starvation bypass rejection."""
    get_paper_metrics().record_starvation_bypass_rejected(symbol, reason)
