"""
V5 Legacy Bridge — Integration of V5 infrastructure into legacy runtime

Converts legacy bot trading events into V5-compatible persistence, learning, and metrics.
Single service only: cryptomaster.service
"""

import logging
from typing import Optional, Dict, Any

from .event_models import LegacyPaperOpenEvent, LegacyPaperCloseEvent
from .quota import V5LegacyQuotaGuard
from .outbox import DurableOutbox
from .firebase_writer import V5LegacyFirebaseWriter
from .learning_bridge import V5LearningBridge
from .metrics_publisher import V5MetricsPublisher
from .outbox_flush_worker import OutboxFlushWorker
from . import config

logger = logging.getLogger(__name__)


class V5LegacyBridge:
    """
    Main bridge class for integrating V5 functions into legacy runtime.

    Lifecycle:
    1. Legacy bot checks can_open_new_position() before entry
    2. Legacy bot calls record_open(event) on PAPER entry → Firebase + outbox
    3. Firebase writer persists with idempotency (trade_id key)
    4. On PAPER exit: record_close(event) → Firebase + learning + metrics
    5. Learning bridge updates normalized learning snapshot
    6. Metrics publisher publishes dashboard/readiness/quota
    7. Outbox retries on Firebase failure (never loses closed trades)
    """

    def __init__(self, firebase_client=None):
        """
        Initialize bridge with all components.

        Args:
            firebase_client: Existing legacy Firebase client (or None if disabled)
        """
        try:
            # NEW: Wrap raw Firestore client if needed (API compatibility)
            if firebase_client and not hasattr(firebase_client, 'set'):
                from .firebase_client_wrapper import FirestorePathClient
                firebase_client = FirestorePathClient(firebase_client)
                logger.info("[V5_BRIDGE_FIREBASE_WRAPPED] Using path-based adapter for Firestore client")

            self.quota_guard = V5LegacyQuotaGuard()
            self.outbox = DurableOutbox()
            self.firebase_writer = V5LegacyFirebaseWriter(firebase_client, self.quota_guard, self.outbox)
            self.learning_bridge = V5LearningBridge()
            self.metrics_publisher = V5MetricsPublisher(self.quota_guard, self.outbox)

            # Phase 4D: Start outbox flush worker
            self.flush_worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
            self.flush_worker.start()

            logger.info(
                f"[V5_BRIDGE_INIT] enabled=true "
                f"real_orders_allowed={config.REAL_ORDERS_ALLOWED} "
                f"firebase_client={'connected' if firebase_client else 'unavailable'} "
                f"flush_worker={'started' if self.flush_worker else 'failed'} "
                f"service=cryptomaster.service"
            )
        except Exception as e:
            logger.error(f"[V5_BRIDGE] Initialization failed: {e}")
            self.quota_guard = None
            self.outbox = None
            self.firebase_writer = None
            self.learning_bridge = None
            self.metrics_publisher = None
            self.flush_worker = None

    def can_open_new_position(self, open_global: int = 0, open_for_symbol: int = 0) -> bool:
        """
        Check if quota allows new position opening.

        Args:
            open_global: Current global open positions
            open_for_symbol: Current open positions for this symbol

        Returns:
            True if new entry allowed, False if blocked by quota
        """
        try:
            if not self.quota_guard:
                return True  # Fallback: allow if bridge unavailable

            decision = self.quota_guard.check_entry_allowed(open_global, open_for_symbol, estimated_lifecycle_writes=5)
            return decision.allowed
        except Exception as e:
            logger.error(f"[V5_BRIDGE] can_open_new_position check failed: {e}")
            return True  # Safe default: allow if check fails

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
            if not self.firebase_writer:
                logger.warning(f"[V5_BRIDGE] firebase_writer unavailable, skipping record_open")
                return False

            return self.firebase_writer.write_open(event)
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
            if not self.firebase_writer:
                logger.warning(f"[V5_BRIDGE] firebase_writer unavailable, skipping record_close")
                return False

            # Always write close (critical for learning and metrics)
            result = self.firebase_writer.write_close(event)

            # Apply learning if eligible
            if event.learning_eligible and self.learning_bridge:
                try:
                    learning_update = self.learning_bridge.apply_learning_from_close(event)
                    if learning_update and "error" not in learning_update:
                        self.firebase_writer.write_learning_update(event.trade_id, learning_update)
                except Exception as e:
                    logger.error(f"[V5_BRIDGE] Learning update failed: {e}")

            return result
        except Exception as e:
            logger.error(f"[V5_BRIDGE] record_close failed: {e}")
            return False

    def publish_metrics(
        self,
        runtime_state: dict = None,
        trading_stats: dict = None,
        learning_stats: dict = None,
        paper_metrics: dict = None,
    ) -> bool:
        """
        Publish dashboard, readiness, and quota metrics.

        Called periodically (e.g., every 30 seconds from legacy loop).

        Args:
            runtime_state: Service/mode info
            trading_stats: Entry/exit counts and stats
            learning_stats: Learning eligibility and readiness
            paper_metrics: Live PAPER training metrics (1-hour rolling windows)

        Returns:
            True if published, False if failed
        """
        try:
            if not self.metrics_publisher or not self.firebase_writer:
                return False

            # Build metrics
            quota_snapshot = self.quota_guard.snapshot() if self.quota_guard else {}
            payload = self.metrics_publisher.prepare_publish_payload(
                runtime_state=runtime_state,
                quota_snapshot=quota_snapshot,
                trading_stats=trading_stats,
                learning_stats=learning_stats,
                paper_metrics=paper_metrics,
            )

            # Publish dashboard
            if "dashboard" in payload:
                self.firebase_writer.write_dashboard(payload["dashboard"])

            # Publish readiness
            if "readiness" in payload:
                self.firebase_writer.write_readiness(payload["readiness"])

            # Publish quota
            if "quota" in payload:
                self.firebase_writer.write_quota(payload["quota"])

            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE] publish_metrics failed: {e}")
            return False

    def get_quota_status(self) -> Dict[str, Any]:
        """Get current quota state."""
        try:
            if not self.quota_guard:
                return {"state": "uninitialized"}

            snapshot = self.quota_guard.snapshot()
            if self.outbox:
                snapshot["outbox_pending"] = self.outbox.pending_count()

            return snapshot
        except Exception as e:
            logger.error(f"[V5_BRIDGE] get_quota_status failed: {e}")
            return {"state": "error", "error": str(e)}

    def flush_outbox(self, limit: int = 20) -> Dict[str, Any]:
        """
        Manually flush pending outbox entries to Firebase.

        Args:
            limit: Max entries to attempt

        Returns:
            Status dict with counts
        """
        try:
            if not self.firebase_writer:
                return {"status": "firebase_writer_unavailable"}

            return self.firebase_writer.flush_outbox(limit)
        except Exception as e:
            logger.error(f"[V5_BRIDGE] flush_outbox failed: {e}")
            return {"status": "error", "error": str(e)}


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
