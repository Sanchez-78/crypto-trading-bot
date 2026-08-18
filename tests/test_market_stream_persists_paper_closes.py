"""P1.1AR regression test (forensic pass, 2026-08-18), market_stream.py half.

_dispatch() -- the WS tick handler -- calls update_paper_positions() on
every tick and discarded its return value, exactly like the analogous
bot2/main.py main-loop call site (see tests/test_bot2_main_persists_paper_closes.py
for the full root-cause writeup). This call site is the more important of
the two: it fires on every WS tick and runs BEFORE `publish("price_tick",
...)`, which is what trade_executor.on_price() is subscribed to -- so it
almost always wins the race to observe a TP/SL price crossing first,
silently discarding the only copy of that closed trade's data.

_dispatch() is deep inside market_stream.py's WS plumbing and not safely
unit-callable in isolation (network/WS setup). Like the bot2/main.py
counterpart, this test statically verifies the source-level invariant that
matters: the captured return value must be handed to the same persistence
function on_price() uses, for every closed trade, not just the first.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_market_stream_source() -> str:
    return (REPO_ROOT / "src" / "services" / "market_stream.py").read_text(encoding="utf-8")


def test_update_paper_positions_return_value_is_not_discarded():
    src = _read_market_stream_source()
    assert "update_paper_positions(_symbol_prices, time.time())" in src, (
        "expected call site not found -- has the call signature changed? "
        "update this test's search string accordingly, don't just delete it"
    )
    assert "= update_paper_positions(_symbol_prices, time.time())" in src, (
        "P1.1AR regression: update_paper_positions(...) return value is "
        "discarded again in the WS tick dispatcher -- this call site wins "
        "the TP/SL close race on almost every tick, so this is the primary "
        "sink of the data loss this fix closes"
    )
    assert "_ = update_paper_positions(_symbol_prices, time.time())" not in src, (
        "P1.1AR regression (throwaway-assign variant): assigning to `_` "
        "still discards the value"
    )


def test_closed_papers_from_dispatch_are_persisted():
    src = _read_market_stream_source()
    assign_idx = src.index("= update_paper_positions(_symbol_prices, time.time())")
    window = src[assign_idx: assign_idx + 900]
    assert "_save_paper_trade_closed" in window, (
        "P1.1AR regression: the WS tick dispatcher's update_paper_positions() "
        "return value is captured but never passed to _save_paper_trade_closed()"
    )
    assert "for _closed_trade in _closed_papers" in window, (
        "expected an explicit `for _closed_trade in _closed_papers:` loop "
        "persisting EVERY closed trade, not just the first"
    )
    assert "_closed_papers[0]" not in window, (
        "P1.1AR regression (partial-persist variant): indexing only the "
        "first closed trade still silently drops the rest"
    )


def test_dispatch_persistence_is_exception_guarded():
    """This call site previously had NO try/except at all (unlike the
    bot2/main.py counterpart) -- a persistence hiccup must not be able to
    interrupt the WS tick dispatcher (_dispatch is on the hot path for
    every incoming tick)."""
    src = _read_market_stream_source()
    assign_idx = src.index("= update_paper_positions(_symbol_prices, time.time())")
    before = src[max(0, assign_idx - 200): assign_idx]
    after = src[assign_idx: assign_idx + 900]
    assert "try:" in before, "the update_paper_positions() call must be inside a try block"
    assert "except Exception as e:" in after
    assert "PAPER_UPDATE_ERROR" in after


def test_save_call_deferred_until_after_publish():
    """Refinement from safety-persist-fix's review: the actual
    _save_paper_trade_closed() write (blocking network I/O) must run AFTER
    publish("price_tick", ...), not before -- so a slow/blocking Firebase
    call cannot delay tick fan-out to downstream consumers. Only the cheap
    in-memory evaluation call (update_paper_positions) may stay before
    publish. Dedup (_CLOSED_TRADES_THIS_SESSION) makes this reordering safe."""
    src = _read_market_stream_source()
    assign_idx = src.index("= update_paper_positions(_symbol_prices, time.time())")
    publish_idx = src.index('publish("price_tick"', assign_idx)
    save_idx = src.index("_save_paper_trade_closed(_closed_trade)", assign_idx)
    assert save_idx > publish_idx, (
        "P1.1AR regression: _save_paper_trade_closed() must be called AFTER "
        "publish(\"price_tick\", ...), not before -- moving it earlier "
        "reintroduces a blocking-network-call-on-the-hot-path risk"
    )
    # The persistence block should have its own, separate exception guard
    # (distinct from the evaluation call's PAPER_UPDATE_ERROR guard) since
    # it's now a physically separate try block after the restructuring.
    window = src[publish_idx: save_idx + 200]
    assert "PAPER_SAVE_ERROR" in window, (
        "expected a dedicated exception guard around the deferred "
        "persistence block, separate from the evaluation call's guard"
    )


def test_dispatch_still_publishes_price_tick_after_persistence():
    """The persistence addition must not have been inserted AFTER
    publish("price_tick", ...) or displaced it -- on_price() depends on
    that publish still happening every tick regardless of this change."""
    src = _read_market_stream_source()
    assign_idx = src.index("= update_paper_positions(_symbol_prices, time.time())")
    # Search only after assign_idx -- the explanatory comment on this fix
    # itself mentions the literal text `publish("price_tick", ...)`, which
    # would otherwise be found first by a plain src.index() and defeat this
    # check.
    publish_idx = src.index('publish("price_tick"', assign_idx)
    assert publish_idx > assign_idx, (
        "price_tick publish must still occur after the paper-position update, "
        "matching the pre-existing tick-processing order"
    )
