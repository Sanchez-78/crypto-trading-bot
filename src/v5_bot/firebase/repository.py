"""QuotaAwareFirestoreRepository — V5 Firebase persistence with hard quota enforcement.

All V5 Firebase operations go through this repository.
Quota guard is applied pre-flight. Failures go to outbox.
"""

from typing import Optional, Dict, Any, List
import logging
import firebase_admin
from firebase_admin import firestore, credentials
from google.cloud.firestore import Client, WriteBatch

from src.v5_bot.firebase.schema import (
    V5Control, V5Epoch, V5OpenPositions, V5Trade, V5LearningState,
    V5DailyMetrics, V5Readiness, V5Quota, V5Dashboard, V5MetricsRegistry,
    to_firestore_dict, from_firestore_dict, QuotaState
)
from src.v5_bot.firebase.quota_guard import QuotaGuard
from src.v5_bot.firebase.outbox import TradeOutbox

logger = logging.getLogger(__name__)


class QuotaAwareFirestoreRepository:
    """Firebase repository with hard quota enforcement."""

    def __init__(self, credentials_path: Optional[str] = None):
        """
        Initialize Firebase repository.

        Args:
            credentials_path: path to Firebase credentials JSON (default from env)
        """
        self.quota_guard = QuotaGuard()
        self.outbox = TradeOutbox()

        # Initialize Firebase if not already done
        try:
            firebase_admin.get_app()
            # App already initialized
        except ValueError:
            # No default app exists, initialize it
            if credentials_path:
                creds = credentials.Certificate(credentials_path)
                firebase_admin.initialize_app(creds)
            else:
                firebase_admin.initialize_app()

        self.db: Client = firestore.client()
        logger.info("QuotaAwareFirestoreRepository initialized")

    # ==================== Control & Epoch ====================

    def get_control(self) -> Optional[V5Control]:
        """Get v5_control/active."""
        allowed, reason = self.quota_guard.check_can_read(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot read control: {reason}")
            return None

        try:
            doc = self.db.collection("v5_control").document("active").get()
            self.quota_guard.record_read(1)
            if doc.exists:
                return from_firestore_dict(V5Control, doc.to_dict())
            return None
        except Exception as e:
            logger.error(f"Failed to read control: {e}")
            return None

    def set_control(self, control: V5Control) -> bool:
        """Set v5_control/active."""
        allowed, reason = self.quota_guard.check_can_write(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot write control: {reason}")
            return False

        try:
            self.db.collection("v5_control").document("active").set(to_firestore_dict(control))
            self.quota_guard.record_write(1)
            return True
        except Exception as e:
            logger.error(f"Failed to write control: {e}")
            return False

    def get_epoch(self, epoch_id: str) -> Optional[V5Epoch]:
        """Get v5_epochs/{epoch_id}."""
        allowed, reason = self.quota_guard.check_can_read(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot read epoch: {reason}")
            return None

        try:
            doc = self.db.collection("v5_epochs").document(epoch_id).get()
            self.quota_guard.record_read(1)
            if doc.exists:
                return from_firestore_dict(V5Epoch, doc.to_dict())
            return None
        except Exception as e:
            logger.error(f"Failed to read epoch {epoch_id}: {e}")
            return None

    def set_epoch(self, epoch: V5Epoch) -> bool:
        """Set v5_epochs/{epoch_id}."""
        allowed, reason = self.quota_guard.check_can_write(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot write epoch: {reason}")
            return False

        try:
            self.db.collection("v5_epochs").document(epoch.epoch_id).set(to_firestore_dict(epoch))
            self.quota_guard.record_write(1)
            return True
        except Exception as e:
            logger.error(f"Failed to write epoch {epoch.epoch_id}: {e}")
            return False

    # ==================== Trades ====================

    def create_trade(self, trade: V5Trade) -> bool:
        """Create v5_trades/{trade_id}."""
        allowed, reason = self.quota_guard.check_can_write(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot create trade: {reason}")
            self.outbox.enqueue_trade_outcome(trade.trade_id, trade.epoch_id, to_firestore_dict(trade))
            return False

        try:
            self.db.collection("v5_trades").document(trade.trade_id).set(to_firestore_dict(trade))
            self.quota_guard.record_write(1)
            return True
        except Exception as e:
            logger.error(f"Failed to create trade {trade.trade_id}: {e}")
            self.outbox.enqueue_trade_outcome(trade.trade_id, trade.epoch_id, to_firestore_dict(trade))
            self.outbox.record_sync_failure(trade.trade_id, str(e))
            return False

    def close_trade(self, trade: V5Trade) -> bool:
        """Update v5_trades/{trade_id} with CLOSED status."""
        allowed, reason = self.quota_guard.check_can_write(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot close trade: {reason}")
            self.outbox.enqueue_trade_outcome(trade.trade_id, trade.epoch_id, to_firestore_dict(trade))
            return False

        try:
            self.db.collection("v5_trades").document(trade.trade_id).update(to_firestore_dict(trade))
            self.quota_guard.record_write(1)
            self.outbox.mark_trade_synced(trade.trade_id)
            return True
        except Exception as e:
            logger.error(f"Failed to close trade {trade.trade_id}: {e}")
            self.outbox.enqueue_trade_outcome(trade.trade_id, trade.epoch_id, to_firestore_dict(trade))
            self.outbox.record_sync_failure(trade.trade_id, str(e))
            return False

    def get_trade(self, trade_id: str) -> Optional[V5Trade]:
        """Get v5_trades/{trade_id}."""
        allowed, reason = self.quota_guard.check_can_read(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot read trade: {reason}")
            return None

        try:
            doc = self.db.collection("v5_trades").document(trade_id).get()
            self.quota_guard.record_read(1)
            if doc.exists:
                return from_firestore_dict(V5Trade, doc.to_dict())
            return None
        except Exception as e:
            logger.error(f"Failed to read trade {trade_id}: {e}")
            return None

    # ==================== Open Positions ====================

    def get_open_positions(self, epoch_id: str) -> Optional[V5OpenPositions]:
        """Get v5_runtime/open_positions."""
        allowed, reason = self.quota_guard.check_can_read(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot read open positions: {reason}")
            return None

        try:
            doc = self.db.collection("v5_runtime").document("open_positions").get()
            self.quota_guard.record_read(1)
            if doc.exists:
                return from_firestore_dict(V5OpenPositions, doc.to_dict())
            # Return empty
            return V5OpenPositions(epoch_id=epoch_id)
        except Exception as e:
            logger.error(f"Failed to read open positions: {e}")
            return None

    def set_open_positions(self, positions: V5OpenPositions) -> bool:
        """Set v5_runtime/open_positions."""
        allowed, reason = self.quota_guard.check_can_write(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot write open positions: {reason}")
            return False

        try:
            self.db.collection("v5_runtime").document("open_positions").set(to_firestore_dict(positions))
            self.quota_guard.record_write(1)
            return True
        except Exception as e:
            logger.error(f"Failed to write open positions: {e}")
            return False

    # ==================== Learning ====================

    def get_learning_state(self, epoch_id: str) -> Optional[V5LearningState]:
        """Get v5_learning/state."""
        allowed, reason = self.quota_guard.check_can_read(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot read learning state: {reason}")
            return None

        try:
            doc = self.db.collection("v5_learning").document("state").get()
            self.quota_guard.record_read(1)
            if doc.exists:
                return from_firestore_dict(V5LearningState, doc.to_dict())
            return V5LearningState(epoch_id=epoch_id)
        except Exception as e:
            logger.error(f"Failed to read learning state: {e}")
            return None

    def set_learning_state(self, state: V5LearningState) -> bool:
        """Set v5_learning/state."""
        allowed, reason = self.quota_guard.check_can_write(1)
        if not allowed:
            logger.warning(f"Quota limit: cannot write learning state: {reason}")
            self.outbox.enqueue_learning_update(state.epoch_id, "global", to_firestore_dict(state))
            return False

        try:
            self.db.collection("v5_learning").document("state").set(to_firestore_dict(state))
            self.quota_guard.record_write(1)
            return True
        except Exception as e:
            logger.error(f"Failed to write learning state: {e}")
            self.outbox.record_learning_sync_failure(-1, str(e))
            return False

    # ==================== Dashboard & Metrics ====================

    def get_dashboard(self) -> Optional[V5Dashboard]:
        """Get v5_dashboard/current."""
        allowed, reason = self.quota_guard.check_can_read(1)
        if not allowed:
            return None

        try:
            doc = self.db.collection("v5_dashboard").document("current").get()
            self.quota_guard.record_read(1)
            if doc.exists:
                return from_firestore_dict(V5Dashboard, doc.to_dict())
            return None
        except Exception as e:
            logger.error(f"Failed to read dashboard: {e}")
            return None

    def set_dashboard(self, dashboard: V5Dashboard) -> bool:
        """Set v5_dashboard/current."""
        allowed, reason = self.quota_guard.check_can_write(1)
        if not allowed:
            return False

        try:
            self.db.collection("v5_dashboard").document("current").set(to_firestore_dict(dashboard))
            self.quota_guard.record_write(1)
            return True
        except Exception as e:
            logger.error(f"Failed to write dashboard: {e}")
            return False

    def get_readiness(self) -> Optional[V5Readiness]:
        """Get v5_readiness/current."""
        allowed, reason = self.quota_guard.check_can_read(1)
        if not allowed:
            return None

        try:
            doc = self.db.collection("v5_readiness").document("current").get()
            self.quota_guard.record_read(1)
            if doc.exists:
                return from_firestore_dict(V5Readiness, doc.to_dict())
            return None
        except Exception as e:
            logger.error(f"Failed to read readiness: {e}")
            return None

    def set_readiness(self, readiness: V5Readiness) -> bool:
        """Set v5_readiness/current."""
        allowed, reason = self.quota_guard.check_can_write(1)
        if not allowed:
            return False

        try:
            self.db.collection("v5_readiness").document("current").set(to_firestore_dict(readiness))
            self.quota_guard.record_write(1)
            return True
        except Exception as e:
            logger.error(f"Failed to write readiness: {e}")
            return False

    # ==================== Quota & Monitoring ====================

    def get_quota_status(self) -> Dict[str, Any]:
        """Get current quota guard status."""
        return self.quota_guard.get_status()

    def publish_quota(self, quota: V5Quota) -> bool:
        """Publish v5_quota/{quota_day_pt}."""
        allowed, reason = self.quota_guard.check_can_write(1)
        if not allowed:
            return False

        try:
            self.db.collection("v5_quota").document(quota.quota_day_pt).set(to_firestore_dict(quota))
            self.quota_guard.record_write(1)
            return True
        except Exception as e:
            logger.error(f"Failed to publish quota: {e}")
            return False

    # ==================== Startup Recovery ====================

    def flush_outbox(self, max_retries: int = 3) -> bool:
        """
        Attempt to flush pending trades/learning from outbox.

        Only called when quota is sufficient.
        """
        if not self._check_outbox_flush_allowed():
            logger.warning("Outbox flush blocked by quota or other limit")
            return False

        success = True
        for trade in self.outbox.get_pending_trade_outcomes(limit=20):
            if trade["sync_attempts"] > max_retries:
                logger.warning(f"Trade {trade['trade_id']} exceeded max retries, discarding")
                self.outbox.mark_trade_synced(trade["trade_id"])
                continue

            # Reconstruct Trade object and retry Firebase write
            trade_doc = V5Trade(**trade["outcome"])
            if self.close_trade(trade_doc):
                self.outbox.mark_trade_synced(trade["trade_id"])
            else:
                success = False

        return success

    def _check_outbox_flush_allowed(self) -> bool:
        """Check if outbox flush is allowed based on quota."""
        status = self.quota_guard.get_status()
        return status["state"] not in ("critical", "hard_stop")

    def get_outbox_status(self) -> Dict[str, Any]:
        """Get current outbox status."""
        return self.outbox.get_outbox_status()
