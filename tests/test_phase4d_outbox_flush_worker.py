"""Phase 4D: Outbox Flush Worker Tests

Verify that:
1. Flush worker processes pending outbox entries
2. Firebase writes are successful and idempotent
3. Retry logic works with exponential backoff
4. Quota guard prevents overspend
5. Thread safety (worker can run in background)
"""

import pytest
import time
import sqlite3
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch

from src.services.v5_legacy_bridge.outbox import DurableOutbox
from src.services.v5_legacy_bridge.firebase_writer import V5LegacyFirebaseWriter
from src.services.v5_legacy_bridge.outbox_flush_worker import OutboxFlushWorker
from src.services.v5_legacy_bridge.quota import V5LegacyQuotaGuard
from src.services.v5_legacy_bridge import config


class TestOutboxFlushWorker:
    """Test outbox flush worker."""

    def setup_method(self):
        """Create fresh outbox and worker for each test."""
        # Clear outbox DB before test
        import os
        db_path = config.V5_OUTBOX_DB_PATH
        if os.path.exists(db_path):
            os.remove(db_path)

        self.outbox = DurableOutbox()
        self.firebase_writer = Mock(spec=V5LegacyFirebaseWriter)
        self.firebase_writer.firebase_client = Mock()
        self.firebase_writer.quota_guard = Mock(spec=V5LegacyQuotaGuard)

    def teardown_method(self):
        """Clean up worker."""
        if hasattr(self, 'worker') and self.worker:
            self.worker.stop()

        # Clean up DB
        import os
        db_path = config.V5_OUTBOX_DB_PATH
        if os.path.exists(db_path):
            os.remove(db_path)

    def test_worker_starts_and_stops(self):
        """Worker can start and stop cleanly."""
        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
        self.worker.start()
        assert self.worker.running

        self.worker.stop()
        assert not self.worker.running

    def test_flush_paper_open_to_firebase(self):
        """Flush worker writes paper_open to Firebase."""
        # Enqueue a paper_open event
        payload = {
            "trade_id": "trade_123",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "entry_price": 50000.0,
            "qty": 0.1,
        }
        self.outbox.enqueue("paper_open", "trade_123", payload)

        # Mock Firebase write
        self.firebase_writer.firebase_client.set = Mock()
        self.firebase_writer.quota_guard.record_write = Mock()

        # Create worker and process one batch
        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
        sent = self.worker._flush_batch(batch_size=10)

        assert sent == 1
        self.firebase_writer.firebase_client.set.assert_called_once()
        self.firebase_writer.quota_guard.record_write.assert_called_once()

        # Verify entry was deleted from outbox
        remaining = self.outbox.get_pending()
        assert len(remaining) == 0

    def test_flush_paper_close_to_firebase(self):
        """Flush worker writes paper_close to Firebase."""
        payload = {
            "trade_id": "trade_456",
            "close_price": 51000.0,
            "pnl_usd": 100.0,
            "pnl_pct": 2.0,
        }
        self.outbox.enqueue("paper_close", "trade_456", payload)

        # Mock Firebase update
        self.firebase_writer.firebase_client.update = Mock()
        self.firebase_writer.quota_guard.record_write = Mock()

        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
        sent = self.worker._flush_batch()

        assert sent == 1
        self.firebase_writer.firebase_client.update.assert_called_once()

    def test_flush_multiple_events_different_types(self):
        """Flush worker processes multiple event types in one batch."""
        # Enqueue mixed events
        self.outbox.enqueue("paper_open", "trade_1", {"trade_id": "trade_1"})
        self.outbox.enqueue("paper_close", "trade_1", {"trade_id": "trade_1"})
        self.outbox.enqueue("learning_update", "seg_1", {"segment": "seg_1"})

        # Mock all Firebase methods
        self.firebase_writer.firebase_client.set = Mock()
        self.firebase_writer.firebase_client.update = Mock()
        self.firebase_writer.quota_guard.record_write = Mock()

        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
        sent = self.worker._flush_batch(batch_size=10)

        assert sent == 3
        assert self.firebase_writer.firebase_client.set.call_count >= 1
        assert self.firebase_writer.quota_guard.record_write.call_count == 3

    def test_firebase_failure_triggers_retry(self):
        """On Firebase write failure, entry is marked for retry."""
        self.outbox.enqueue("paper_open", "trade_bad", {"trade_id": "trade_bad"})

        # Mock Firebase error
        self.firebase_writer.firebase_client.set = Mock(
            side_effect=Exception("Firebase connection failed")
        )
        self.firebase_writer.quota_guard.record_write = Mock()

        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
        sent = self.worker._flush_batch()

        # Should not be sent
        assert sent == 0

        # Entry should still be in outbox with retry_count = 1
        # Query directly from DB since get_pending filters by retry time
        conn = sqlite3.connect(config.V5_OUTBOX_DB_PATH)
        cursor = conn.execute("SELECT * FROM outbox WHERE idempotency_key = ?", ("trade_bad",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        # row format: id, event_type, idempotency_key, payload, retry_count, next_retry_at, error, created_at, updated_at
        retry_count = row[4]
        error = row[6]
        assert retry_count == 1
        assert error is not None

    def test_exponential_backoff_applied(self):
        """Retry scheduling uses exponential backoff."""
        # Test backoff calculation directly by manually incrementing retry_count
        self.outbox.enqueue("paper_open", "trade_exp", {"trade_id": "trade_exp"})

        # Manually mark as failed twice and check backoff times
        self.outbox.mark_failed(1, "First error")  # Increments to retry_count=1, backoff=60s

        conn = sqlite3.connect(config.V5_OUTBOX_DB_PATH)
        cursor = conn.execute("SELECT next_retry_at FROM outbox WHERE idempotency_key = ?", ("trade_exp",))
        first_retry_at = cursor.fetchone()[0]
        conn.close()

        # Now mark as failed again (will be retry_count=2, backoff=120s)
        time.sleep(0.1)  # Small delay to ensure different timestamp
        self.outbox.mark_failed(1, "Second error")

        conn = sqlite3.connect(config.V5_OUTBOX_DB_PATH)
        cursor = conn.execute("SELECT next_retry_at FROM outbox WHERE idempotency_key = ?", ("trade_exp",))
        second_retry_at = cursor.fetchone()[0]
        conn.close()

        # Parse timestamps and verify exponential backoff (120s > 60s)
        first_dt = datetime.fromisoformat(first_retry_at)
        second_dt = datetime.fromisoformat(second_retry_at)

        # Verify second is scheduled later due to exponential backoff
        # First call: backoff = 60 * 2^0 = 60 seconds
        # Second call: backoff = 60 * 2^1 = 120 seconds
        # So second_dt should be about 60 seconds later than first_dt
        time_diff = (second_dt - first_dt).total_seconds()
        assert time_diff > 50  # At least 50 seconds difference due to exponential backoff

    def test_worker_continues_on_single_event_failure(self):
        """If one event fails, worker continues with others."""
        self.outbox.enqueue("paper_open", "trade_ok", {"trade_id": "trade_ok"})
        self.outbox.enqueue("paper_close", "trade_fail", {"trade_id": "trade_fail"})
        self.outbox.enqueue("paper_open", "trade_ok2", {"trade_id": "trade_ok2"})

        # Mock: first succeeds, second fails, third succeeds
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:  # Second call (paper_close)
                raise Exception("Firebase error")
            return None

        self.firebase_writer.firebase_client.set = Mock(side_effect=side_effect)
        self.firebase_writer.firebase_client.update = Mock(side_effect=side_effect)
        self.firebase_writer.quota_guard.record_write = Mock()

        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
        sent = self.worker._flush_batch(batch_size=10)

        # Should have sent 2 (ok, ok2)
        assert sent == 2

        # One should still be in DB with retry_count=1 (trade_fail)
        conn = sqlite3.connect(config.V5_OUTBOX_DB_PATH)
        cursor = conn.execute("SELECT * FROM outbox WHERE idempotency_key = ?", ("trade_fail",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        retry_count = row[4]
        assert retry_count == 1

    def test_no_flush_if_firebase_unavailable(self):
        """Worker doesn't flush if Firebase client is unavailable."""
        self.outbox.enqueue("paper_open", "trade_noconnect", {"trade_id": "trade_noconnect"})

        # Firebase client is None
        self.firebase_writer.firebase_client = None

        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
        sent = self.worker._flush_batch()

        # Should not attempt write
        assert sent == 0

        # Entry should still be in outbox (not retried, still fresh)
        pending = self.outbox.get_pending(limit=10)
        assert len(pending) == 1
        assert pending[0].retry_count == 0  # Not marked as failed

    def test_batch_size_limit_respected(self):
        """Worker processes only batch_size entries per call."""
        # Enqueue 10 events
        for i in range(10):
            self.outbox.enqueue("paper_open", f"trade_{i}", {"trade_id": f"trade_{i}"})

        self.firebase_writer.firebase_client.set = Mock()
        self.firebase_writer.quota_guard.record_write = Mock()

        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
        sent = self.worker._flush_batch(batch_size=5)

        # Should process only 5
        assert sent == 5

        # 5 should remain
        pending = self.outbox.get_pending(limit=20)
        assert len(pending) == 5

    def test_background_worker_thread(self):
        """Worker runs in background thread and processes events periodically."""
        payload = {"trade_id": "trade_bg", "test": "data"}
        self.outbox.enqueue("paper_open", "trade_bg", payload)

        self.firebase_writer.firebase_client.set = Mock()
        self.firebase_writer.quota_guard.record_write = Mock()

        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)

        # Patch the flush interval to speed up test
        with patch.object(self.worker, '_flush_batch') as mock_flush:
            mock_flush.return_value = 1
            self.worker.start()

            # Give worker time to run
            time.sleep(0.2)

            # Flush should have been called
            assert mock_flush.call_count >= 1

            self.worker.stop()

    def test_worker_status_reporting(self):
        """Worker reports current status correctly."""
        self.outbox.enqueue("paper_open", "t1", {"trade_id": "t1"})
        self.outbox.enqueue("paper_close", "t2", {"trade_id": "t2"})

        self.firebase_writer.firebase_client = Mock()

        self.worker = OutboxFlushWorker(self.outbox, self.firebase_writer)
        status = self.worker.get_status()

        assert status["running"] == False  # Not started yet
        assert status["pending_count"] == 2
        assert status["count_by_type"]["paper_open"] == 1
        assert status["count_by_type"]["paper_close"] == 1
        assert status["firebase_connected"] == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
