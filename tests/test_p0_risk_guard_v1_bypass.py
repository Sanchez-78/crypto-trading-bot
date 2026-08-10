"""§22.3 bypass architecture test for p0_risk_guard_v1.py.

Unlike the strategy modules and signal_router.py, this module IS allowed to
import paper_trade_executor (for the read-only get_open_positions()
accessor, §17.1 duplicate/opposite-position check) -- but must still never
call open_paper_position() or any other entry primitive, and must never
import trade_executor/execution_engine/paper_training_sampler/
paper_exploration (no legitimate reason for this module to touch any of
those).
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = "src/services/p0_risk_guard_v1.py"

FORBIDDEN_ENTRY_SYMBOLS = {
    "open_paper_position", "open_position", "place_order",
    "create_order", "maybe_open_training_sample",
}
# paper_trade_executor is deliberately NOT in this set -- see module docstring.
FORBIDDEN_ENTRY_MODULES = {
    "trade_executor", "paper_training_sampler", "paper_exploration", "execution_engine",
}


def test_module_has_no_forbidden_entry_symbol_calls():
    src = (REPO / MODULE).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=MODULE)
    called_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called_names.add(func.id)
            elif isinstance(func, ast.Attribute):
                called_names.add(func.attr)
    hit = called_names & FORBIDDEN_ENTRY_SYMBOLS
    assert not hit, f"{MODULE} calls forbidden entry symbol(s): {hit}"


def test_module_has_no_forbidden_entry_module_imports():
    src = (REPO / MODULE).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=MODULE)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[-1])
            for alias in node.names:
                imported.add(alias.name)
    hit = imported & FORBIDDEN_ENTRY_MODULES
    assert not hit, f"{MODULE} imports forbidden entry module(s): {hit}"


def test_module_only_calls_get_open_positions_on_paper_trade_executor():
    """Narrower, positive check: the ONE paper_trade_executor symbol this
    module may reference is get_open_positions -- confirm no other
    attribute access on that module sneaks in."""
    src = (REPO / MODULE).read_text(encoding="utf-8")
    assert "from src.services import paper_trade_executor" in src
    assert "paper_trade_executor.get_open_positions" in src
    # No other paper_trade_executor.<name> access pattern.
    import re
    accesses = set(re.findall(r"paper_trade_executor\.(\w+)", src))
    assert accesses == {"get_open_positions"}, f"unexpected paper_trade_executor accesses: {accesses}"


def test_module_never_opens_a_position_at_runtime(monkeypatch):
    import src.services.paper_trade_executor as pte

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("p0_risk_guard_v1 reached open_paper_position()!")

    monkeypatch.setattr(pte, "open_paper_position", _must_not_be_called, raising=True)

    from src.services.p0_risk_guard_v1 import evaluate_risk_guard
    # Real accessors (paper_trade_executor.get_open_positions() on an
    # otherwise-untouched test-process position store returns {}), real
    # runtime_mode/risk_engine/firebase_client -- exercising the actual
    # lazy-import default path, not injected fakes, specifically to prove
    # the real code path never reaches open_paper_position.
    evaluate_risk_guard(symbol="ETHUSDT", side="BUY")
    # If we reach here, open_paper_position was never called.
