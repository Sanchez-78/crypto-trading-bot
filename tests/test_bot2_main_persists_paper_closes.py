"""P1.1AR regression test (forensic pass, 2026-08-18): bot2/main.py's
main-loop call to update_paper_positions() must persist any closed trades
it receives, not discard the return value.

Root cause confirmed live in production: update_paper_positions() is called
from TWO places against the same shared _POSITIONS state -- trade_executor's
on_price() (WS tick handler) and bot2/main.py's own loop. Whichever caller
observes a TP/SL crossing first pops the position and gets it in its return
value; the other caller never sees it again. on_price() has always persisted
its return value via _save_paper_trade_closed(); bot2/main.py's call site
discarded its own return value entirely with a bare `update_paper_positions(
lp, now)` statement. TP/SL has no other persistence path (unlike TIMEOUT,
which is independently re-caught by check_and_close_timeout_positions()), so
any TP/SL close this loop won the race for was executed correctly in-memory
but never written to cache.sqlite/Firebase. Confirmed live: cache.sqlite
showed zero non-TIMEOUT exits since 2026-08-05 despite TP/SL still firing
correctly every day (visible in [TP_SL_HIT]/[PAPER_EXIT] "executed" log
lines with no matching DB row).

main() is a large, monolithic, side-effecting function that starts a full
bot process -- it cannot be safely unit-tested by calling it directly. This
test instead statically verifies the source-level invariant that actually
matters: the specific call site's return value must be captured and handed
to the same persistence function on_price() uses, in the correct order,
inside the same try block. This mirrors the precedent set by
tests/test_state_01_import_purity.py::test_bot2_main_calls_initializer_after_event_bus_init
for the same file/function.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_bot2_main_source() -> str:
    return (REPO_ROOT / "bot2" / "main.py").read_text(encoding="utf-8")


def test_update_paper_positions_return_value_is_not_discarded():
    """The main-loop call site must NOT be a bare
    `update_paper_positions(lp, now)` statement (discards the return value --
    the exact regression this test guards against)."""
    src = _read_bot2_main_source()
    assert "update_paper_positions(lp, now)" in src, (
        "expected call site not found -- has the call signature changed? "
        "update this test's search string accordingly, don't just delete it"
    )
    # The bare/discarding form has no `=` immediately before it on the same
    # logical line. Also reject a throwaway `_ =` assignment -- that still
    # discards the value just as effectively as no assignment at all.
    assert "= update_paper_positions(lp, now)" in src, (
        "P1.1AR regression: update_paper_positions(lp, now) return value is "
        "discarded again -- any TP/SL close this call site wins the race "
        "for will silently vanish (never persisted, no error, no log)"
    )
    assert "_ = update_paper_positions(lp, now)" not in src, (
        "P1.1AR regression (throwaway-assign variant): assigning to `_` "
        "still discards the value -- it must actually be consumed and "
        "persisted, not merely captured"
    )


def test_closed_papers_from_main_loop_are_persisted():
    """Whatever update_paper_positions(lp, now) returns in the main loop must
    be handed to _save_paper_trade_closed() for EVERY closed trade (not just
    the first), the same way on_price() does -- not left to just update
    in-memory state."""
    src = _read_bot2_main_source()

    assign_idx = src.index("= update_paper_positions(lp, now)")
    # The persistence call must appear after the assignment, within a bounded
    # distance (same try block, not some unrelated later call site).
    window = src[assign_idx: assign_idx + 800]
    assert "_save_paper_trade_closed" in window, (
        "P1.1AR regression: update_paper_positions(lp, now)'s return value "
        "is captured but never passed to _save_paper_trade_closed() -- "
        "closed TP/SL trades from this call site still won't reach "
        "cache.sqlite/Firebase"
    )
    # Require an actual `for ... in <captured var>:` loop over the FULL
    # returned list -- not a narrower fallback that would also accept
    # something like `_save_paper_trade_closed(_closed_papers[0])`
    # (persisting only the first item, silently dropping the rest).
    assert "for _closed_trade in _closed_papers" in window, (
        "expected an explicit `for _closed_trade in _closed_papers:` loop "
        "persisting EVERY closed trade -- a call that only persists the "
        "first item (e.g. _closed_papers[0]) would still lose data and must "
        "fail this test"
    )
    assert "_closed_papers[0]" not in window, (
        "P1.1AR regression (partial-persist variant): indexing only the "
        "first closed trade still silently drops the rest when more than "
        "one position closes in the same tick"
    )


def test_paper_update_error_handling_still_present():
    """The existing broad except (pre-existing behavior, not touched by this
    fix) must still wrap the block -- this test is not asking for that to
    change, only confirming the fix didn't accidentally remove error
    isolation from the main loop."""
    src = _read_bot2_main_source()
    assign_idx = src.index("= update_paper_positions(lp, now)")
    # Look backward a bit for the enclosing try, and forward for the except.
    before = src[max(0, assign_idx - 300): assign_idx]
    after = src[assign_idx: assign_idx + 800]
    assert "try:" in before
    assert "except Exception as e:" in after
    assert "PAPER_UPDATE_ERROR" in after
