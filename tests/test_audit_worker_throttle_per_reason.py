"""Regression test for the 2026-08-28 audit-write-volume fix in
audit_worker.py:_buffer_audit().

Root cause (user question "proc se tak moc zapisuje?" -- why does it
write so much?): live investigation found real trade-lifecycle writes
account for only ~2,400/day (808 closed trades/24h x ~3 writes each), but
the "audits" Redis channel was observed publishing ~2 messages/sec,
continuously, almost entirely reason="REJECTED_CORRELATION"
(execution_engine.py's correlation-shield rejection, which fires on
essentially every candidate correlated with an already-open position --
common, not rare). The old 1.0s per-reason throttle still allowed up to
86,400 writes/day from this single reason alone -- more than the entire
20,000/day Firebase write quota. Raised to 20.0s
(AUDIT_THROTTLE_PER_REASON_S), capping this source at ~4,320 writes/day.
"""
import time

from src.services import audit_worker


def _make_worker():
    return audit_worker.AuditWorker()


def test_first_event_for_a_reason_is_buffered():
    worker = _make_worker()
    worker._buffer_audit({"reason": "REJECTED_CORRELATION", "symbol": "BTCUSDT"})
    assert len(worker._buffer) == 1


def test_second_event_within_throttle_window_is_dropped():
    worker = _make_worker()
    worker._buffer_audit({"reason": "REJECTED_CORRELATION", "symbol": "BTCUSDT"})
    worker._buffer_audit({"reason": "REJECTED_CORRELATION", "symbol": "ETHUSDT"})
    assert len(worker._buffer) == 1, (
        "a second event for the same reason within the throttle window "
        "must be dropped, regardless of which symbol triggered it -- this "
        "is what actually caps the write rate"
    )


def test_event_is_buffered_again_after_the_throttle_window_elapses(monkeypatch):
    worker = _make_worker()
    fake_now = [1_000_000.0]
    monkeypatch.setattr(audit_worker.time, "time", lambda: fake_now[0])

    worker._buffer_audit({"reason": "REJECTED_CORRELATION"})
    assert len(worker._buffer) == 1

    fake_now[0] += audit_worker.AUDIT_THROTTLE_PER_REASON_S - 1
    worker._buffer_audit({"reason": "REJECTED_CORRELATION"})
    assert len(worker._buffer) == 1, "still inside the throttle window"

    fake_now[0] += 2
    worker._buffer_audit({"reason": "REJECTED_CORRELATION"})
    assert len(worker._buffer) == 2, "throttle window elapsed, must buffer again"


def test_different_reasons_are_throttled_independently():
    worker = _make_worker()
    worker._buffer_audit({"reason": "REJECTED_CORRELATION"})
    worker._buffer_audit({"reason": "REJECTED_L2_WALL"})
    assert len(worker._buffer) == 2, (
        "the throttle key is per-reason -- a different reason must not be "
        "blocked by another reason's recent event"
    )


def test_throttle_window_is_20_seconds_not_the_old_1_second():
    """Direct regression against the exact value: the fix's whole point is
    the window being wide enough to matter (86,400/day ceiling at 1s vs
    ~4,320/day at 20s) -- pin the constant so a future edit can't silently
    revert it back to something too permissive."""
    assert audit_worker.AUDIT_THROTTLE_PER_REASON_S == 20.0
