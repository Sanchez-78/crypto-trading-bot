"""Tests for V5 QuotaGuard and quota state transitions."""

import pytest
import tempfile
import os
from pathlib import Path
from datetime import datetime

from src.v5_bot.firebase.quota_guard import QuotaGuard, QuotaLedger


@pytest.fixture
def temp_db():
    """Use temporary SQLite database for tests."""
    import sqlite3
    import os
    import time

    with tempfile.TemporaryDirectory() as tmpdir:
        # Override DB path for test
        original_path = QuotaLedger.DB_PATH
        db_path = Path(tmpdir) / "test_quota.sqlite"
        QuotaLedger.DB_PATH = db_path
        try:
            yield
        finally:
            # Close any open connections
            import gc
            gc.collect()  # Force garbage collection to close dangling references
            time.sleep(0.1)  # Brief delay to ensure file handles are released

            # Close all SQLite connections
            try:
                sqlite3.connect(str(db_path)).close()
            except:
                pass

            # Remove WAL files manually
            for suffix in ['', '-wal', '-shm']:
                try:
                    (Path(tmpdir) / f"test_quota.sqlite{suffix}").unlink(missing_ok=True)
                except:
                    pass

            QuotaLedger.DB_PATH = original_path
            time.sleep(0.05)  # Allow Windows to release file locks


class TestQuotaLedger:
    """Tests for quota ledger persistence."""

    def test_initialization(self, temp_db):
        """Test ledger creates tables on init."""
        ledger = QuotaLedger()
        # Should not raise
        assert ledger.DB_PATH.exists() or ledger.DB_PATH.parent.exists()

    def test_record_read(self, temp_db):
        """Test recording read operations."""
        ledger = QuotaLedger()
        ledger.record_operation('read', 5)
        reads, writes, deletes, retries = ledger.get_daily_usage()
        assert reads == 5
        assert writes == 0

    def test_record_write(self, temp_db):
        """Test recording write operations."""
        ledger = QuotaLedger()
        ledger.record_operation('write', 3)
        reads, writes, deletes, retries = ledger.get_daily_usage()
        assert writes == 3
        assert reads == 0

    def test_cumulative_operations(self, temp_db):
        """Test that operations accumulate."""
        ledger = QuotaLedger()
        ledger.record_operation('read', 10)
        ledger.record_operation('read', 5)
        ledger.record_operation('write', 2)
        reads, writes, deletes, retries = ledger.get_daily_usage()
        assert reads == 15
        assert writes == 2

    def test_state_tracking(self, temp_db):
        """Test state update and retrieval."""
        ledger = QuotaLedger()
        ledger.update_state('warning')
        assert ledger.get_state() == 'warning'

        ledger.update_state('critical')
        assert ledger.get_state() == 'critical'


class TestQuotaGuard:
    """Tests for quota guard enforcement."""

    def test_normal_state(self, temp_db):
        """Test NORMAL state allows all operations."""
        guard = QuotaGuard()

        allowed, reason = guard.check_can_read(100)
        assert allowed

        allowed, reason = guard.check_can_write(100)
        assert allowed

    def test_warning_state_triggered_reads(self, temp_db):
        """Test WARNING state when reads exceed threshold."""
        guard = QuotaGuard()

        # Simulate crossing warning threshold
        for _ in range(4000):
            guard.record_read(1)

        allowed, reason = guard.check_can_read(1)
        assert allowed  # At warning, reads still allowed

        status = guard.get_status()
        assert status['state'] == 'warning'

    def test_warning_state_triggered_writes(self, temp_db):
        """Test WARNING state when writes exceed threshold."""
        guard = QuotaGuard()

        for _ in range(1500):
            guard.record_write(1)

        status = guard.get_status()
        assert status['state'] == 'warning'

    def test_degraded_state(self, temp_db):
        """Test DEGRADED state blocks some operations."""
        guard = QuotaGuard()

        # Exceed degraded threshold
        for _ in range(6000):
            guard.record_read(1)

        status = guard.get_status()
        assert status['state'] == 'degraded'
        # Should still allow operations in degraded state (per spec)
        allowed, _ = guard.check_can_read(1)
        assert allowed

    def test_critical_state(self, temp_db):
        """Test CRITICAL state blocks new entries."""
        guard = QuotaGuard()

        # Exceed critical threshold
        for _ in range(7500):
            guard.record_read(1)

        status = guard.get_status()
        assert status['state'] == 'critical'

    def test_hard_stop_state(self, temp_db):
        """Test HARD_STOP state blocks all operations."""
        guard = QuotaGuard()

        # Exceed hard cap
        for _ in range(8000):
            guard.record_read(1)

        status = guard.get_status()
        assert status['state'] == 'hard_stop'

        allowed, reason = guard.check_can_read(1)
        assert not allowed
        assert 'exhausted' in reason.lower()

    def test_entry_write_reserve_sufficient(self, temp_db):
        """Test entry is allowed when sufficient write reserve exists."""
        guard = QuotaGuard()
        guard.record_write(100)  # Use 100, 2900 remaining

        allowed, reason = guard.check_entry_write_reserve(open_count=10)
        assert allowed, f"Expected sufficient reserve, got: {reason}"

    def test_entry_write_reserve_insufficient(self, temp_db):
        """Test entry is blocked when insufficient write reserve."""
        guard = QuotaGuard()
        # Now uses internal daily cap (10000), so need to get close to that
        # Record 9990 writes, leaving only 10 for remaining writes
        guard.record_write(9990)

        # Entry with 10 open positions needs: 10*3 + 4 + 20 = 54 writes
        # Only 10 remaining, so should be blocked with insufficient reason
        allowed, reason = guard.check_entry_write_reserve(open_count=10)
        assert not allowed
        assert 'insufficient' in reason.lower()

    def test_quota_status_dict(self, temp_db):
        """Test quota status dictionary."""
        guard = QuotaGuard()
        guard.record_read(500)
        guard.record_write(200)

        status = guard.get_status()
        assert status['reads_attempted'] == 500
        assert status['writes_attempted'] == 200
        assert status['reads_remaining'] == guard.HARD_CAP_READS - 500
        assert status['writes_remaining'] == guard.HARD_CAP_WRITES - 200
        assert 'state' in status
        assert 'timestamp' in status

    def test_state_transitions_sequence(self, temp_db):
        """Test realistic state transition sequence (session-level caps)."""
        guard = QuotaGuard()

        # Start NORMAL
        status = guard.get_status()
        assert status['state'] == 'normal'

        # Reach WARNING (threshold = 1500)
        guard.record_write(1500)
        status = guard.get_status()
        assert status['state'] == 'warning', f"Expected warning but got {status['state']} at 1500 writes"

        # Reach DEGRADED (threshold = 2500)
        guard.record_write(1000)
        status = guard.get_status()
        assert status['state'] == 'degraded', f"Expected degraded but got {status['state']} at 2500 writes"

        # Reach CRITICAL (threshold = 2800)
        guard.record_write(300)
        status = guard.get_status()
        assert status['state'] == 'critical', f"Expected critical but got {status['state']} at 2800 writes"

        # Reach HARD_STOP (hard_cap = 3000)
        guard.record_write(200)
        status = guard.get_status()
        assert status['state'] == 'hard_stop', f"Expected hard_stop but got {status['state']} at 3000 writes"

        allowed, _ = guard.check_can_write(1)
        assert not allowed

    def test_retry_tracking(self, temp_db):
        """Test retry attempt tracking."""
        guard = QuotaGuard()
        guard.record_retry()
        guard.record_retry()

        status = guard.get_status()
        assert status['retries_attempted'] == 2

    def test_hard_cap_read_enforcement(self, temp_db):
        """Test hard cap on reads is strictly enforced."""
        guard = QuotaGuard()

        # Use up to near hard cap
        for _ in range(7999):
            guard.record_read(1)

        # Next read should be rejected
        allowed, reason = guard.check_can_read(1)
        assert not allowed

    def test_hard_cap_write_enforcement(self, temp_db):
        """Test hard cap on writes is strictly enforced."""
        guard = QuotaGuard()

        # Use up to near hard cap
        for _ in range(2999):
            guard.record_write(1)

        # Next write should be rejected
        allowed, reason = guard.check_can_write(1)
        assert not allowed


class TestQuotaIntegration:
    """Integration tests for quota system."""

    def test_full_daily_budget_under_cap(self, temp_db):
        """Test that expected daily budget stays under cap."""
        guard = QuotaGuard()

        # Simulate full day: 300 entries + 300 closes
        writes = 0

        # Entry writes: trade create + open_positions update
        writes += 300 * 2  # 600

        # Close writes: trade close + open_positions + learning + metrics
        writes += 300 * 4  # 1200

        # Dashboard writes: ~1 per 5 min (288 max per day)
        writes += 288  # 288

        # Quota publishes: ~1 per 15 min (96 max per day)
        writes += 96  # 96

        # Reserve
        writes += 100  # 100

        # Total: 2,284 (should be well under 2,500 target)
        for _ in range(writes):
            guard.record_write(1)

        status = guard.get_status()
        assert status['writes_attempted'] <= 2500
        assert status['state'] in ('normal', 'warning')

    def test_quota_overflow_scenario(self, temp_db):
        """Test system behavior during quota overflow."""
        guard = QuotaGuard()

        # Manually push to critical
        for _ in range(2800):
            guard.record_write(1)

        status = guard.get_status()
        assert status['state'] == 'critical'

        # At critical, entry should be blocked
        allowed, _ = guard.check_entry_write_reserve(open_count=5)
        assert not allowed
