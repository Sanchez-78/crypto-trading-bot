"""Regression test for the 2026-08-26 false-positive fix in
emergency_health_monitor.py:detect_crashes().

Root cause: the old check flagged ANY log line containing the bare
substring "Exception"/"ERROR"/"FATAL" as a crash -- false-positived on an
already-handled, logged warning whose message text happens to mention an
exception class name. Confirmed live (2026-08-26 06:05 UTC): a benign
"WebSocket error: WebSocketTimeoutException: ping/pong timed out" warning
fired a CRITICAL CRASH_DETECTED alert, while systemctl showed NRestarts=0
and continuous uptime at the exact same moment -- proof the service never
actually crashed
(_workspace/46_quota_exhaustion_outbox_path_bug_and_false_crash_alerts_cycle123.md).
"""
from src.services.emergency_health_monitor import detect_crashes


def test_handled_websocket_timeout_warning_is_not_a_crash():
    """Exact production false positive: must NOT be flagged."""
    logs = [
        "Aug 26 06:04:38 host python3[123]: ⚠️  WebSocket error: "
        "WebSocketTimeoutException: ping/pong timed out"
    ]
    has_crash, crash_lines = detect_crashes(logs)
    assert has_crash is False
    assert crash_lines == []


def test_other_handled_warning_lines_with_exception_class_names_are_not_crashes():
    logs = [
        "⚠️  save_auditor_state: Timeout of 60.0s exceeded, last exception: "
        "429 Quota exceeded.",
        "⚠️  save_bot2_advice: Timeout of 60.0s exceeded, last exception: "
        "429 Quota exceeded.",
    ]
    has_crash, crash_lines = detect_crashes(logs)
    assert has_crash is False
    assert crash_lines == []


def test_real_traceback_is_still_detected():
    """The fix must not blind the detector to an actual unhandled crash."""
    logs = [
        "Traceback (most recent call last):",
        '  File "bot2/main.py", line 42, in run',
        "ZeroDivisionError: division by zero",
    ]
    has_crash, crash_lines = detect_crashes(logs)
    assert has_crash is True
    assert any("Traceback" in line for line in crash_lines)


def test_fatal_marker_is_still_detected():
    logs = ["[STARTUP FATAL] Firebase initialization failed: connection refused"]
    has_crash, crash_lines = detect_crashes(logs)
    assert has_crash is True


def test_no_logs_no_crash():
    has_crash, crash_lines = detect_crashes([])
    assert has_crash is False
    assert crash_lines == []
