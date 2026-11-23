# -*- coding: utf-8 -*-
"""REJECT_ECON_BAD_ENTRY detail-output rate limit (2026-11-23, observability only).

The decision and every counter/diagnostic must be identical with the flag off and on; only the
per-reject [ECON_BAD_ENTRY_RETURN_TRACE] line and the print may be reduced, never the
[ECON_BAD_READY_BUT_REJECTED] invariant.
"""
import ast
import inspect
import logging
import threading

import pytest

from src.services import realtime_decision_engine as rde

FLAG = rde.ECON_BAD_REJECT_LOG_LIMIT_FLAG
REASON = "weak_ev (ev=0.0300<0.045)"
OVERRIDE = {"checked": True, "allowed": False, "reason": "recovery_blocked:probe_ev_too_low",
            "kind": None, "size_mult": None, "meta": {}}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(rde, "_ECON_BAD_REJECT_LOG_LIMITER", rde.EconBadRejectLogLimiter(clock=c))
    return c


@pytest.fixture
def calls(monkeypatch):
    """Record every side effect of the reject path; the real trace function is kept."""
    rec = {"near_miss": 0, "track_blocked": [], "flush": 0, "emit": []}
    monkeypatch.setattr(rde, "_update_econ_bad_near_miss",
                        lambda **k: rec.__setitem__("near_miss", rec["near_miss"] + 1))
    monkeypatch.setattr(rde, "track_blocked", lambda reason: rec["track_blocked"].append(reason))
    monkeypatch.setattr(rde, "_maybe_flush_econ_bad_diagnostics",
                        lambda *a, **k: rec.__setitem__("flush", rec["flush"] + 1))
    monkeypatch.setattr(rde, "_maybe_emit_econ_bad_diag_from_reject",
                        lambda source="rde_reject": rec["emit"].append(source))
    monkeypatch.setattr(rde, "get_econ_bad_diagnostics_snapshot",
                        lambda: {"pf": 0.5, "econ_status": "BAD", "probe_ready": False, "probe_block_reason": "x"})
    return rec


def _reject(n, reason=REASON, override=OVERRIDE):
    for _ in range(n):
        out = rde._econ_bad_reject_outputs(
            signal={"symbol": "BTCUSDT"}, ctx={}, sym="BTCUSDT", regime="BULL_TREND", ev=0.03, score=0.2,
            win_prob=0.5, coherence=0.6, auditor_factor=0.8, reason=reason, override=dict(override))
        assert out is None


def _lines(caplog, marker):
    return [r for r in caplog.records if marker in r.getMessage()]


# ── default off: byte-for-byte the old output ─────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [None, "", "false", "0", "no", "off", "maybe", "TRUE ish"])
def test_flag_off_or_invalid_keeps_every_detail_line(monkeypatch, clock, calls, caplog, capsys, value):
    if value is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, value)
    with caplog.at_level(logging.WARNING):
        _reject(20)
    assert len(_lines(caplog, "[ECON_BAD_ENTRY_RETURN_TRACE]")) == 20
    assert capsys.readouterr().out.count("decision=REJECT_ECON_BAD_ENTRY") == 20
    assert not _lines(caplog, "[ECON_BAD_REJECT_LOG_SUMMARY]")


# ── flag on: same decisions and counters, fewer detail lines ──────────────────────────────────────

@pytest.mark.parametrize("value", ["true", "1", "yes", "on", " TRUE "])
def test_flag_on_limits_details_but_not_counters(monkeypatch, clock, calls, caplog, capsys, value):
    monkeypatch.setenv(FLAG, value)
    with caplog.at_level(logging.WARNING):
        _reject(50)
    assert len(_lines(caplog, "[ECON_BAD_ENTRY_RETURN_TRACE]")) == 1
    assert capsys.readouterr().out.count("decision=REJECT_ECON_BAD_ENTRY") == 1
    assert calls["track_blocked"] == ["ECON_BAD_ENTRY"] * 50
    assert calls["near_miss"] == 50 and calls["flush"] == 50 and calls["emit"] == ["rde_reject"] * 50


def test_off_and_on_produce_identical_side_effects(monkeypatch, clock, calls):
    reasons = [REASON, "weak_p (p=0.500<0.54)", REASON, "forbidden_tag_x", REASON] * 6
    monkeypatch.delenv(FLAG, raising=False)
    for r in reasons:
        _reject(1, reason=r)
    off = {k: (list(v) if isinstance(v, list) else v) for k, v in calls.items()}
    for k in calls:
        calls[k] = [] if isinstance(calls[k], list) else 0
    monkeypatch.setenv(FLAG, "true")
    for r in reasons:
        _reject(1, reason=r)
    assert calls == off


def test_window_boundary_writes_exact_summary_and_resets(monkeypatch, clock, calls, caplog, capsys):
    monkeypatch.setenv(FLAG, "true")
    with caplog.at_level(logging.WARNING):
        _reject(7)
        _reject(3, reason="weak_p (p=0.5<0.54)")
        clock.t += 59.9
        _reject(1)                                   # still inside the window: no summary
        assert not _lines(caplog, "[ECON_BAD_REJECT_LOG_SUMMARY]")
        clock.t += 0.2                               # window over
        _reject(1)
    summaries = _lines(caplog, "[ECON_BAD_REJECT_LOG_SUMMARY]")
    assert len(summaries) == 1
    text = summaries[0].getMessage()
    assert "seq=1 " in text
    assert "window_rejects=11 window_suppressed=9" in text
    assert "total_rejects=11 total_suppressed=9" in text
    assert "weak_ev=8/7" in text and "weak_p=3/2" in text
    # first reject of the new window is written in full again
    assert len(_lines(caplog, "[ECON_BAD_ENTRY_RETURN_TRACE]")) == 3
    assert capsys.readouterr().out.count("decision=REJECT_ECON_BAD_ENTRY") == 3


def test_new_category_is_written_immediately(monkeypatch, clock, calls, caplog):
    monkeypatch.setenv(FLAG, "true")
    with caplog.at_level(logging.WARNING):
        for r in [REASON, REASON, "weak_score (score=0.1<0.22)", REASON, "weak_coh (coh=0.5<0.58)"]:
            _reject(1, reason=r)
    reasons = [r.getMessage().split("entry_reason=")[1].split(" ")[0]
               for r in _lines(caplog, "[ECON_BAD_ENTRY_RETURN_TRACE]")]
    assert reasons == ["weak_ev", "weak_score", "weak_coh"]


def test_category_cardinality_is_bounded():
    lim = rde.EconBadRejectLogLimiter(max_categories=4, clock=Clock())
    emitted = [lim.observe(f"tag_{chr(97 + i)}{chr(97 + i)} free text {i}")[0] for i in range(26)]
    snap = lim.snapshot()
    assert len(snap) == 5 and "other" in snap      # 4 named + overflow bucket
    assert snap["other"] == (22, 21)
    assert sum(emitted) == 5
    assert rde._econ_bad_reject_category("weak_ev (ev=1)") == "weak_ev"
    assert rde._econ_bad_reject_category(None) == "unknown" and rde._econ_bad_reject_category("(x)") == "unknown"
    assert len(rde._econ_bad_reject_category("a" * 500)) == 40


def test_observe_is_serialized_by_its_lock():
    """Deterministic: while one observe() is inside the critical section, another cannot finish."""
    inside, release = threading.Event(), threading.Event()
    first = [True]

    def clock():
        if first[0]:
            first[0] = False
            inside.set()
            release.wait(5)  # hold the critical section
        return 1000.0

    lim = rde.EconBadRejectLogLimiter(clock=clock)
    a = threading.Thread(target=lambda: lim.observe(REASON))
    a.start()
    assert inside.wait(5)
    b_done = threading.Event()
    b = threading.Thread(target=lambda: (lim.observe(REASON), b_done.set()))
    b.start()
    assert not b_done.wait(0.3)   # blocked behind A
    release.set()
    a.join(5)
    b.join(5)
    assert b_done.is_set() and lim.snapshot() == {"weak_ev": (2, 1)}


def test_concurrent_rejects_are_counted_exactly():
    import sys
    import time as _t
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # force frequent thread switches so a missing lock shows up
    try:
        ticks = iter(range(10 ** 9))
        clock = lambda: 1000.0 + next(ticks) * 1e-9  # monotonic, stays inside one window
        lim = rde.EconBadRejectLogLimiter(clock=clock)
        emitted = []
        lock = threading.Lock()
        start = threading.Barrier(8)

        def worker():
            start.wait()
            local = []
            for i in range(3000):
                local.append(lim.observe(REASON if i % 2 else "weak_p (p=0)")[0])
                if i % 97 == 0:
                    _t.sleep(0)
            with lock:
                emitted.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old)
    assert lim.snapshot() == {"weak_ev": (12000, 11999), "weak_p": (12000, 11999)}
    assert sum(emitted) == 2


def test_ready_but_rejected_invariant_stays_visible_when_detail_is_suppressed(monkeypatch, clock, calls, caplog):
    monkeypatch.setenv(FLAG, "true")
    allowed = {**OVERRIDE, "allowed": True, "reason": "recovery_allowed"}
    with caplog.at_level(logging.WARNING):
        _reject(5, override=allowed)
    assert len(_lines(caplog, "[ECON_BAD_ENTRY_RETURN_TRACE]")) == 1
    assert len(_lines(caplog, "[ECON_BAD_READY_BUT_REJECTED]")) == 5


def test_internal_or_logger_errors_never_hide_details_or_raise(monkeypatch, clock, calls, caplog, capsys):
    monkeypatch.setenv(FLAG, "true")

    class Broken:
        def observe(self, reason):
            raise RuntimeError("boom")

    assert rde._econ_bad_should_emit_reject_detail(REASON, limiter=Broken()) is True

    class BrokenLog:
        def warning(self, *a, **k):
            raise OSError("log down")

    monkeypatch.setattr(rde, "log", BrokenLog())
    lim = rde.EconBadRejectLogLimiter(clock=clock)
    lim.observe(REASON)
    clock.t += 61
    assert rde._econ_bad_should_emit_reject_detail(REASON, limiter=lim) is True  # summary log failed, no raise


class FlakyLog:
    """Fails the next `fail` summary writes; records the summaries that were written."""

    def __init__(self, fail):
        self.fail = fail
        self.written = []

    def warning(self, msg, *args, **kwargs):
        text = msg % args if args else msg
        if text.startswith("[ECON_BAD_REJECT_LOG_SUMMARY]"):
            if self.fail > 0:
                self.fail -= 1
                raise OSError("journal unavailable")
            self.written.append(text)

    def error(self, *a, **k):
        pass


def _field(line, name):
    return int(line.split(f"{name}=")[1].split(" ")[0])


def test_failed_summary_write_loses_no_counts(monkeypatch, clock):
    """review 2026-11-23 R1: a lost summary line is visible (seq gap) and its counts are in the next one."""
    monkeypatch.setenv(FLAG, "true")
    flaky = FlakyLog(fail=1)
    monkeypatch.setattr(rde, "log", flaky)
    emit = rde._econ_bad_should_emit_reject_detail
    assert [emit(REASON) for _ in range(3)] == [True, False, False]          # window 1: 3 rejects
    clock.t += 61
    assert emit(REASON) is True                                              # summary seq=1 write fails
    assert flaky.written == []
    emit(REASON), emit(REASON)                                               # window 2: 3 rejects
    clock.t += 61
    emit(REASON)                                                             # summary seq=2 arrives
    line = flaky.written[0]
    assert _field(line, "seq") == 2                                          # gap: seq=1 never arrived
    assert _field(line, "window_rejects") == 3 and _field(line, "window_suppressed") == 2
    assert _field(line, "total_rejects") == 6 and _field(line, "total_suppressed") == 4  # includes window 1
    assert "weak_ev=6/4" in line


def test_streamhandler_swallowing_write_errors_loses_no_counts(clock):
    """review 2026-11-23 R2: the production StreamHandler swallows stream errors, so a returning
    log.warning() proves nothing. The cumulative totals must still carry the lost window."""
    import io

    class FailingStream:
        def write(self, _text):
            raise OSError("journal stream unavailable")

        def flush(self):
            pass

    logger = logging.getLogger("test_econ_bad_streamhandler")
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    handler = logging.StreamHandler(FailingStream())
    logger.addHandler(handler)
    previous = logging.raiseExceptions
    logging.raiseExceptions = False
    original_log = rde.log
    rde.log = logger
    try:
        env = {FLAG: "true"}
        emit = rde._econ_bad_should_emit_reject_detail
        assert [emit(REASON, env=env) for _ in range(3)] == [True, False, False]
        clock.t += 61
        assert emit(REASON, env=env) is True                                 # seq=1 swallowed by the handler
        sink = io.StringIO()
        handler.setStream(sink)
        clock.t += 61
        emit(REASON, env=env)                                                # seq=2 reaches the stream
    finally:
        rde.log = original_log
        logging.raiseExceptions = previous
        logger.removeHandler(handler)
    written = sink.getvalue().strip().splitlines()
    assert len(written) == 1
    assert _field(written[0], "seq") == 2
    assert _field(written[0], "total_rejects") == 4 and _field(written[0], "total_suppressed") == 2
    assert _field(written[0], "window_rejects") == 1


def test_repeated_summary_failures_stay_bounded_and_lose_nothing(monkeypatch, clock):
    monkeypatch.setenv(FLAG, "true")
    flaky = FlakyLog(fail=10)
    monkeypatch.setattr(rde, "log", flaky)
    emit = rde._econ_bad_should_emit_reject_detail
    total = 0
    for w in range(11):                                  # 10 failed summaries, then 1 success
        for i in range(25):                              # 25 categories per window, different every window
            emit(f"{chr(97 + w)}{chr(97 + i)}_cat (x={w})")
            total += 1
        clock.t += 61
        totals = rde._ECON_BAD_REJECT_LOG_LIMITER.totals_snapshot()
        assert len(totals) <= 17                         # 16 named + "other": memory bounded
    emit(REASON)                                         # boundary after window 11 -> written
    line = flaky.written[0]
    assert len(flaky.written) == 1 and _field(line, "seq") == 11
    assert _field(line, "total_rejects") == total
    assert _field(line, "window_rejects") == 25


def test_logger_failure_never_changes_the_reject_path(monkeypatch, clock, calls):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setattr(rde, "log", FlakyLog(fail=10 ** 6))
    for _ in range(3):
        _reject(10)
        clock.t += 61
    assert calls["track_blocked"] == ["ECON_BAD_ENTRY"] * 30
    assert calls["near_miss"] == 30 and calls["flush"] == 30 and len(calls["emit"]) == 30


def test_consecutive_summaries_difference_to_window_counts():
    """total(seq=n) - total(seq=n-1) == window(seq=n): lines can be checked against each other."""
    clock = Clock()
    lim = rde.EconBadRejectLogLimiter(clock=clock)
    lines = []
    for n in (4, 2, 7):
        for _ in range(n):
            _, s = lim.observe(REASON)
            if s:
                lines.append(s)
        clock.t += 61
    _, s = lim.observe(REASON)
    lines.append(s)
    assert [_field(l, "seq") for l in lines] == [1, 2, 3]
    totals = [_field(l, "total_rejects") for l in lines]
    windows = [_field(l, "window_rejects") for l in lines]
    assert windows == [4, 2, 7] and totals == [4, 6, 13]


def test_recovery_probe_trace_is_not_limited(monkeypatch, clock, calls, caplog):
    monkeypatch.setenv(FLAG, "true")
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            rde._trace_econ_bad_entry_return(signal={"symbol": "BTCUSDT"}, ctx={}, entry_reason=REASON,
                                             override=dict(OVERRIDE), final_decision="TAKE")
    assert len(_lines(caplog, "[ECON_BAD_ENTRY_RETURN_TRACE]")) == 5


def test_evaluate_signal_reject_branch_delegates_and_returns_none():
    src = inspect.getsource(rde)
    tree = ast.parse(src)
    calls_ = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and getattr(n.func, "id", None) == "_econ_bad_reject_outputs"]
    assert len(calls_) == 1
    branch = src[src.index("_econ_bad_reject_outputs(\n                signal=signal"):]
    assert branch.split(")", 1)[1].lstrip().startswith("return None")
    helper = inspect.getsource(rde._econ_bad_reject_outputs).split('"""', 2)[2]  # body after the docstring
    order = ["_update_econ_bad_near_miss(", "_econ_bad_should_emit_reject_detail(", "_trace_econ_bad_entry_return(",
             'track_blocked(reason="ECON_BAD_ENTRY")', "_maybe_flush_econ_bad_diagnostics()",
             '_maybe_emit_econ_bad_diag_from_reject(source="rde_reject")']
    positions = [helper.index(s) for s in order]
    assert positions == sorted(positions)
    # track_blocked is unconditional (not inside the emit_detail if)
    assert "if emit_detail:\n        track_blocked" not in helper
