"""Regression: PAPER_DATA_COLLECTION_ONLY must block position opening at the
authoritative choke — open_paper_position() itself — so NO caller (RDE,
trade_executor, exploration, P0 gate) can bypass observe mode.

Backstory (2026-07-19): the gate lived only in signal_generator + the
_on_signal_created handler, but realtime_decision_engine / trade_executor call
open_paper_position() directly and slipped a few entries through while observe
mode was set. The fix gates at the choke, fail-closed.
"""
import importlib
import os

import pytest


@pytest.fixture
def executor(monkeypatch):
    # Import fresh; the gate reads the env at call time, so no reload needed,
    # but ensure a clean module object.
    mod = importlib.import_module("src.services.paper_trade_executor")
    return mod


def _signal():
    return {"symbol": "ETHUSDT", "side": "BUY", "action": "BUY",
            "ev": 0.5, "score": 0.9, "p": 0.6, "coh": 0.5, "af": 0.1}


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes", "on"])
def test_observe_blocks_open_regardless_of_caller(executor, monkeypatch, flag):
    monkeypatch.setenv("PAPER_DATA_COLLECTION_ONLY", flag)
    # A real price + valid signal that would otherwise open. The choke must block
    # it BEFORE any position is created, for every caller reason.
    for reason in ("RDE_TAKE", "P0_GATE", "EXPLORE", "anything"):
        res = executor.open_paper_position(_signal(), 1866.0, 1784500000.0, reason=reason)
        assert res.get("status") == "blocked", (reason, res)
        assert res.get("reason") == "data_collection_only", (reason, res)


def test_observe_off_does_not_block_on_the_gate(executor, monkeypatch):
    # With the flag OFF, the observe gate must NOT be what blocks — the call may
    # still be blocked for other reasons (price, enforcement), but never with
    # reason=data_collection_only.
    monkeypatch.delenv("PAPER_DATA_COLLECTION_ONLY", raising=False)
    res = executor.open_paper_position(_signal(), 1866.0, 1784500000.0, reason="RDE_TAKE")
    assert res.get("reason") != "data_collection_only", res


def test_gate_is_the_first_thing_in_open_paper_position():
    """Static guard: the data-collection gate must sit at the TOP of
    open_paper_position (before any other early-return branch) so no logic can
    open a position ahead of it."""
    import inspect
    from src.services import paper_trade_executor as m
    src = inspect.getsource(m.open_paper_position)
    body = src.split('"""', 2)[-1]  # after the docstring
    gate_pos = body.find("PAPER_DATA_COLLECTION_ONLY")
    sell_pos = body.find("SELL ENFORCEMENT")
    assert gate_pos != -1, "observe gate missing from open_paper_position"
    assert gate_pos < sell_pos, "observe gate must precede all other branches"
