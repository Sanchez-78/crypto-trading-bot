"""Regression test for the 2026-08-31 quota-instrumentation fix in
audit_worker.py.

Root cause (reviewer-agent's follow-up finding from the throttle-fix
review, _workspace/49_...md "known gap"): _sync_batch_write()'s
batch.commit() and the cleanup pass's count()/drain queries never called
_record_write()/_record_read() -- contrast firebase_client.py's own save
functions, which do. This worker's Firestore activity was therefore
invisible to the app's own quota-usage dashboard; the throttle fix itself
could only be verified by re-querying Firestore directly, not via the
app's own quota meter. Now instrumented.
"""
import time
from unittest.mock import MagicMock

import pytest

from src.services import audit_worker
from src.services import firebase_client


def _make_fake_db(total_docs: int = 0, drain_docs: int = 0):
    """Same shape as test_audit_worker_cleanup_throttle.py's fixture, plus
    a knob for how many documents the drain query itself returns (needed
    to test the drain-query read count, which depends on len(snap))."""
    db = MagicMock()

    fake_collection = MagicMock()
    fake_count_result = MagicMock()
    fake_count_result.__getitem__.return_value = [MagicMock(value=total_docs)]
    fake_collection.count.return_value.get.return_value = fake_count_result

    fake_query = MagicMock()
    fake_query.order_by.return_value = fake_query
    fake_query.limit.return_value = fake_query
    fake_query.get.return_value = [MagicMock() for _ in range(drain_docs)]

    fake_collection.order_by.return_value = fake_query
    db.collection.return_value = fake_collection
    db.batch.return_value = MagicMock()
    return db


@pytest.fixture
def record_calls(monkeypatch):
    """Patch firebase_client's module-level counters directly so we can
    assert on real call effects rather than mocking the functions
    themselves -- exercises the same code path production uses."""
    monkeypatch.setattr(firebase_client, "_QUOTA_WRITES", 0)
    monkeypatch.setattr(firebase_client, "_QUOTA_READS", 0)
    yield firebase_client


def test_write_batch_commit_is_recorded(record_calls):
    worker = audit_worker.AuditWorker()
    db = _make_fake_db(total_docs=0)  # stay under MAX_AUDITS, no cleanup writes involved

    worker._sync_batch_write(db, [{"reason": "a"}, {"reason": "b"}, {"reason": "c"}])

    assert firebase_client._QUOTA_WRITES == 3, (
        "batch.commit() wrote 3 documents -- must be recorded via "
        "_record_write(len(items)), not left invisible to the app's own "
        "quota dashboard"
    )


def test_count_refresh_read_is_recorded_approximately(record_calls):
    """Firestore bills count() at ~1 read per 1,000 index entries matched,
    not a flat 1 -- the recorded figure must reflect that approximation,
    not silently under-report it as 1. Uses a total at exactly MAX_AUDITS
    so excess == 0 and the drain query never fires (asserted explicitly),
    isolating the count() read from the drain-query read tested
    separately below."""
    worker = audit_worker.AuditWorker()
    db = _make_fake_db(total_docs=audit_worker.MAX_AUDITS)

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])

    db.collection.return_value.order_by.assert_not_called()  # no drain query
    assert firebase_client._QUOTA_READS == 1  # MAX_AUDITS // 1000 == 0, floored to 1


def test_count_refresh_read_is_at_least_1(record_calls):
    """Even a small collection's count() still costs a real read -- must
    never record 0."""
    worker = audit_worker.AuditWorker()
    db = _make_fake_db(total_docs=5)

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])

    assert firebase_client._QUOTA_READS >= 1


def test_drain_query_read_matches_documents_actually_returned(record_calls):
    worker = audit_worker.AuditWorker()
    total = audit_worker.MAX_AUDITS + 100
    db = _make_fake_db(total_docs=total, drain_docs=17)

    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])

    # Reads recorded = count() approximation + drain query's actual count.
    count_reads = max(1, total // 1000)
    assert firebase_client._QUOTA_READS == count_reads + 17


def test_deletes_are_not_recorded_as_writes(record_calls):
    """The app's own quota dashboard only ever displayed reads/writes,
    never a deletes figure -- deletes must not be folded into the write
    counter (that would misrepresent the write budget, which is what this
    whole instrumentation effort exists to report accurately)."""
    worker = audit_worker.AuditWorker()
    total = audit_worker.MAX_AUDITS + 100
    db = _make_fake_db(total_docs=total, drain_docs=17)

    worker._sync_batch_write(db, [])  # no items -> batch.commit() writes 0

    assert firebase_client._QUOTA_WRITES == 0, (
        "the 17 deleted docs must not be counted as writes"
    )


def test_instrumentation_failure_does_not_block_the_actual_write(monkeypatch):
    """If firebase_client itself can't be imported for some reason, the
    real Firestore write must still happen -- instrumentation is a
    reporting side-effect, never a precondition for the write itself."""
    worker = audit_worker.AuditWorker()
    db = _make_fake_db(total_docs=0)

    import builtins
    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "src.services.firebase_client":
            raise ImportError("simulated import failure")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    # Must not raise.
    worker._sync_batch_write(db, [{"reason": "x", "timestamp": time.time()}])
    db.batch.return_value.commit.assert_called_once()
