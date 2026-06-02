"""
V5 Legacy Bridge — Outbox Flush Worker

Processes pending outbox events and persists them to Firebase.
Runs on a background thread with exponential backoff retry logic.

Handles:
- paper_open: Trade entry events
- paper_close: Trade exit events (critical path)
- learning_update: Learning segment updates
- dashboard_publish: Dashboard metrics
- readiness_publish: Real readiness progression
- quota_publish: Quota exhaustion alerts
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, List

from .outbox import DurableOutbox, OutboxEntry
from .firebase_writer import V5LegacyFirebaseWriter
from . import config

logger = logging.getLogger(__name__)


class OutboxFlushWorker:
    """
    Processes pending outbox entries and flushes to Firebase.

    Runs on background thread:
    - Polls outbox every N seconds for pending entries
    - Attempts to write to Firebase
    - On success: marks entry as sent (deletes from outbox)
    - On failure: schedules exponential backoff retry
    - Thread-safe: all DB operations under SQLite implicit lock
    """

    def __init__(self, outbox: DurableOutbox, firebase_writer: V5LegacyFirebaseWriter):
        """
        Initialize flush worker.

        Args:
            outbox: DurableOutbox instance
            firebase_writer: V5LegacyFirebaseWriter instance
        """
        self.outbox = outbox
        self.firebase_writer = firebase_writer
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start background flush worker thread."""
        if self.running:
            logger.warning("[V5_BRIDGE_OUTBOX_FLUSH] Worker already running")
            return

        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="v5-outbox-flush")
        self._thread.start()
        logger.info("[V5_BRIDGE_OUTBOX_FLUSH] Worker started")

    def stop(self) -> None:
        """Stop background worker and flush remaining entries."""
        if not self.running:
            return

        logger.info("[V5_BRIDGE_OUTBOX_FLUSH] Stopping worker...")
        self._stop_event.set()

        # Final flush before shutdown
        try:
            self._flush_batch()
        except Exception as e:
            logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_FINAL] Error: {e}")

        if self._thread:
            self._thread.join(timeout=5)

        self.running = False
        logger.info("[V5_BRIDGE_OUTBOX_FLUSH] Worker stopped")

    def _run_loop(self) -> None:
        """Main worker loop: poll and flush outbox entries."""
        while self.running and not self._stop_event.is_set():
            try:
                self._flush_batch()
            except Exception as e:
                logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_ERROR] {e}")

            # Sleep before next poll
            if not self._stop_event.wait(config.OUTBOX_FLUSH_INTERVAL_S):
                continue
            # Stop event was set, exit loop
            break

    def _flush_batch(self, batch_size: int = 20) -> int:
        """
        Flush a batch of pending outbox entries to Firebase.

        Args:
            batch_size: Max entries to process in one batch

        Returns:
            Number of entries successfully sent
        """
        if not self.firebase_writer or not self.firebase_writer.firebase_client:
            # Firebase unavailable, skip flush (entries stay in outbox)
            return 0

        pending = self.outbox.get_pending(limit=batch_size)
        if not pending:
            return 0

        sent_count = 0
        for entry in pending:
            try:
                success = self._process_entry(entry)
                if success:
                    sent_count += 1
                    self.outbox.mark_sent(entry.id)
                    logger.info(
                        f"[V5_BRIDGE_OUTBOX_FLUSH_SENT] event_type={entry.event_type} "
                        f"idempotency_key={entry.idempotency_key}"
                    )
                else:
                    # Mark as failed, will retry on next run
                    self.outbox.mark_failed(entry.id, "Firebase write failed")
            except Exception as e:
                logger.error(
                    f"[V5_BRIDGE_OUTBOX_FLUSH_FAILED] event_type={entry.event_type} "
                    f"id={entry.id} error={str(e)[:100]}"
                )
                self.outbox.mark_failed(entry.id, str(e)[:500])

        if sent_count > 0:
            logger.info(
                f"[V5_BRIDGE_OUTBOX_FLUSH_BATCH] sent={sent_count}/{len(pending)} "
                f"batch_size={batch_size}"
            )

        return sent_count

    def _process_entry(self, entry: OutboxEntry) -> bool:
        """
        Process a single outbox entry by writing to Firebase.

        Args:
            entry: OutboxEntry to process

        Returns:
            True if successfully written, False otherwise
        """
        event_type = entry.event_type
        payload = entry.payload

        if event_type == "paper_open":
            return self._write_paper_open(payload)
        elif event_type == "paper_close":
            return self._write_paper_close(payload)
        elif event_type == "learning_update":
            return self._write_learning_update(payload)
        elif event_type == "dashboard_publish":
            return self._write_dashboard_publish(payload)
        elif event_type == "readiness_publish":
            return self._write_readiness_publish(payload)
        elif event_type == "quota_publish":
            return self._write_quota_publish(payload)
        else:
            logger.warning(f"[V5_BRIDGE_OUTBOX_FLUSH] Unknown event type: {event_type}")
            return False

    def _write_paper_open(self, payload: dict) -> bool:
        """Write paper_open event to Firebase."""
        if not self.firebase_writer.firebase_client:
            return False

        try:
            trade_id = payload.get("trade_id")
            path = f"v5_trades/{trade_id}"
            self.firebase_writer.firebase_client.set(path, payload)
            self.firebase_writer.quota_guard.record_write(1, reason="paper_open_flush")
            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_WRITE_OPEN] {e}")
            return False

    def _write_paper_close(self, payload: dict) -> bool:
        """Write paper_close event to Firebase."""
        if not self.firebase_writer.firebase_client:
            return False

        try:
            trade_id = payload.get("trade_id")
            path = f"v5_trades/{trade_id}"
            # Update trade with close details
            self.firebase_writer.firebase_client.update(path, payload)
            self.firebase_writer.quota_guard.record_write(1, reason="paper_close_flush")
            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_WRITE_CLOSE] {e}")
            return False

    def _write_learning_update(self, payload: dict) -> bool:
        """Write learning_update event to Firebase."""
        if not self.firebase_writer.firebase_client:
            return False

        try:
            trade_id = payload.get("trade_id")
            segment = payload.get("segment")
            path = f"v5_learning/{segment}/{trade_id}"
            self.firebase_writer.firebase_client.set(path, payload)
            self.firebase_writer.quota_guard.record_write(1, reason="learning_update_flush")
            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_WRITE_LEARNING] {e}")
            return False

    def _write_dashboard_publish(self, payload: dict) -> bool:
        """Write dashboard_publish event to Firebase."""
        if not self.firebase_writer.firebase_client:
            return False

        try:
            path = "v5_dashboard/current"
            self.firebase_writer.firebase_client.set(path, payload)
            self.firebase_writer.quota_guard.record_write(1, reason="dashboard_publish_flush")
            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_WRITE_DASHBOARD] {e}")
            return False

    def _write_readiness_publish(self, payload: dict) -> bool:
        """Write readiness_publish event to Firebase."""
        if not self.firebase_writer.firebase_client:
            return False

        try:
            segment = payload.get("segment", "unknown")
            path = f"v5_readiness/{segment}"
            self.firebase_writer.firebase_client.set(path, payload)
            self.firebase_writer.quota_guard.record_write(1, reason="readiness_publish_flush")
            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_WRITE_READINESS] {e}")
            return False

    def _write_quota_publish(self, payload: dict) -> bool:
        """Write quota_publish event to Firebase."""
        if not self.firebase_writer.firebase_client:
            return False

        try:
            path = "v5_quota/current"
            self.firebase_writer.firebase_client.set(path, payload)
            self.firebase_writer.quota_guard.record_write(1, reason="quota_publish_flush")
            return True
        except Exception as e:
            logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_WRITE_QUOTA] {e}")
            return False

    def get_status(self) -> dict:
        """Get worker status and outbox metrics."""
        pending_count = self.outbox.pending_count() if self.outbox else 0

        # Count by event type
        if self.outbox:
            pending = self.outbox.get_pending(limit=1000)
            count_by_type = {}
            for entry in pending:
                count_by_type[entry.event_type] = count_by_type.get(entry.event_type, 0) + 1
        else:
            count_by_type = {}

        return {
            "running": self.running,
            "pending_count": pending_count,
            "count_by_type": count_by_type,
            "firebase_connected": bool(
                self.firebase_writer and self.firebase_writer.firebase_client
            ),
        }
