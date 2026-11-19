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
from typing import Optional

from .outbox import DurableOutbox
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
    - Shares the writer's quota checks and serialized flush with the main loop
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
        if self.running or (self._thread is not None and self._thread.is_alive()):
            logger.warning("[V5_BRIDGE_OUTBOX_FLUSH] Worker already running")
            return

        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="v5-outbox-flush")
        self._thread.start()
        logger.info("[V5_BRIDGE_OUTBOX_FLUSH] Worker started")

    def stop(self) -> None:
        """Stop scheduling flushes; unfinished rows remain in the durable outbox."""
        if not self.running:
            return

        logger.info("[V5_BRIDGE_OUTBOX_FLUSH] Stopping worker...")
        self._stop_event.set()

        # The in-flight batch owns its acknowledgement. Do not start another
        # flush from the shutdown caller or wait indefinitely on a network call.
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        if self._thread is None or not self._thread.is_alive():
            self.running = False
            logger.info("[V5_BRIDGE_OUTBOX_FLUSH] Worker stopped")

    def _run_loop(self) -> None:
        """Main worker loop: poll and flush outbox entries."""
        try:
            while self.running and not self._stop_event.is_set():
                try:
                    self._flush_batch()
                except Exception as e:
                    logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_ERROR] {e}")
                if self._stop_event.wait(config.OUTBOX_FLUSH_INTERVAL_S):
                    break
        finally:
            self.running = False

    def _flush_batch(self, batch_size: int = 20) -> int:
        """
        Flush a batch of pending outbox entries to Firebase.

        Args:
            batch_size: Max entries to process in one batch

        Returns:
            Number of entries successfully sent
        """
        if not self.firebase_writer:
            return 0
        result = self.firebase_writer.flush_outbox(limit=batch_size)
        sent_count = result["sent"]
        if sent_count > 0:
            logger.info(
                f"[V5_BRIDGE_OUTBOX_FLUSH_BATCH] sent={sent_count}/{result['processed']} "
                f"batch_size={batch_size}"
            )
        return sent_count

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
