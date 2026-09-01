"""Regression test for the 2026-09-01 log-window-truncation fix in
emergency_health_monitor.py.

Root cause (live-confirmed via direct measurement on the Hetzner service):
every detector below used to additionally slice its own small fixed tail
(`last_logs[-50:]`/`[-100:]`/`[-200:]`) on top of whatever the caller
(bot2/main.py's `_get_recent_logs`, itself a fixed "-n 500" journalctl line
count) already returned. Measured live throughput was ~147 log lines/second,
i.e. ~4,400-4,600 lines between two consecutive periodic markers (the check
interval is 60s; markers like [V5_BRIDGE_DASHBOARD_METRICS] fire every
~30s). A 500-line fetch covered only ~3.4s of real history, and a further
[-50:] slice inside a detector covered under half a second -- structurally
almost-never containing the periodic marker the detector was looking for.
This is the most likely root cause of the RECON_FAILURE/DASHBOARD_ZERO/
LEARNING_STALL false positives observed and individually dismissed as noise
across many monitoring cycles (see _workspace/50_... and the cycle-196 log
in _workspace/monitoring_progress.json).

Fix: bot2/main.py's `_get_recent_logs` now fetches by TIME (`--since "90
seconds ago"`) instead of a fixed line count, and every detector below had
its own redundant fixed-size tail slice removed -- each now scans the full
(already time-scoped) `last_logs` it is given.

These tests prove the fix directly: a marker placed BEHIND more padding
lines than the OLD truncation window would have allowed (i.e. it would have
been invisible to the pre-fix `[-50:]`/`[-100:]`/`[-200:]` slice) must still
be found by the post-fix detector.
"""
from src.services import emergency_health_monitor as ehm


def _reset_state():
    ehm._monitor_state["last_recon_check"] = 0.0
    ehm._monitor_state["recon_failures"] = 0
    ehm._monitor_state["last_dashboard_metrics"] = {}
    ehm._monitor_state["last_learning_update"] = 0.0
    ehm._monitor_state["learning_stall_count"] = 0
    ehm._monitor_state["last_entry_rate"] = 0
    ehm._monitor_state["entry_stall_count"] = 0


def _padding(n):
    """n unrelated, marker-free log lines -- larger than every old fixed
    tail-slice size used in this file (50/100/200)."""
    return [f"unrelated log line {i}" for i in range(n)]


def test_recon_ok_marker_found_beyond_old_50_line_window():
    """The marker sits toward the FRONT of the batch (as it would in the
    real bug: logged first, then hundreds of other lines logged after it
    before the next health check fetched "the last N lines") -- an
    end-anchored [-50:] slice discards the front, not the tail, so this is
    the layout that actually distinguishes the fix from the bug."""
    _reset_state()
    logs = ["[V10.13x.1 RECON] counts_ok=True status=OK"] + _padding(300)
    is_failure, reason = ehm.detect_recon_failure(logs)
    assert is_failure is False, (
        f"RECON OK marker sits 300 lines deep -- the old [-50:] slice would "
        f"have missed it and reported a false 'not found' failure. Got: {reason}"
    )
    assert reason == "RECON OK"


def test_dashboard_metrics_marker_found_beyond_old_50_line_window():
    _reset_state()
    logs = [
        "[V5_BRIDGE_DASHBOARD_METRICS] closed_today=5 paper_exits_1h=5 "
        "learning_updates=5 open=2 quota_state=normal source=paper_metrics"
    ] + _padding(300)
    is_zero, reason = ehm.detect_dashboard_zero(logs, current_time=1000.0)
    assert is_zero is False, (
        f"dashboard-metrics marker sits 300 lines deep -- the old [-50:] "
        f"slice would have missed it and reported a false DASHBOARD_ZERO. "
        f"Got: {reason}"
    )
    assert reason == "Dashboard metrics flowing"
    assert ehm._monitor_state["last_dashboard_metrics"]["timestamp"] == 1000.0


def test_learning_update_marker_found_beyond_old_100_line_window():
    _reset_state()
    logs = ["[V5_BRIDGE_LEARNING_UPDATE] segment=A_STRICT_TAKE n=42"] + _padding(300)
    is_stalled, reason = ehm.detect_learning_stall(logs, current_time=1000.0)
    assert is_stalled is False, (
        f"learning-update marker sits 300 lines deep -- the old [-100:] "
        f"slice would have missed it and reported a false LEARNING_STALL. "
        f"Got: {reason}"
    )
    assert reason == "Learning active"


def test_paper_entry_marker_found_beyond_old_200_line_window():
    _reset_state()
    logs = [
        "[PAPER_ENTRY] symbol=BTCUSDT side=BUY price=50000.00000000 "
        "size_usd=10.00 ev=0.0300 score=0.312 reason=A_STRICT_TAKE"
    ] + _padding(300)
    is_stalled, reason = ehm.detect_entry_stall(logs, current_time=1000.0)
    assert is_stalled is False, (
        f"[PAPER_ENTRY] marker sits 300 lines deep -- the old [-200:] slice "
        f"would have missed it and reported a false ENTRY_STALL. Got: {reason}"
    )
    assert reason == "Entries flowing"


def test_traceback_found_beyond_old_100_line_window():
    _reset_state()
    logs = [
        "Traceback (most recent call last):",
        '  File "bot2/main.py", line 42, in run',
        "ZeroDivisionError: division by zero",
    ] + _padding(300)
    has_crash, crash_lines = ehm.detect_crashes(logs)
    assert has_crash is True, (
        "a real Traceback sits at the front, 300 unrelated lines before the "
        "end -- the old [-100:] slice (from the END of the list) would have "
        "missed it entirely and silently hidden a real crash"
    )
    assert any("Traceback" in line for line in crash_lines)


def test_outbox_pending_marker_found_beyond_old_100_line_window():
    logs = ["[V5_BRIDGE_OUTBOX_FLUSH] pending=12 flushed=3"] + _padding(300)
    is_stuck, pending, reason = ehm.detect_outbox_stuck(logs)
    assert pending == 12, (
        f"outbox-flush marker sits 300 lines deep -- the old [-100:] slice "
        f"would have missed it and reported pending=0. Got pending={pending}"
    )
    assert is_stuck is True


def test_quota_marker_found_beyond_old_50_line_window():
    logs = ["[V5_BRIDGE_QUOTA_STATE] reads=100/50000 writes=18500/20000"] + _padding(300)
    approaching, quota, reason = ehm.detect_quota_approaching(logs)
    assert quota["writes"] == 18500, (
        f"quota-state marker sits 300 lines deep -- the old [-50:] slice "
        f"would have missed it and reported writes=0. Got: {quota}"
    )
    assert approaching is True
