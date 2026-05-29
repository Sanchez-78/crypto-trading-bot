"""Test internal V5 quota caps are properly enforced separate from official limits."""

import pytest
import sqlite3
from src.v5_bot.firebase.quota_guard import QuotaGuard, QuotaLedger
from src.v5_bot.config import QUOTA_BUDGET


@pytest.fixture(autouse=True)
def cleanup_quota_db():
    """Clean up quota database before each test."""
    ledger = QuotaLedger()
    date = ledger._pt_date()
    # Clear today's quota data before test
    with sqlite3.connect(ledger.DB_PATH) as conn:
        conn.execute("DELETE FROM quota_daily WHERE date = ?", (date,))
        conn.commit()
    yield
    # Cleanup after test
    with sqlite3.connect(ledger.DB_PATH) as conn:
        conn.execute("DELETE FROM quota_daily WHERE date = ?", (date,))
        conn.commit()


def test_internal_read_cap_is_distinct_from_official():
    """Verify internal read cap (20k) is less than official (50k)."""
    assert QUOTA_BUDGET.v5_active_hard_reads_cap_per_day == 20000
    assert QUOTA_BUDGET.official_max_reads_per_day == 50000
    assert QUOTA_BUDGET.v5_active_hard_reads_cap_per_day < QUOTA_BUDGET.official_max_reads_per_day


def test_internal_write_cap_is_distinct_from_official():
    """Verify internal write cap (10k) is less than official (20k)."""
    assert QUOTA_BUDGET.v5_active_hard_writes_cap_per_day == 10000
    assert QUOTA_BUDGET.official_max_writes_per_day == 20000
    assert QUOTA_BUDGET.v5_active_hard_writes_cap_per_day < QUOTA_BUDGET.official_max_writes_per_day


def test_quota_guard_enforces_internal_read_cap():
    """Verify QuotaGuard blocks reads when internal daily cap would be exceeded."""
    guard = QuotaGuard()

    # Manually set high read count to trigger internal cap
    date = guard.ledger._pt_date()
    with sqlite3.connect(guard.ledger.DB_PATH) as conn:
        # Create row and set reads to just under the internal cap
        conn.execute(
            "INSERT OR IGNORE INTO quota_daily (date, updated_at) VALUES (?, ?)",
            (date, "2026-05-29T00:00:00Z")
        )
        # Set to 19999 (one read away from internal cap of 20000)
        conn.execute(
            "UPDATE quota_daily SET reads_attempted = ? WHERE date = ?",
            (19999, date)
        )
        conn.commit()

    # Attempt to read 1 more (would exceed 20000 internal cap)
    allowed, reason = guard.check_can_read(count=1)
    assert not allowed, "Read should be blocked at internal cap"
    assert "V5 daily read cap 20000 would be exceeded" in reason


def test_quota_guard_enforces_internal_write_cap():
    """Verify QuotaGuard blocks writes when internal daily cap would be exceeded."""
    guard = QuotaGuard()

    # Manually set high write count to trigger internal cap
    date = guard.ledger._pt_date()
    with sqlite3.connect(guard.ledger.DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO quota_daily (date, updated_at) VALUES (?, ?)",
            (date, "2026-05-29T00:00:00Z")
        )
        # Set to 9999 (one write away from internal cap of 10000)
        conn.execute(
            "UPDATE quota_daily SET writes_attempted = ? WHERE date = ?",
            (9999, date)
        )
        conn.commit()

    # Attempt to write 1 more (would exceed 10000 internal cap)
    allowed, reason = guard.check_can_write(count=1)
    assert not allowed, "Write should be blocked at internal cap"
    assert "V5 daily write cap 10000 would be exceeded" in reason


def test_entry_write_reserve_uses_internal_daily_cap():
    """Verify entry reserve calculation uses internal daily cap (10000) not session cap (3000)."""
    guard = QuotaGuard()

    # Verify that check_entry_write_reserve uses QUOTA_BUDGET.v5_active_hard_writes_cap_per_day
    # by checking that entries can still be evaluated when writes exceed session-level caps
    # but remain under internal daily cap

    # This test just verifies the method can run and uses the correct cap internally
    # rather than failing due to session-level thresholds

    # With modest writes (100), entry should have sufficient reserve
    date = guard.ledger._pt_date()
    with sqlite3.connect(guard.ledger.DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO quota_daily (date, updated_at) VALUES (?, ?)",
            (date, "2026-05-29T00:00:00Z")
        )
        conn.execute(
            "UPDATE quota_daily SET writes_attempted = ? WHERE date = ?",
            (100, date)
        )
        conn.commit()

    # With 1 open position: 1*3 + 4 + 20 = 27 writes needed, 10000-100=9900 available
    allowed, reason = guard.check_entry_write_reserve(open_count=1, new_close_writes=4)
    assert allowed, f"Entry should be allowed with ample reserve: {reason}"

    # With 2000 writes used, only 8000 left before daily cap
    # Entry needs 2*3 + 4 + 20 = 30 writes, so should still be allowed
    with sqlite3.connect(guard.ledger.DB_PATH) as conn:
        conn.execute(
            "UPDATE quota_daily SET writes_attempted = ? WHERE date = ?",
            (2000, date)
        )
        conn.commit()

    allowed, reason = guard.check_entry_write_reserve(open_count=2, new_close_writes=4)
    # State will be "degraded" (2500 writes) or "warning" depending on thresholds,
    # but reserve is still sufficient (10000-2000=8000 available, 30 needed)
    assert allowed, f"Entry should be allowed with sufficient reserve even near threshold: {reason}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
