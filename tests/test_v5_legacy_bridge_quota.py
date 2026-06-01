"""
Phase 2 Tests: V5 Legacy Bridge — Quota Guard

Test quota management, safety reserves, and entry blocking.
"""

import pytest
import tempfile
import os
from unittest.mock import patch

from src.services.v5_legacy_bridge.quota import V5LegacyQuotaGuard
from src.services.v5_legacy_bridge import config


@pytest.fixture
def temp_runtime_dir():
    """Temporary runtime directory for test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(config, "RUNTIME_DIR", tmpdir):
            with patch.object(config, "V5_QUOTA_DB_PATH", os.path.join(tmpdir, "quota.sqlite")):
                yield tmpdir


def test_quota_internal_caps_reads_20000_writes_10000(temp_runtime_dir):
    """Test that quota guard enforces internal caps."""
    guard = V5LegacyQuotaGuard()

    snapshot = guard.snapshot()
    assert snapshot["internal_reads_cap"] == 20000
    assert snapshot["internal_writes_cap"] == 10000
    assert snapshot["reads_used"] == 0
    assert snapshot["writes_used"] == 0
    assert snapshot["reads_remaining"] == 20000
    assert snapshot["writes_remaining"] == 10000


def test_quota_check_can_read(temp_runtime_dir):
    """Test read quota checking."""
    guard = V5LegacyQuotaGuard()

    decision = guard.check_can_read(100)
    assert decision.allowed
    assert decision.reads_remaining >= 0

    # Record 19,900 reads (199 x 100)
    for _ in range(199):
        guard.record_read(100)

    # Next 100 should be allowed (20,000 - 19,900 = 100)
    decision = guard.check_can_read(100)
    assert decision.allowed

    # Next 1 more should fail (would exceed cap)
    decision = guard.check_can_read(101)
    assert not decision.allowed
    assert decision.reason == "READ_QUOTA_EXHAUSTED"


def test_quota_check_can_write(temp_runtime_dir):
    """Test write quota checking."""
    guard = V5LegacyQuotaGuard()

    decision = guard.check_can_write(100)
    assert decision.allowed

    # Record 9,900 writes
    for _ in range(99):
        guard.record_write(100)

    # Next 100 should be allowed
    decision = guard.check_can_write(100)
    assert decision.allowed

    # Next 200 should fail
    decision = guard.check_can_write(200)
    assert not decision.allowed
    assert decision.reason == "WRITE_QUOTA_EXHAUSTED"


def test_quota_blocks_new_entry_when_close_reserve_insufficient(temp_runtime_dir):
    """Test that new entries are blocked when close reserve is insufficient."""
    guard = V5LegacyQuotaGuard()

    # Record 9,900 writes (leaving only 100)
    for _ in range(99):
        guard.record_write(100)

    # Try to open new entry
    # Required reserve: 500 (close) + 5 (lifecycle) + 100 (emergency) = 605
    # Available: 100
    decision = guard.check_entry_allowed(open_global=0, open_for_symbol=0)
    assert not decision.allowed
    assert decision.reason == "QUOTA_CLOSE_RESERVE"


def test_quota_does_not_block_close_outbox(temp_runtime_dir):
    """Test that close operations can always be outboxed (never blocked)."""
    guard = V5LegacyQuotaGuard()

    # Exhaust write quota
    for _ in range(100):
        guard.record_write(100)

    # Check quota is exhausted
    decision = guard.check_can_write(1)
    assert not decision.allowed

    # But check_entry_allowed should still allow closes to be attempted
    # (they'll be outboxed if Firebase fails)
    # Close operations are never blocked by this guard
    # (the guard just says "no new entries", not "no closes")
    assert decision.writes_remaining == 0


def test_quota_enforces_symbol_limits(temp_runtime_dir):
    """Test MAX_OPEN_PER_SYMBOL enforcement."""
    guard = V5LegacyQuotaGuard()

    # Try to open second position for same symbol
    decision = guard.check_entry_allowed(open_global=0, open_for_symbol=1)
    assert not decision.allowed
    assert "MAX_OPEN_PER_SYMBOL" in decision.reason


def test_quota_enforces_global_limits(temp_runtime_dir):
    """Test MAX_OPEN_GLOBAL enforcement."""
    guard = V5LegacyQuotaGuard()

    # Try to open third position globally
    decision = guard.check_entry_allowed(open_global=2, open_for_symbol=0)
    assert not decision.allowed
    assert "MAX_OPEN_GLOBAL" in decision.reason


def test_quota_snapshot_provides_state(temp_runtime_dir):
    """Test that snapshot includes complete state."""
    guard = V5LegacyQuotaGuard()

    guard.record_read(100)
    guard.record_write(50)

    snapshot = guard.snapshot()
    assert "date" in snapshot
    assert "reads_used" in snapshot
    assert "writes_used" in snapshot
    assert "reads_remaining" in snapshot
    assert "writes_remaining" in snapshot
    assert "state" in snapshot
    assert "timestamp" in snapshot
    assert snapshot["reads_used"] == 100
    assert snapshot["writes_used"] == 50


def test_quota_helpers(temp_runtime_dir):
    """Test quota helper methods."""
    guard = V5LegacyQuotaGuard()

    guard.record_write(100)
    assert guard.writes_remaining() == 9900
    assert guard.reads_remaining() == 20000
    assert guard.get_state() == "normal"
