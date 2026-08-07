"""P0.7 §22.3 bypass architecture tests.

Statically prove the new central-routing modules (strategy_contracts,
strategy_registry, signal_router, cost_model) cannot reach any paper-entry
primitive -- so a future P0.8+ strategy module that only imports from these
new modules inherits that guarantee by construction.
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

NEW_ROUTING_MODULES = [
    "src/services/strategy_contracts.py",
    "src/services/strategy_registry.py",
    "src/services/signal_router.py",
    "src/services/cost_model.py",
]

FORBIDDEN_ENTRY_SYMBOLS = {
    "open_paper_position",
    "open_position",
    "place_order",
    "create_order",
    "maybe_open_training_sample",
}

FORBIDDEN_ENTRY_MODULES = {
    "paper_trade_executor",
    "trade_executor",
    "paper_training_sampler",
    "paper_exploration",
    "execution_engine",
}


@pytest.mark.parametrize("relpath", NEW_ROUTING_MODULES)
def test_module_has_no_forbidden_entry_symbol_calls(relpath):
    """AST-based call scan (§22.3): no Call node in these modules may
    reference a forbidden entry-primitive name, however it was imported."""
    src = (REPO / relpath).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=relpath)

    called_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called_names.add(func.id)
            elif isinstance(func, ast.Attribute):
                called_names.add(func.attr)

    hit = called_names & FORBIDDEN_ENTRY_SYMBOLS
    assert not hit, f"{relpath} calls forbidden entry symbol(s): {hit}"


@pytest.mark.parametrize("relpath", NEW_ROUTING_MODULES)
def test_module_has_no_forbidden_entry_module_imports(relpath):
    """No import statement in these modules may reference a module that
    itself provides a paper-entry primitive."""
    src = (REPO / relpath).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=relpath)

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.add(node.module.split(".")[-1])
            for alias in node.names:
                imported_modules.add(alias.name)

    hit = imported_modules & FORBIDDEN_ENTRY_MODULES
    assert not hit, f"{relpath} imports forbidden entry module(s): {hit}"


def test_signal_router_source_has_no_forbidden_invocation_pattern():
    """Belt-and-braces plain-text check in addition to the AST scan, in case
    a future edit references a forbidden name through a string/getattr that
    the AST scan's Call/Import analysis wouldn't catch.

    Scans code lines only (module docstring and `#` comments excluded) --
    this module's docstring legitimately *discusses* why these names are
    absent (that is the point of documenting a bypass guarantee), which a
    naive whole-file substring check would misfire on. What must never
    appear in actual code is an invocation pattern: the forbidden name
    immediately followed by `(`, or as a dotted/import reference.
    """
    tree = ast.parse((REPO / "src/services/signal_router.py").read_text(encoding="utf-8"))
    # Drop the module docstring (first Expr/Constant statement) before
    # rendering back to source, so prose explaining the exclusion can't
    # trip this check.
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, (ast.Constant,))
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body = tree.body[1:]
    code_only = ast.unparse(tree)

    for forbidden in FORBIDDEN_ENTRY_SYMBOLS | FORBIDDEN_ENTRY_MODULES:
        assert forbidden not in code_only, (
            f"signal_router.py's executable code (docstring excluded) references "
            f"forbidden name: {forbidden}"
        )


def test_signal_router_never_opens_a_position_at_runtime(monkeypatch):
    """Dynamic spy: even if some future refactor added an indirect call
    path, patching the real entry primitive to explode proves the router's
    actual execution never reaches it for a representative admit-path
    signal."""
    import src.services.paper_trade_executor as pte

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("signal_router reached open_paper_position()!")

    monkeypatch.setattr(pte, "open_paper_position", _must_not_be_called, raising=True)

    from src.services import strategy_contracts as sc
    from src.services.signal_router import evaluate_signal_for_paper_entry
    from src.services.strategy_registry import StrategyRegistration, StrategyRegistry

    reg = StrategyRegistry()
    reg.register(StrategyRegistration(
        strategy_id="trend_cost_aware", current_version="1", enabled=True,
        evidence_only=True, allowed_symbols=frozenset({"ETHUSDT"}),
        allowed_regimes=frozenset({"BULL_TREND"}), allowed_sides=frozenset({"BUY"}),
        exit_profile="dynamic_trend_exit_v1", minimum_warmup_seconds=60,
        required_feature_schema_version="v1",
    ))
    sig = sc.StrategySignal(
        signal_id="sig-1", strategy_id="trend_cost_aware", strategy_version="1",
        symbol="ETHUSDT", side="BUY", regime="BULL_TREND",
        learning_source="trend_cost_aware_v1",
        generated_event_time_ms=1_700_000_000_000,
        generated_processing_time_ms=1_700_000_000_010,
        market_data_event_time_ms=1_700_000_000_005,
        feature_snapshot_time_ms=1_700_000_000_005,
        expected_horizon_seconds=300, reference_price=1900.0,
        gross_expected_move_bps=30.0, expected_cost_bps=10.0,
        uncertainty_buffer_bps=2.0, net_expected_edge_bps=18.0, confidence=0.6,
        invalidation_price=1890.0, initial_stop_price=1890.0,
        target_reference_price=1930.0, exit_profile="dynamic_trend_exit_v1",
        feature_schema_version="v1",
    )
    evaluate_signal_for_paper_entry(
        sig, registry=reg, best_bid=1899.9, best_ask=1900.1,
        requested_notional=25.0, visible_top_notional=1000.0,
        realized_volatility_bps=10.0, realized_volatility_bps_per_second=0.5,
        decision_latency_ms=20.0, now_ms=1_700_000_000_050,
    )
    # If we reach here without AssertionError, open_paper_position was never called.
