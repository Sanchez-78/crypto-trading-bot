"""
V5 Legacy Bridge — Firebase Writer

Handles all Firebase writes through quota guard with outbox fallback.
Never loses trades if Firebase is unavailable.
"""

import logging
from typing import Optional

from . import config
from .event_models import LegacyPaperOpenEvent, LegacyPaperCloseEvent
from .quota import V5LegacyQuotaGuard
from .outbox import DurableOutbox

logger = logging.getLogger(__name__)


class V5LegacyFirebaseWriter:
    """
    Manages Firebase writes with quota guards and fallback to durable outbox.

    Never loses closed trades if Firebase is unavailable.
    """

    def __init__(self, firebase_client=None, quota_guard: V5LegacyQuotaGuard = None, outbox: DurableOutbox = None):
        """
        Initialize Firebase writer.

        Args:
            firebase_client: Existing legacy Firebase client (or None if disabled)
            quota_guard: Quota guard instance
            outbox: Outbox instance
        """
        self.firebase_client = firebase_client
        self.quota_guard = quota_guard or V5LegacyQuotaGuard()
        self.outbox = outbox or DurableOutbox()

    def write_open(self, event: LegacyPaperOpenEvent) -> bool:
        """
        Write paper open event to Firebase.

        Args:
            event: LegacyPaperOpenEvent

        Returns:
            True if written or queued, False if failed
        """
        try:
            if not self.firebase_client:
                logger.warning(
                    f"[V5_BRIDGE] Firebase client unavailable, enqueuing paper_open "
                    f"trade_id={event.trade_id}"
                )
                return self.outbox.enqueue("paper_open", event.trade_id, event.to_dict())

            # Check quota
            decision = self.quota_guard.check_can_write(1)
            if not decision.allowed:
                logger.warning(
                    f"[V5_BRIDGE] Quota exhausted for paper_open trade_id={event.trade_id}, "
                    f"enqueuing to outbox"
                )
                return self.outbox.enqueue("paper_open", event.trade_id, event.to_dict())

            # Write to Firebase
            path = f"v5_trades/{event.trade_id}"
            try:
                self.firebase_client.set(path, event.to_dict())
                self.quota_guard.record_write(1, reason="paper_open")
                logger.info(
                    f"[V5_BRIDGE_OPEN_SAVED] trade_id={event.trade_id} "
                    f"symbol={event.symbol} side={event.side}"
                )
                return True
            except Exception as e:
                logger.error(
                    f"[V5_BRIDGE_FIREBASE_WRITE_FAILED] paper_open trade_id={event.trade_id}, "
                    f"error={str(e)[:100]}, enqueuing to outbox"
                )
                return self.outbox.enqueue("paper_open", event.trade_id, event.to_dict())

        except Exception as e:
            logger.error(f"[V5_BRIDGE] write_open failed: {e}")
            return False

    def write_close(self, event: LegacyPaperCloseEvent) -> bool:
        """
        Write paper close event to Firebase.

        Close events are critical: if Firebase fails, always enqueue to outbox.

        Args:
            event: LegacyPaperCloseEvent

        Returns:
            True if written or queued, False if failed to queue
        """
        try:
            if not self.firebase_client:
                logger.warning(
                    f"[V5_BRIDGE] Firebase client unavailable, enqueuing paper_close "
                    f"trade_id={event.trade_id}"
                )
                return self.outbox.enqueue("paper_close", event.trade_id, event.to_dict())

            # Check quota - but allow close to be enqueued even if no write quota
            # since close_reserve is maintained for this purpose
            decision = self.quota_guard.check_can_write(1)

            # Always try to write first if we have quota
            if decision.allowed:
                try:
                    path = f"v5_trades/{event.trade_id}"
                    self.firebase_client.set(path, event.to_dict())
                    self.quota_guard.record_write(1, reason="paper_close")
                    logger.info(
                        f"[V5_BRIDGE_CLOSE_SAVED] trade_id={event.trade_id} "
                        f"symbol={event.symbol} exit_reason={event.exit_reason} "
                        f"net_pnl={event.net_pnl:.2f}"
                    )
                    return True
                except Exception as e:
                    logger.warning(
                        f"[V5_BRIDGE_FIREBASE_WRITE_FAILED] paper_close trade_id={event.trade_id}, "
                        f"error={str(e)[:100]}, enqueuing to outbox"
                    )
                    return self.outbox.enqueue("paper_close", event.trade_id, event.to_dict())
            else:
                # No write quota - enqueue for retry
                logger.warning(
                    f"[V5_BRIDGE] Quota exhausted for paper_close trade_id={event.trade_id}, "
                    f"enqueuing to outbox for later persistence"
                )
                return self.outbox.enqueue("paper_close", event.trade_id, event.to_dict())

        except Exception as e:
            logger.error(f"[V5_BRIDGE] write_close failed: {e}")
            # Even on error, try to enqueue
            try:
                return self.outbox.enqueue("paper_close", event.trade_id, event.to_dict())
            except Exception as e2:
                logger.critical(f"[V5_BRIDGE] Failed to enqueue paper_close: {e2}")
                return False

    def write_learning_update(self, trade_id: str, payload: dict) -> bool:
        """
        Write learning update for a closed trade.

        Args:
            trade_id: Trade ID (used as idempotency key)
            payload: Learning update payload

        Returns:
            True if written or queued
        """
        try:
            if not self.firebase_client:
                logger.debug(f"[V5_BRIDGE] Firebase client unavailable, enqueuing learning_update")
                return self.outbox.enqueue("learning_update", trade_id, payload)

            decision = self.quota_guard.check_can_write(1)
            if not decision.allowed:
                logger.debug(
                    f"[V5_BRIDGE] Quota exhausted for learning_update, enqueuing to outbox"
                )
                return self.outbox.enqueue("learning_update", trade_id, payload)

            try:
                path = f"v5_trades/{trade_id}/learning"
                self.firebase_client.set(path, payload)
                self.quota_guard.record_write(1, reason="learning_update")
                logger.debug(f"[V5_BRIDGE_LEARNING_UPDATE] trade_id={trade_id}")
                return True
            except Exception as e:
                logger.debug(
                    f"[V5_BRIDGE_FIREBASE_WRITE_FAILED] learning_update trade_id={trade_id}, "
                    f"enqueuing to outbox"
                )
                return self.outbox.enqueue("learning_update", trade_id, payload)

        except Exception as e:
            logger.error(f"[V5_BRIDGE] write_learning_update failed: {e}")
            return False

    def write_dashboard(self, payload: dict) -> bool:
        """
        Write dashboard snapshot.

        Args:
            payload: Dashboard payload

        Returns:
            True if written or queued
        """
        try:
            if not self.firebase_client:
                return self.outbox.enqueue("dashboard_publish", "dashboard_current", payload)

            decision = self.quota_guard.check_can_write(1)
            if not decision.allowed:
                return self.outbox.enqueue("dashboard_publish", "dashboard_current", payload)

            try:
                self.firebase_client.set(config.FIREBASE_DASHBOARD_PATH, payload)
                self.quota_guard.record_write(1, reason="dashboard")
                return True
            except Exception as e:
                logger.debug(f"[V5_BRIDGE] Dashboard write failed, enqueuing: {e}")
                return self.outbox.enqueue("dashboard_publish", "dashboard_current", payload)

        except Exception as e:
            logger.error(f"[V5_BRIDGE] write_dashboard failed: {e}")
            return False

    def write_readiness(self, payload: dict) -> bool:
        """
        Write readiness snapshot.

        Args:
            payload: Readiness payload

        Returns:
            True if written or queued
        """
        try:
            if not self.firebase_client:
                return self.outbox.enqueue("readiness_publish", "readiness_current", payload)

            decision = self.quota_guard.check_can_write(1)
            if not decision.allowed:
                return self.outbox.enqueue("readiness_publish", "readiness_current", payload)

            try:
                self.firebase_client.set(config.FIREBASE_READINESS_PATH, payload)
                self.quota_guard.record_write(1, reason="readiness")
                return True
            except Exception as e:
                logger.debug(f"[V5_BRIDGE] Readiness write failed, enqueuing: {e}")
                return self.outbox.enqueue("readiness_publish", "readiness_current", payload)

        except Exception as e:
            logger.error(f"[V5_BRIDGE] write_readiness failed: {e}")
            return False

    def write_quota(self, payload: dict) -> bool:
        """
        Write quota snapshot.

        Args:
            payload: Quota payload

        Returns:
            True if written or queued
        """
        try:
            if not self.firebase_client:
                date = payload.get("date", "unknown")
                return self.outbox.enqueue("quota_publish", f"quota_{date}", payload)

            decision = self.quota_guard.check_can_write(1)
            if not decision.allowed:
                date = payload.get("date", "unknown")
                return self.outbox.enqueue("quota_publish", f"quota_{date}", payload)

            try:
                date = payload.get("date", "unknown")
                path = f"v5_quota/{date}"
                self.firebase_client.set(path, payload)
                self.quota_guard.record_write(1, reason="quota")
                return True
            except Exception as e:
                logger.debug(f"[V5_BRIDGE] Quota write failed, enqueuing: {e}")
                date = payload.get("date", "unknown")
                return self.outbox.enqueue("quota_publish", f"quota_{date}", payload)

        except Exception as e:
            logger.error(f"[V5_BRIDGE] write_quota failed: {e}")
            return False

    def flush_outbox(self, limit: int = 20) -> dict:
        """
        Attempt to flush outbox entries to Firebase.

        Args:
            limit: Max entries to attempt

        Returns:
            Status dict with counts
        """
        try:
            pending = self.outbox.get_pending(limit)
            sent = 0
            failed = 0

            for entry in pending:
                success = False

                try:
                    if not self.firebase_client:
                        break

                    # Check quota for retry
                    decision = self.quota_guard.check_can_write(1)
                    if not decision.allowed:
                        logger.debug(f"[V5_BRIDGE] Quota exhausted, stopping outbox flush")
                        break

                    # Attempt write based on event type
                    if entry.event_type == "paper_open":
                        self.firebase_client.set(f"v5_trades/{entry.idempotency_key}", entry.payload)
                        self.quota_guard.record_write(1, reason="outbox_replay")
                        success = True
                    elif entry.event_type == "paper_close":
                        self.firebase_client.set(f"v5_trades/{entry.idempotency_key}", entry.payload)
                        self.quota_guard.record_write(1, reason="outbox_replay")
                        success = True
                    elif entry.event_type == "learning_update":
                        self.firebase_client.set(
                            f"v5_trades/{entry.idempotency_key}/learning", entry.payload
                        )
                        self.quota_guard.record_write(1, reason="outbox_replay")
                        success = True
                    elif entry.event_type == "dashboard_publish":
                        self.firebase_client.set(config.FIREBASE_DASHBOARD_PATH, entry.payload)
                        self.quota_guard.record_write(1, reason="outbox_replay")
                        success = True
                    elif entry.event_type == "readiness_publish":
                        self.firebase_client.set(config.FIREBASE_READINESS_PATH, entry.payload)
                        self.quota_guard.record_write(1, reason="outbox_replay")
                        success = True
                    elif entry.event_type == "quota_publish":
                        date = entry.payload.get("date", "unknown")
                        self.firebase_client.set(f"v5_quota/{date}", entry.payload)
                        self.quota_guard.record_write(1, reason="outbox_replay")
                        success = True

                    if success:
                        self.outbox.mark_sent(entry.id)
                        sent += 1
                        logger.info(
                            f"[V5_BRIDGE_OUTBOX_SENT] id={entry.id} "
                            f"event_type={entry.event_type} retry_count={entry.retry_count}"
                        )
                    else:
                        self.outbox.mark_failed(entry.id, "unknown event type")
                        failed += 1

                except Exception as e:
                    self.outbox.mark_failed(entry.id, str(e))
                    failed += 1
                    logger.warning(
                        f"[V5_BRIDGE_OUTBOX_RETRY] id={entry.id} "
                        f"event_type={entry.event_type} error={str(e)[:100]}"
                    )

            return {
                "processed": len(pending),
                "sent": sent,
                "failed": failed,
                "pending_count": self.outbox.pending_count(),
            }

        except Exception as e:
            logger.error(f"[V5_BRIDGE] flush_outbox failed: {e}")
            return {
                "processed": 0,
                "sent": 0,
                "failed": 0,
                "pending_count": self.outbox.pending_count(),
                "error": str(e),
            }
