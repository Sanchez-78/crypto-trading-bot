"""Production-linked RED gate (Phase 3): a no-price expiry is not a loss.

Phase 0 evidence: 106 of 472 rows (22.5%) in the local cohort are
`exit_reason=TIMEOUT_NO_PRICE`, and every single one carries

    exit_price = 0.0     pnl_pct = 0.0     win = 0

These are positions the executor closed WITHOUT ever obtaining a market price
(the price feed went stale for that symbol). The executor deliberately
quarantines them from learning -- `learning_skipped=True`, no `record_close`,
and `canonical_learning_eligibility()` rejects them as
`timeout_no_price_invalid`. So the trading code already knows they are not
trades.

The persisted row says otherwise. `exit_price=0.0` asserts the market printed
a price of zero, which is false, and `win=0` books a non-event as a defeat.
Anything counting rows -- including the dashboard's raw win rate -- therefore
treats a stale price feed as 106 losing trades.

The fix asserted here is a genuine distinct state, NOT a post-hoc filter:

* RED-1: the outcome contract has a state for "no measurable outcome".
* RED-2: the executor writes that state, with `win` and `exit_price` NULL
  rather than 0 -- unknown is recorded as unknown.
* RED-3: the persistence layer preserves NULL `win` instead of coercing it
  to 0 (`1 if trade.get("win") else 0` is what silently made it a loss).
* RED-4: VOID rows are excluded from the canonical win-rate denominator,
  while FLAT trades -- which ARE real trades -- stay in it.

PAPER-only: writes only to the redirected test sink.
"""

import sqlite3

import pytest

from src.core import trade_metrics_contract as tmc
from src.services import local_persistent_cache as lpc


def test_outcome_contract_has_a_void_state():
    """RED-1: WIN/LOSS/FLAT cannot express 'never got a price'."""
    assert hasattr(tmc.TradeOutcome, "VOID"), \
        "TradeOutcome has no state for an unmeasurable (no-fill-price) close"
    assert tmc.TradeOutcome.VOID.value == "VOID"


def test_save_closed_trade_preserves_null_win(tmp_path, monkeypatch):
    """RED-3: an unknown win must persist as NULL, never coerced to 0."""
    db = tmp_path / "cache.sqlite"
    monkeypatch.setattr(lpc, "LOCAL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(lpc, "LOCAL_DB_PATH", str(db))
    monkeypatch.setattr(lpc, "LOCAL_STATE_DIR", str(tmp_path / "state"))
    lpc._init_db()

    lpc.save_closed_trade({
        "trade_id": "paper_void01",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry_price": 100.0,
        "exit_price": None,
        "pnl_pct": None,
        "win": None,
        "outcome": "VOID",
        "exit_reason": "TIMEOUT_NO_PRICE",
    })

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT win, exit_price, outcome FROM closed_trades WHERE trade_id=?",
            ("paper_void01",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["win"] is None, f"unknown win was coerced to {row['win']!r}"
    assert row["exit_price"] is None, "exit_price 0.0 asserts a zero market price"
    assert row["outcome"] == "VOID"


def test_void_is_excluded_from_the_win_rate_denominator():
    """RED-4: VOID is not a trade; FLAT is. Only VOID leaves the denominator."""
    outcomes = [
        tmc.TradeOutcome.WIN,
        tmc.TradeOutcome.LOSS,
        tmc.TradeOutcome.FLAT,
        tmc.TradeOutcome.VOID,
        tmc.TradeOutcome.VOID,
    ]
    # 1 win out of 3 real trades (WIN, LOSS, FLAT) -- the two VOIDs are not
    # trades and must not dilute the rate to 1/5.
    assert tmc.compute_win_rate(outcomes) == pytest.approx(1 / 3)

    # All-VOID is not a 0% win rate, it is no measurement at all.
    assert tmc.compute_win_rate([tmc.TradeOutcome.VOID]) == 0.0


def test_executor_timeout_no_price_branch_records_unknown_not_loss():
    """RED-2: the production branch writes VOID/NULL, not 0.0/0.

    Asserted against the real source so the contract cannot drift back.
    """
    from pathlib import Path

    src = Path(__file__).parents[1] / "src/services/paper_trade_executor.py"
    text = src.read_text(encoding="utf-8")

    marker = text.index('"exit_reason": "TIMEOUT_NO_PRICE"')
    # The WHOLE closed_trade dict literal that carries this exit reason --
    # from `closed_trade = {` through its closing brace. Slicing only up to
    # the exit_reason line would miss every key declared after it.
    block_start = text.rindex("closed_trade = {", 0, marker)
    block_end = text.index("\n            }", marker)
    block = text[block_start:block_end]

    assert '"exit_price": 0.0' not in block, \
        "TIMEOUT_NO_PRICE still books exit_price=0.0 (asserts a zero market price)"
    assert '"exit_price": None' in block, "exit_price must be recorded as unknown"
    assert '"win": None' in block, "win must be NULL, not an implicit loss"
    assert '"outcome": "VOID"' in block, "no explicit VOID outcome is written"
