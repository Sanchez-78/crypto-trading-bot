"""Regression test for the 2026-08-27 dead-code fix in
emergency_health_monitor.py:detect_entry_stall().

Root cause: the "entries flowing" check was
`if "PAPER_ENTRY\\|admission_reason=paper_learning" in log_line:` -- a
grep-style `\\|` alternation written inside a plain Python substring
check, which can never match (no log line literally contains that whole
string). This permanently disabled the early-return path, dating to the
file's original commit -- found during cycle-125 deploy verification
(_workspace/48_deploy_verification_two_new_findings.md, Finding B).
"""
from src.services import emergency_health_monitor as ehm


def _reset_state():
    ehm._monitor_state["last_entry_rate"] = 0
    ehm._monitor_state["entry_stall_count"] = 0


def test_bare_paper_entry_line_is_detected_as_flowing():
    _reset_state()
    logs = [
        "[PAPER_ENTRY] symbol=BTCUSDT side=BUY price=50000.00000000 "
        "size_usd=10.00 ev=0.0300 score=0.312 reason=A_STRICT_TAKE"
    ]
    is_stalled, reason = ehm.detect_entry_stall(logs, current_time=1000.0)
    assert is_stalled is False
    assert reason == "Entries flowing"
    assert ehm._monitor_state["last_entry_rate"] == 1000.0
    assert ehm._monitor_state["entry_stall_count"] == 0


def test_admission_reason_paper_learning_line_is_still_detected_as_flowing():
    """Preserves the original apparent intent -- currently inert in
    production (this string doesn't appear in current logs), but kept as
    a harmless alternative in case another code path emits it."""
    _reset_state()
    logs = ["some_future_line admission_reason=paper_learning more_fields"]
    is_stalled, reason = ehm.detect_entry_stall(logs, current_time=1000.0)
    assert is_stalled is False
    assert reason == "Entries flowing"


def test_blocked_skip_attempt_variants_do_not_count_as_flowing():
    """2026-08-27 regression guard: a naive fix (just
    `"PAPER_ENTRY" in log_line`) would also match PAPER_ENTRY_BLOCKED/
    SKIP/ATTEMPT -- none of which represent a successful entry. Must use
    the bracket-terminated "PAPER_ENTRY]" match to exclude them."""
    _reset_state()
    ehm._monitor_state["last_entry_rate"] = 0  # far in the past
    logs = [
        "[PAPER_ENTRY_BLOCKED] symbol=BTCUSDT reason=quota",
        "[PAPER_ENTRY_SKIP] symbol=ETHUSDT reason=cooldown",
        "[PAPER_ENTRY_ATTEMPT] symbol=SOLUSDT",
        "candidate_ev=0.0300 positive_ev",
    ]
    is_stalled, reason = ehm.detect_entry_stall(logs, current_time=1000.0 + ehm._ENTRY_STALL_THRESHOLD + 1)
    assert is_stalled is True, (
        "BLOCKED/SKIP/ATTEMPT lines must not be mistaken for a real entry "
        "-- otherwise a genuine stall would be masked"
    )


def test_stall_still_detected_when_no_entries_and_ev_candidates_present():
    _reset_state()
    ehm._monitor_state["last_entry_rate"] = 0
    current_time = ehm._ENTRY_STALL_THRESHOLD + 100
    logs = ["candidate_ev=0.0300 positive_ev"]
    is_stalled, reason = ehm.detect_entry_stall(logs, current_time=current_time)
    assert is_stalled is True
    assert "Entry stall" in reason


def test_no_stall_when_no_ev_candidates_at_all():
    _reset_state()
    ehm._monitor_state["last_entry_rate"] = 0
    current_time = ehm._ENTRY_STALL_THRESHOLD + 100
    logs = ["some unrelated log line"]
    is_stalled, reason = ehm.detect_entry_stall(logs, current_time=current_time)
    assert is_stalled is False
    assert reason == "Entry rate OK"
