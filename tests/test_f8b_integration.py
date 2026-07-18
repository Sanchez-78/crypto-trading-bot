"""Static wiring tests for the F8b observation-only integration.

The two call-site modules (signal_generator, paper_trade_executor) pull heavy
runtime deps (numpy, firebase, event bus) and run import-time side effects, so the
hook wiring is asserted at the source level here; the recorder's own behaviour is
covered by test_shadow_excursion_recorder.py.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIGGEN = REPO / "src/services/signal_generator.py"
EXEC = REPO / "src/services/paper_trade_executor.py"


def test_tick_hook_before_blacklist_gate_and_gated():
    """record_tick must be fed BEFORE the symbol-blacklist early-return (so observers
    keep getting ticks while paused), and only when the recorder is enabled."""
    t = SIGGEN.read_text(encoding="utf-8")
    assert "shadow_excursion_recorder" in t
    tick = t.index("_shadow.record_tick(")
    gate = t.index('if _bl and s in _bl.split(",")')
    assert tick < gate, "record_tick must run before the blacklist early-return"
    # gated by enabled() so it is a no-op in normal operation
    assert t.rindex("_shadow.enabled()", 0, tick) > t.index("s, p = data")


def test_entry_diversion_records_and_skips_open_when_enabled():
    """In _on_signal_created, when data-collection is enabled the signal is recorded
    and the function RETURNS before open_paper_position — no position is opened."""
    t = EXEC.read_text(encoding="utf-8")
    hook = t.index("shadow_excursion_recorder")
    record = t.index("_shadow.record_signal(", hook)
    ret = t.index("return", record)
    open_call = t.index("open_paper_position(\n", hook)  # the real open call site
    # record_signal + return must both precede the open call
    assert record < ret < open_call, "record + return must come before open_paper_position"
    # the diversion is gated by enabled()
    assert "_shadow.enabled()" in t[hook:open_call]
    # observation path marks the signal handled so RDE won't double-process it
    assert '__paper_handled' in t[record:open_call]


def test_integration_is_default_off():
    """Both hooks are guarded by _shadow.enabled(), which is false unless
    PAPER_DATA_COLLECTION_ONLY is set — so normal operation is unchanged."""
    from src.services import shadow_excursion_recorder as R
    import os
    os.environ.pop("PAPER_DATA_COLLECTION_ONLY", None)
    assert R.enabled() is False
