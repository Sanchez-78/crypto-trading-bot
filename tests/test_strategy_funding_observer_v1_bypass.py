"""P1.3 §22.3 bypass architecture test for strategy_funding_observer_v1.py.

§15.4 "No trading": this module must never call or import a paper-entry
primitive, must never emit a StrategySignal (it is not a signal-producing
strategy in the P0.8+ sense -- see module docstring), and must never
reference a second leg / hedge / cross-venue execution concept.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = "src/services/strategy_funding_observer_v1.py"

FORBIDDEN_ENTRY_SYMBOLS = {
    "open_paper_position", "open_position", "place_order",
    "create_order", "maybe_open_training_sample",
}
FORBIDDEN_ENTRY_MODULES = {
    "paper_trade_executor", "trade_executor", "paper_training_sampler",
    "paper_exploration", "execution_engine",
}
# §15.4 explicit prohibitions for this specific phase.
FORBIDDEN_TWO_LEG_SYMBOLS = {
    "spot_hedge", "open_hedge", "place_hedge_order", "transfer_funds",
    "cross_venue_execute", "second_leg_order",
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
    hit = called_names & (FORBIDDEN_ENTRY_SYMBOLS | FORBIDDEN_TWO_LEG_SYMBOLS)
    assert not hit, f"{MODULE} calls forbidden symbol(s): {hit}"


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


def test_module_never_opens_a_position_at_runtime(monkeypatch):
    import src.services.paper_trade_executor as pte

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("strategy_funding_observer_v1 reached open_paper_position()!")

    monkeypatch.setattr(pte, "open_paper_position", _must_not_be_called, raising=True)

    from src.services import strategy_funding_observer_v1 as fo

    fo.observe_funding_opportunity(
        symbol="BTCUSDT", observed_at_ms=1_700_000_000_000,
        current_funding_rate_bps=1.0, mark_price=65000.0,
        estimated_entry_cost_bps=1.0, estimated_exit_cost_bps=1.0,
    )
    # If we reach here, open_paper_position was never called.


def test_module_does_not_define_generate_candidates():
    """§15.4: this module must never propose an entry -- structurally
    confirmed by the absence of a generate_candidates()/StrategySignal
    producer, unlike every trading strategy module in this phase family."""
    from src.services import strategy_funding_observer_v1 as fo
    assert not hasattr(fo, "generate_candidates")


def test_module_does_not_import_strategy_contracts_or_registry():
    """This is not a signal-producing strategy (module docstring) -- it
    must not import StrategySignal or the central registry, which would
    misrepresent it as one."""
    src = (REPO / MODULE).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=MODULE)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[-1])
    assert "strategy_contracts" not in imported_modules
    assert "strategy_registry" not in imported_modules
