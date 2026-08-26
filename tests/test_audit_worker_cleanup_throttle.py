"""Tests for the audit_worker.py cleanup-query quota-burn fixes.

2026-08-14 fix: _sync_batch_write()'s cleanup query (db.collection("audits")
.order_by(...).offset(MAX_AUDITS).limit(20).get()) ran on EVERY batch flush --
as often as every BATCH_INTERVAL (3s). Throttled to run at most once per
CLEANUP_INTERVAL_S, tracked via a per-instance _last_cleanup_ts, independent
of how often _sync_batch_write() itself is called
(_workspace/26_quota_burn_found_audit_worker_offset.md).

2026-08-26 fix: the throttle above only reduced call FREQUENCY -- the
.offset(MAX_AUDITS) query itself still billed Firestore for 50 skipped
documents on every call regardless of whether anything needed deleting, and
its fixed .limit(20) never kept pace with the collection's write rate (the
"audits" collection was found to have grown to ~92,684 documents live,
despite MAX_AUDITS=50). Replaced with an aggregate .count() (1 read) to size
the actual excess, then an ascending-order query that only reads the
documents it is about to delete, with a higher CLEANUP_BATCH_LIMIT to drain
the backlog faster (_workspace/47_audit_collection_backlog_and_offset_free_cleanup.md).
"""
import time
from unittest.mock import MagicMock

import pytest

from src.services import audit_worker


def _make_fake_db(total_docs: int = 0):
    """A minimal fake Firestore client: batch()/collection() chain that
    counts how many times the cleanup count() query is invoked.

    total_docs controls the simulated collection size for the aggregate
    .count().get() call. Defaults to 0 (well under MAX_AUDITS), so `excess`
    is always negative and no delete query is attempted -- isolates the
    cleanup-throttle timing behavior from the deletion path itself, matching
    the original tests' intent."""
    db = MagicMock()
    cleanup_count_calls = []

    fake_collection = MagicMock()

    fake_count_result = MagicMock()
    fake_count_result.__getitem__.return_value = [MagicMock(value=total_docs)]

    def _count_get():
        cleanup_count_calls.append(1)
        return fake_count_result

    fake_collection.count.return_value.get.side_effect = _count_get

    fake_query = MagicMock()
    fake_query.order_by.return_value = fake_query
    fake_query.limit.return_value = fake_query
    fake_query.get.return_value = []  # no docs returned by the delete query

    fake_collection.order_by.return_value = fake_query

    db.collection.return_value = fake_collection
    db.batch.return_value = MagicMock()
    return db, cleanup_count_calls


def test_cleanup_runs_on_first_flush():
    worker = audit_worker.AuditWorker()
    db, cleanup_calls = _make_fake_db()
    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])
    assert len(cleanup_calls) == 1


def test_cleanup_does_not_rerun_within_the_throttle_window():
    worker = audit_worker.AuditWorker()
    db, cleanup_calls = _make_fake_db()
    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])
    # Immediately flush again -- well within CLEANUP_INTERVAL_S (300s).
    worker._sync_batch_write(db, [{"reason": "y", "timestamp": time.time()}])
    worker._sync_batch_write(db, [{"reason": "z", "timestamp": time.time()}])
    assert len(cleanup_calls) == 1, (
        "cleanup ran more than once within the throttle window -- this is "
        "the exact regression (every-3s offset() scan) this fix closes"
    )


def test_cleanup_reruns_after_the_throttle_window_elapses(monkeypatch):
    worker = audit_worker.AuditWorker()
    db, cleanup_calls = _make_fake_db()
    fake_now = [1_000_000.0]
    monkeypatch.setattr(audit_worker.time, "time", lambda: fake_now[0])

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": fake_now[0]}])
    assert len(cleanup_calls) == 1

    fake_now[0] += audit_worker.CLEANUP_INTERVAL_S - 1  # still inside the window
    worker._sync_batch_write(db, [{"reason": "y", "timestamp": fake_now[0]}])
    assert len(cleanup_calls) == 1

    fake_now[0] += 2  # now past CLEANUP_INTERVAL_S since the first cleanup
    worker._sync_batch_write(db, [{"reason": "z", "timestamp": fake_now[0]}])
    assert len(cleanup_calls) == 2


def test_batch_commit_still_happens_every_flush_regardless_of_throttle():
    """The throttle must only gate the cleanup query -- the actual audit
    writes (batch.set/commit) must still happen on every flush."""
    worker = audit_worker.AuditWorker()
    db, _ = _make_fake_db()
    for i in range(3):
        worker._sync_batch_write(db, [{"reason": f"r{i}", "timestamp": time.time()}])
    assert db.batch.call_count == 3, "one write batch per flush call expected"


def test_cleanup_failure_does_not_break_the_write_batch_or_the_throttle(monkeypatch):
    """A cleanup query exception must be swallowed (pre-existing behavior,
    'cleanup failure is non-critical') and must still advance the throttle
    timestamp so a persistently-failing cleanup can't spin every flush."""
    worker = audit_worker.AuditWorker()
    db, _ = _make_fake_db()
    db.collection.return_value.count.return_value.get.side_effect = RuntimeError("boom")

    # Must not raise.
    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])
    assert worker._last_cleanup_ts > 0, (
        "throttle timestamp must advance even when the cleanup query itself "
        "raises, otherwise a failing cleanup would retry on every flush"
    )


def test_cleanup_deletes_only_the_excess_over_max_audits():
    """When total docs exceed MAX_AUDITS, the delete query must be sized to
    min(excess, CLEANUP_BATCH_LIMIT) via the ascending-order/limit query --
    not an unbounded or fixed-20 delete."""
    worker = audit_worker.AuditWorker()
    total = audit_worker.MAX_AUDITS + audit_worker.CLEANUP_BATCH_LIMIT + 500
    db, _ = _make_fake_db(total_docs=total)

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])

    fake_query = db.collection.return_value.order_by.return_value
    fake_query.limit.assert_called_once_with(audit_worker.CLEANUP_BATCH_LIMIT)


def test_cleanup_skips_delete_query_when_under_max_audits():
    """No delete query should run at all when the collection is already at
    or under MAX_AUDITS -- avoids an unnecessary read even for the (cheap)
    ascending-order query."""
    worker = audit_worker.AuditWorker()
    db, _ = _make_fake_db(total_docs=audit_worker.MAX_AUDITS)

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])

    db.collection.return_value.order_by.assert_not_called()
