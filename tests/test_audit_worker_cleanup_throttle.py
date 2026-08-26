"""Tests for the audit_worker.py cleanup-query quota-burn fixes.

2026-08-14 fix: _sync_batch_write()'s cleanup query (db.collection("audits")
.order_by(...).offset(MAX_AUDITS).limit(20).get()) ran on EVERY batch flush --
as often as every BATCH_INTERVAL (3s). Throttled to run at most once per
CLEANUP_INTERVAL_S, tracked via a per-instance _last_cleanup_ts, independent
of how often _sync_batch_write() itself is called
(_workspace/26_quota_burn_found_audit_worker_offset.md).

2026-08-26 v1 fix: replaced the DESCENDING+offset(50) query (found on review
to delete the 51st-70th NEWEST docs, never the true oldest tail -- the
"audits" collection had grown to ~92,684 documents despite MAX_AUDITS=50)
with an ASCENDING order_by that actually targets the oldest documents,
sized via a per-pass aggregate .count().

2026-08-26 v2 fix (after review): v1's per-pass .count() was REJECTED --
Firestore bills count() at ~1 read per 1,000 index entries matched, so
against the live ~92,684-doc collection it cost ~93 reads/call, not 1,
roughly doubling total read cost during the exact period (a huge backlog)
where it mattered most. v2 caches the count locally, refreshed only once
per CLEANUP_COUNT_REFRESH_S (~hourly), and keeps the local estimate in
sync between refreshes purely from local knowledge (no extra Firestore
reads) -- see _workspace/47_audit_collection_backlog_and_offset_free_cleanup.md.
"""
import time
from unittest.mock import MagicMock

import pytest

from src.services import audit_worker


def _make_fake_db(total_docs: int = 0):
    """A minimal fake Firestore client: batch()/collection() chain that
    separately counts (a) how many times the aggregate .count().get() is
    invoked and (b) how many times the ASCENDING delete query's .get() is
    invoked -- these are now gated by two independent timers
    (CLEANUP_INTERVAL_S vs CLEANUP_COUNT_REFRESH_S) and must be tracked
    separately to test each timer's behavior.

    total_docs controls the simulated collection size for the aggregate
    .count().get() call. Defaults to 0 (well under MAX_AUDITS), so `excess`
    is always negative and the delete query never runs -- isolates the
    cleanup-throttle timing behavior from the deletion path itself."""
    db = MagicMock()
    count_calls = []
    delete_query_calls = []

    fake_collection = MagicMock()

    fake_count_result = MagicMock()
    fake_count_result.__getitem__.return_value = [MagicMock(value=total_docs)]

    def _count_get():
        count_calls.append(1)
        return fake_count_result

    fake_collection.count.return_value.get.side_effect = _count_get

    fake_query = MagicMock()
    fake_query.order_by.return_value = fake_query
    fake_query.limit.return_value = fake_query

    def _delete_get():
        delete_query_calls.append(1)
        return []  # no docs returned -- isolates call-count from delete logic

    fake_query.get.side_effect = _delete_get

    fake_collection.order_by.return_value = fake_query

    db.collection.return_value = fake_collection
    db.batch.return_value = MagicMock()
    return db, count_calls, delete_query_calls


def test_cleanup_runs_on_first_flush():
    worker = audit_worker.AuditWorker()
    db, count_calls, _ = _make_fake_db()
    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])
    assert len(count_calls) == 1


def test_cleanup_does_not_rerun_within_the_throttle_window():
    worker = audit_worker.AuditWorker()
    db, count_calls, _ = _make_fake_db()
    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])
    # Immediately flush again -- well within CLEANUP_INTERVAL_S (300s).
    worker._sync_batch_write(db, [{"reason": "y", "timestamp": time.time()}])
    worker._sync_batch_write(db, [{"reason": "z", "timestamp": time.time()}])
    assert len(count_calls) == 1, (
        "cleanup ran more than once within the throttle window -- this is "
        "the exact regression (every-3s offset() scan) this fix closes"
    )


def test_cleanup_delete_query_reruns_after_the_cleanup_throttle_elapses(monkeypatch):
    """The outer CLEANUP_INTERVAL_S throttle must still re-fire the cleanup
    pass itself (checked via the delete query, which runs on every fired
    pass as long as excess > 0) -- distinct from the much longer
    CLEANUP_COUNT_REFRESH_S timer covered by the next test."""
    worker = audit_worker.AuditWorker()
    total = audit_worker.MAX_AUDITS + 100  # keep excess > 0 throughout
    db, count_calls, delete_calls = _make_fake_db(total_docs=total)
    fake_now = [1_000_000.0]
    monkeypatch.setattr(audit_worker.time, "time", lambda: fake_now[0])

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": fake_now[0]}])
    assert len(delete_calls) == 1

    fake_now[0] += audit_worker.CLEANUP_INTERVAL_S - 1  # still inside the window
    worker._sync_batch_write(db, [{"reason": "y", "timestamp": fake_now[0]}])
    assert len(delete_calls) == 1

    fake_now[0] += 2  # now past CLEANUP_INTERVAL_S since the first cleanup
    worker._sync_batch_write(db, [{"reason": "z", "timestamp": fake_now[0]}])
    assert len(delete_calls) == 2


def test_count_refresh_does_not_rerun_within_its_own_much_longer_window(monkeypatch):
    """CLEANUP_COUNT_REFRESH_S (~hourly) is independent of and much longer
    than CLEANUP_INTERVAL_S (300s) -- the real .count() call must NOT
    re-fire on every cleanup pass, only once per refresh window, even
    though the cleanup pass itself (and its delete query) keeps re-firing."""
    worker = audit_worker.AuditWorker()
    total = audit_worker.MAX_AUDITS + 100
    db, count_calls, delete_calls = _make_fake_db(total_docs=total)
    fake_now = [1_000_000.0]
    monkeypatch.setattr(audit_worker.time, "time", lambda: fake_now[0])

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": fake_now[0]}])
    assert len(count_calls) == 1
    assert len(delete_calls) == 1

    # Advance past several CLEANUP_INTERVAL_S windows but still well within
    # a single CLEANUP_COUNT_REFRESH_S window.
    for _ in range(3):
        fake_now[0] += audit_worker.CLEANUP_INTERVAL_S + 1
        worker._sync_batch_write(db, [{"reason": "y", "timestamp": fake_now[0]}])

    assert len(delete_calls) == 4, "the cleanup pass itself must keep re-firing"
    assert len(count_calls) == 1, (
        "the real count() must NOT be re-called until CLEANUP_COUNT_REFRESH_S "
        "elapses -- re-calling it every pass was the exact defect rejected "
        "on review (each call costs ~93 reads against the live ~92,684-doc "
        "collection, not 1)"
    )

    # Now advance past CLEANUP_COUNT_REFRESH_S too.
    fake_now[0] += audit_worker.CLEANUP_COUNT_REFRESH_S + 1
    worker._sync_batch_write(db, [{"reason": "z", "timestamp": fake_now[0]}])
    assert len(count_calls) == 2


def test_batch_commit_still_happens_every_flush_regardless_of_throttle():
    """The throttle must only gate the cleanup query -- the actual audit
    writes (batch.set/commit) must still happen on every flush."""
    worker = audit_worker.AuditWorker()
    db, _, _ = _make_fake_db()
    for i in range(3):
        worker._sync_batch_write(db, [{"reason": f"r{i}", "timestamp": time.time()}])
    assert db.batch.call_count == 3, "one write batch per flush call expected"


def test_cleanup_failure_does_not_break_the_write_batch_or_the_throttle(monkeypatch):
    """A cleanup query exception must be swallowed (pre-existing behavior,
    'cleanup failure is non-critical') and must still advance the throttle
    timestamp so a persistently-failing cleanup can't spin every flush."""
    worker = audit_worker.AuditWorker()
    db, _, _ = _make_fake_db()
    db.collection.return_value.count.return_value.get.side_effect = RuntimeError("boom")

    # Must not raise.
    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])
    assert worker._last_cleanup_ts > 0, (
        "throttle timestamp must advance even when the cleanup query itself "
        "raises, otherwise a failing cleanup would retry on every flush"
    )


def test_cleanup_failure_is_logged_not_silently_swallowed(monkeypatch, caplog):
    """2026-08-26 (post-review): a bare `except Exception: pass` was exactly
    how the collection reached ~92,684 docs under a 50-doc cap without
    anyone noticing -- a cleanup failure must now be logged."""
    import logging

    worker = audit_worker.AuditWorker()
    db, _, _ = _make_fake_db()
    db.collection.return_value.count.return_value.get.side_effect = RuntimeError("boom")

    with caplog.at_level(logging.WARNING, logger="src.services.audit_worker"):
        worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])

    assert any("AUDIT_CLEANUP_FAILED" in r.message for r in caplog.records)


def test_cleanup_deletes_only_the_excess_over_max_audits():
    """When total docs exceed MAX_AUDITS, the delete query must be sized to
    min(excess, CLEANUP_BATCH_LIMIT) via the ascending-order/limit query --
    not an unbounded or fixed-20 delete."""
    worker = audit_worker.AuditWorker()
    total = audit_worker.MAX_AUDITS + audit_worker.CLEANUP_BATCH_LIMIT + 500
    db, _, _ = _make_fake_db(total_docs=total)

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])

    fake_query = db.collection.return_value.order_by.return_value
    fake_query.limit.assert_called_once_with(audit_worker.CLEANUP_BATCH_LIMIT)
    # Regression check for the review finding: the delete query must be
    # ASCENDING (the true oldest docs), not DESCENDING+offset (which
    # deleted the 51st-70th newest and never reached the real backlog).
    fake_collection = db.collection.return_value
    fake_collection.order_by.assert_called_once_with("timestamp", direction="ASCENDING")


def test_cleanup_skips_delete_query_when_under_max_audits():
    """No delete query should run at all when the collection is already at
    or under MAX_AUDITS -- avoids an unnecessary read even for the (cheap)
    ascending-order query."""
    worker = audit_worker.AuditWorker()
    db, _, _ = _make_fake_db(total_docs=audit_worker.MAX_AUDITS)

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])

    db.collection.return_value.order_by.assert_not_called()


def test_cached_count_decrements_by_the_actual_deleted_count(monkeypatch):
    """2026-08-26 (post-review, reviewer-agent's condition #2): the earlier
    committed suite only ever exercised the delete query with an empty
    result, so `self._cached_audit_count -= deleted` (the line that keeps
    the local estimate in sync between hourly count() refreshes) was
    entirely uncovered -- reviewer-agent instead verified this property via
    an out-of-repo, uncommitted simulation. This locks it in as a real test:
    a delete query that actually returns CLEANUP_BATCH_LIMIT fake documents
    must decrement the cache by exactly that many, not by 0 (an empty-list
    assumption) or by some other count."""
    worker = audit_worker.AuditWorker()
    total = audit_worker.MAX_AUDITS + 500
    db, _, _ = _make_fake_db(total_docs=total)

    fake_docs = [MagicMock() for _ in range(audit_worker.CLEANUP_BATCH_LIMIT)]
    fake_query = db.collection.return_value.order_by.return_value
    fake_query.get.side_effect = None
    fake_query.get.return_value = fake_docs

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])

    assert worker._cached_audit_count == total - audit_worker.CLEANUP_BATCH_LIMIT


def test_cached_count_increments_by_written_items_between_refreshes(monkeypatch):
    """The other half of the local sync: += len(items) on every successful
    write batch, so the estimate doesn't just drift downward from deletes
    while staying blind to new inflow between hourly count() refreshes.

    Note: the increment only applies once the cache is already populated
    (it starts as None, and the very first call's real count() -- which in
    production would already reflect that same call's just-committed batch
    -- establishes the baseline instead)."""
    worker = audit_worker.AuditWorker()
    # Stay under MAX_AUDITS so the delete query never fires -- isolates the
    # increment path from the decrement path tested above.
    db, count_calls, delete_calls = _make_fake_db(total_docs=5)
    fake_now = [1_000_000.0]
    monkeypatch.setattr(audit_worker.time, "time", lambda: fake_now[0])

    worker._sync_batch_write(db, [{"reason": "a"}, {"reason": "b"}])
    assert worker._cached_audit_count == 5  # first call: real count() sets the baseline
    assert len(count_calls) == 1

    # Advance past the (much shorter) cleanup-pass throttle but stay well
    # inside CLEANUP_COUNT_REFRESH_S, so no second real count() call occurs
    # -- the cache must still track this next write correctly on its own.
    fake_now[0] += audit_worker.CLEANUP_INTERVAL_S + 1
    worker._sync_batch_write(db, [{"reason": "c"}])
    assert worker._cached_audit_count == 5 + 1
    assert len(count_calls) == 1
    assert len(delete_calls) == 0, "collection stays well under MAX_AUDITS -- no delete query should ever fire"
