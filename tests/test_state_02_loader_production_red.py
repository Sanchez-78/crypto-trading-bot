"""Production-linked RED gate for STATE-02 loader error propagation.

This test intentionally asserts the required fail-closed contract against the
current implementation.  It must fail before the production fix and pass only
after malformed state is propagated to the initializer boundary.
"""

import json

import pytest


def test_load_paper_state_propagates_malformed_json(monkeypatch, tmp_path):
    from src.services import paper_trade_executor as pte

    state_file = tmp_path / "paper_open_positions.json"
    state_file.write_text("{ malformed", encoding="utf-8")
    monkeypatch.setattr(pte, "_STATE_FILE", str(state_file))

    with pytest.raises(json.JSONDecodeError):
        pte._load_paper_state()


def test_initializer_records_failed_status_after_loader_error(monkeypatch):
    from src.services import paper_trade_executor as pte

    monkeypatch.setattr(pte, "_PAPER_STATE_STATUS", "UNINITIALIZED")
    monkeypatch.setattr(pte, "_PAPER_STATE_INITIALIZED", False)
    monkeypatch.setattr(pte, "_load_paper_state", lambda: (_ for _ in ()).throw(OSError("synthetic load failure")))

    pte._init_paper_state_once()

    assert pte._PAPER_STATE_STATUS == "FAILED"


def test_direct_open_blocks_before_any_other_admission_gate(monkeypatch):
    from src.services import paper_trade_executor as pte

    monkeypatch.setattr(pte, "_PAPER_STATE_STATUS", "FAILED")
    result = pte.open_paper_position(
        {"symbol": "BTCUSDT", "action": "BUY", "ev": 0.2},
        100.0,
        1.0,
        "RDE_TAKE",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "paper_state_not_ready"
