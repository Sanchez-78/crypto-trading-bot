"""Tests for the 2026-08-14 quota-burn fix in audit_worker.py.

Found via the (finally-working, 3rd generation) Firestore read tracer:
_sync_batch_write()'s cleanup query (db.collection("audits").order_by(...)
.offset(MAX_AUDITS).limit(20).get()) ran on EVERY batch flush -- as often
as every BATCH_INTERVAL (3s). Firestore bills an offset() query for every
document it skips server-side, not just the ones returned, so each call
was reading on the order of MAX_AUDITS+20 documents. This was the single
largest READ call site during an active quota-burn window
(_workspace/26_quota_burn_found_audit_worker_offset.md).

Fix: throttle the cleanup to run at most once per CLEANUP_INTERVAL_S,
tracked via a per-instance _last_cleanup_ts, independent of how often
_sync_batch_write() itself is called.
"""
import time
from unittest.mock import MagicMock

import pytest

from src.services import audit_worker


def _make_fake_db():
    """A minimal fake Firestore client: batch()/collection() chain that
    counts how many times the cleanup query itself (.get()) is invoked."""
    db = MagicMock()
    cleanup_get_calls = []

    fake_query = MagicMock()
    fake_query.order_by.return_value = fake_query
    fake_query.offset.return_value = fake_query
    fake_query.limit.return_value = fake_query

    def _get():
        cleanup_get_calls.append(1)
        return []  # no docs to delete -- isolates the cleanup call itself

    fake_query.get.side_effect = _get
    db.collection.return_value = fake_query
    db.batch.return_value = MagicMock()
    return db, cleanup_get_calls


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
    db.collection.return_value.get.side_effect = RuntimeError("boom")

    # Must not raise.
    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])
    assert worker._last_cleanup_ts > 0, (
        "throttle timestamp must advance even when the cleanup query itself "
        "raises, otherwise a failing cleanup would retry on every flush"
    )
