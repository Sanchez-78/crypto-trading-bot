"""
V5 Legacy Bridge — Integration of V5 infrastructure into legacy runtime

Converts legacy bot trading events into V5-compatible persistence, learning, and metrics.
Single service only: cryptomaster.service
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from .event_models import LegacyPaperOpenEvent, LegacyPaperCloseEvent, V5QuotaSnapshot, V5DashboardSnapshot

logger = logging.getLogger(__name__)


class V5LegacyBridge:
    """
    Main bridge class for integrating V5 functions into legacy runtime.

    Lifecycle:
    1. Legacy bot calls record_open(event) on PAPER entry
    2. Quota guard approves/rejects new positions
    3. Firebase writer persists with idempotency (trade_id key)
    4. On PAPER exit: record_close(event)
    5. Learning bridge updates and publishes metrics
    6. Outbox retries on Firebase failure
    """

    def __init__(self):
        self.quota_guard = None  # Will be initialized
        self.outbox = None
        self.firebase_writer = None
        self.learning_bridge = None
        self.metrics_publisher = None

        # State tracking
        self._open_events: Dict[str, LegacyPaperOpenEvent] = {}
        self._close_events: Dict[str, LegacyPaperCloseEvent] = {}
        self._quota_snapshot = V5QuotaSnapshot()

        logger.info("[V5_BRIDGE] Initialized (components pending)")

    def initialize(self):
        """Initialize all bridge components."""
        try:
            # Import components
            from .quota import QuotaGuard
            from .outbox import DurableOutbox
            from .firebase_writer import FirebaseWriter
            from .learning_bridge import LearningBridge
            from .metrics_publisher import MetricsPublisher

            self.quota_guard = QuotaGuard()
            self.outbox = DurableOutbox()
            self.firebase_writer = FirebaseWriter()
            self.learning_bridge = LearningBridge()
            self.metrics_publisher = MetricsPublisher()

            logger.info("[V5_BRIDGE] All components initialized successfully")
            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE] Initialization failed: {e}")
            return False

    def can_open_new_position(self) -> bool:
        """Check if quota allows new position opening."""
        if not self.quota_guard:
            return True  # Fallback if not initialized

        # Reserve for closes, lifecycle, emergency
        reserve = 500
        can_open = self.quota_guard.writes_remaining() > reserve

        if not can_open:
            logger.warning(
                f"[V5_BRIDGE_QUOTA_STATE] Cannot open: writes_remaining="
                f"{self.quota_guard.writes_remaining()}, reserve={reserve}"
            )

        return can_open

    def record_open(self, event: LegacyPaperOpenEvent) -> bool:
        """
        Record PAPER entry from legacy bot.

        Called when legacy bot enters a position.

        Args:
            event: LegacyPaperOpenEvent with trade details

        Returns:
            True if saved to outbox/Firebase, False otherwise
        """
        try:
            trade_id = event.trade_id

            # Track locally
            self._open_events[trade_id] = event

            # Save via outbox (will retry if Firebase fails)
            if self.outbox:
                self.outbox.enqueue_open(event)

            logger.info(
                f"[V5_BRIDGE_OPEN_SAVED] trade_id={trade_id} symbol={event.symbol} "
                f"side={event.side} price={event.entry_price}"
            )

            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE] record_open failed: {e}")
            return False

    def record_close(self, event: LegacyPaperCloseEvent) -> bool:
        """
        Record PAPER exit from legacy bot.

        Called when legacy bot closes a position.

        Args:
            event: LegacyPaperCloseEvent with close details

        Returns:
            True if saved to outbox/Firebase, False otherwise
        """
        try:
            trade_id = event.trade_id

            # Track locally
            self._close_events[trade_id] = event

            # Save via outbox
            if self.outbox:
                self.outbox.enqueue_close(event)

            logger.info(
                f"[V5_BRIDGE_CLOSE_SAVED] trade_id={trade_id} pnl={event.net_pnl:+.8f} "
                f"reason={event.exit_reason} eligible={event.learning_eligible}"
            )

            # Apply learning if eligible
            if event.learning_eligible and self.learning_bridge:
                self.learning_bridge.record_close(event)

            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE] record_close failed: {e}")
            return False

    def publish_metrics(self) -> bool:
        """
        Publish dashboard, readiness, and quota metrics.

        Called periodically (e.g., every 30 seconds from legacy loop).

        Returns:
            True if published, False if failed
        """
        try:
            if not self.metrics_publisher:
                return False

            snapshot = V5DashboardSnapshot(
                open_positions=len(self._open_events),
                closed_today=len(self._close_events),
            )

            self.metrics_publisher.publish(snapshot)

            logger.info(
                f"[V5_BRIDGE_DASHBOARD_PUBLISH] open_positions={snapshot.open_positions} "
                f"closed_today={snapshot.closed_today}"
            )

            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE] publish_metrics failed: {e}")
            return False

    def get_quota_status(self) -> Dict[str, Any]:
        """Get current quota state."""
        if not self.quota_guard:
            return {"state": "uninitialized"}

        return {
            "reads_used": self.quota_guard.reads_used(),
            "reads_remaining": self.quota_guard.reads_remaining(),
            "writes_used": self.quota_guard.writes_used(),
            "writes_remaining": self.quota_guard.writes_remaining(),
            "outbox_pending": self.outbox.pending_count() if self.outbox else 0,
            "state": self.quota_guard.get_state(),
        }

    def flush_outbox(self, max_retries: int = 3) -> Dict[str, Any]:
        """Manually flush pending outbox entries."""
        if not self.outbox:
            return {"status": "no_outbox"}

        return self.outbox.flush(max_retries=max_retries)


# Global instance
_v5_bridge: Optional[V5LegacyBridge] = None


def get_v5_bridge() -> V5LegacyBridge:
    """Get or create the global V5 legacy bridge instance."""
    global _v5_bridge
    if _v5_bridge is None:
        _v5_bridge = V5LegacyBridge()
    return _v5_bridge


def initialize_v5_bridge() -> bool:
    """Initialize the V5 legacy bridge."""
    bridge = get_v5_bridge()
    return bridge.initialize()
