"""Regression test for the 2026-08-27 dead-code fix in
emergency_health_monitor.py:detect_entry_stall().

Root cause: the "entries flowing" check was
`if "PAPER_ENTRY\\|admission_reason=paper_learning" in log_line:` -- a
grep-style `\\|` alternation written inside a plain Python substring
check, which can never match (no log line literally contains that whole
string). This permanently disabled the early-return path, dating to the
file's original commit -- found during cycle-125 deploy verification
(_workspace/48_deploy_verification_two_new_findings.md, Finding B).

v1 of this fix kept `"admission_reason=paper_learning" in log_line` as a
second alternative, believing it inert. REJECTED on review: it's an
unterminated prefix that matches the LIVE value
`admission_reason=paper_learning_must_continue` (the sampler's
recovery-admission path, logged as `[PAPER_ENTRY_ADMISSION_TRUTH]`),
which fires when a candidate is merely admitted for consideration --
before open_paper_position() and its ~15 downstream block gates ever
run. Treating that as "flowing" would have re-introduced exactly the
stall-masking bug this fix exists to close. v2 dropped that branch
entirely; only the real `[PAPER_ENTRY]` marker counts.
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


def test_admission_truth_recovery_admission_does_not_count_as_a_real_entry():
    """2026-08-27 v2 regression guard: [PAPER_ENTRY_ADMISSION_TRUTH] with
    admission_reason=paper_learning_must_continue means the sampler merely
    ADMITTED a candidate for consideration -- open_paper_position() and its
    ~15 downstream block gates haven't run yet. Must NOT be treated as a
    real entry, or a genuine stall in exactly the low-throughput
    starvation-recovery regime this detector exists for would be masked
    (cf. the 2026-08-17 66h SKIP_SCORE_HARD stall)."""
    _reset_state()
    ehm._monitor_state["last_entry_rate"] = 0
    logs = [
        "[PAPER_ENTRY_ADMISSION_TRUTH] symbol=BTCUSDT "
        "admission_reason=paper_learning_must_continue source_reject=none",
        "candidate_ev=0.0300 positive_ev",
    ]
    is_stalled, reason = ehm.detect_entry_stall(
        logs, current_time=ehm._ENTRY_STALL_THRESHOLD + 1
    )
    assert is_stalled is True, (
        "an admitted-but-not-yet-opened candidate must not reset the "
        "stall timer or report 'Entries flowing'"
    )


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
