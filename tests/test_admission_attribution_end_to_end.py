"""Production-linked RED gate: attribution must survive open -> position -> close.

Having the columns (test_closed_trades_attribution_persistence.py) and having
canonical_admit() stamp the values (test_canonical_admission_contract.py) is
not sufficient. The position dict inside open_paper_position() is built from
an EXPLICIT ALLOWLIST of `extra` keys, so any stamped key not named there is
silently dropped at the position boundary and never reaches the close writer.

That is exactly the shape of the 2026-08-18 attribution write bug, where
bucket/source/paper_source were correct in memory at open time and lost on the
way to SQLite. This test closes the loop: what canonical_admit() stamps must
be readable on the position, because `close_paper_position` builds the closed
trade as `{**pos, ...}`.

PAPER-only: no position is persisted to any production path; the executor's
save/state hooks are monkeypatched out.
"""

import pytest

from src.services import paper_trade_executor as pte

STAMPED = ("admission_route", "code_version", "config_version", "effective_hold_s")


@pytest.fixture()
def ready_executor(monkeypatch):
    """Put the executor in READY state with persistence stubbed out."""
    monkeypatch.setattr(pte, "_PAPER_STATE_STATUS", "READY", raising=False)
    monkeypatch.setattr(pte, "_PAPER_STATE_INITIALIZED", True, raising=False)
    monkeypatch.setattr(pte, "_save_paper_state", lambda *a, **k: True)
    monkeypatch.setattr(pte, "_init_paper_state_once", lambda *a, **k: None)
    monkeypatch.delenv("PAPER_DATA_COLLECTION_ONLY", raising=False)
    monkeypatch.delenv("PAPER_SYMBOL_BLACKLIST", raising=False)
    with pte._POSITION_LOCK:
        pte._POSITIONS.clear()
    yield pte
    with pte._POSITION_LOCK:
        pte._POSITIONS.clear()


def test_canonical_attribution_reaches_the_open_position(ready_executor, monkeypatch):
    """RED: the stamped attribution is present on the in-memory position."""
    monkeypatch.setenv("BOT_CODE_VERSION", "sha_deadbeef")
    monkeypatch.setenv("BOT_CONFIG_VERSION", "cfg_42")

    result = pte.canonical_admit(
        signal={
            "symbol": "BTCUSDT", "action": "BUY", "ev": 0.5, "score": 0.9,
            "regime": "BULL_TREND", "p": 0.7,
            "learning_source": "strict_ev", "segment_key": "BTCUSDT_BUY_BULL",
        },
        price=50_000.0,
        ts=1_700_000_000.0,
        route="RDE_TAKE",
        reason="RDE_TAKE",
        extra={"paper_source": "rde_take", "max_hold_s": 300},
    )

    assert result["outcome"] == "OPENED", f"setup failure, not RED: {result}"

    with pte._POSITION_LOCK:
        positions = list(pte._POSITIONS.values())
    assert len(positions) == 1
    pos = positions[0]

    missing = [k for k in STAMPED if k not in pos or pos[k] is None]
    assert not missing, (
        "attribution stamped by canonical_admit() was dropped at the position "
        f"boundary and can never reach the close writer: {missing}"
    )

    assert pos["admission_route"] == "RDE_TAKE"
    assert pos["code_version"] == "sha_deadbeef"
    assert pos["config_version"] == "cfg_42"
    assert isinstance(pos["effective_hold_s"], float)

    # segment_key is NOT asserted equal to the supplied value: the executor
    # deterministically RE-DERIVES it as
    # f"{symbol}_{side}_{regime}_{source}_{tp_sl_profile}" on the P0.3C
    # evidence-collection reroute. That re-derivation is the canonical form,
    # so the contract worth asserting is that the position carries one
    # non-empty, symbol-scoped segment_key -- not that the caller's value wins.
    assert isinstance(pos["segment_key"], str) and pos["segment_key"]
    assert pos["segment_key"].startswith("BTCUSDT")
