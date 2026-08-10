"""P1.2 §22.3 bypass architecture test for strategy_sideways_mean_reversion_v1.py.

Same discipline as the other P0.8+ strategy bypass tests: this module must
never call or import a paper-entry primitive, and must contain no promotion
logic or martingale/scale-in behavior (§14.5).
"""
import ast
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = "src/services/strategy_sideways_mean_reversion_v1.py"

FORBIDDEN_ENTRY_SYMBOLS = {
    "open_paper_position", "open_position", "place_order",
    "create_order", "maybe_open_training_sample",
}
FORBIDDEN_ENTRY_MODULES = {
    "paper_trade_executor", "trade_executor", "paper_training_sampler",
    "paper_exploration", "execution_engine",
}


def test_strategy_module_has_no_forbidden_entry_symbol_calls():
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


def test_strategy_module_has_no_forbidden_entry_module_imports():
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


def test_strategy_module_never_opens_a_position_at_runtime(monkeypatch):
    import src.services.paper_trade_executor as pte

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("strategy_sideways_mean_reversion_v1 reached open_paper_position()!")

    monkeypatch.setattr(pte, "open_paper_position", _must_not_be_called, raising=True)

    from src.services import strategy_sideways_mean_reversion_v1 as mr

    rng = random.Random(0)
    candles = []
    price = 1000.0
    for i in range(100):
        offset = 0.004 * (0.5 - rng.random())
        close_p = price * (1 + offset)
        candles.append({
            "open_time": 1_700_000_000_000 + i * 60_000,
            "open": price, "high": max(price, close_p) * 1.0008,
            "low": min(price, close_p) * 0.9992, "close": close_p,
            "volume": 10.0,
        })
        price = close_p
    candles.append({
        "open_time": candles[-1]["open_time"] + 60_000,
        "open": price, "high": price * 1.0008, "low": price * 0.94,
        "close": price * 0.97, "volume": 10.0,
    })

    mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=lambda *a: "sig-1", now_ms=candles[-1]["open_time"] + 100,
    )
    # If we reach here, open_paper_position was never called.


def test_strategy_module_registry_has_no_promotion_logic():
    tree = ast.parse((REPO / MODULE).read_text(encoding="utf-8"))
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body = tree.body[1:]
    code_only = ast.unparse(tree)
    assert "P0SegmentEVGate" not in code_only
    assert "evaluate_segment_for_strict_ev" not in code_only
    assert "strict_ev" not in code_only


def test_strategy_module_has_no_martingale_or_scale_in_symbols():
    """§14.5: never implement martingale, doubling down, unbounded DCA,
    averaging into adverse movement, increasing size after a loss, grid
    recovery, or holding-until-return."""
    src = (REPO / MODULE).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=MODULE)
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body = tree.body[1:]
    code_only = ast.unparse(tree).lower()
    for forbidden in ("martingale", "doubledown", "double_down", "scale_in", "griddrecovery", "grid_recovery"):
        assert forbidden not in code_only, f"{MODULE} contains forbidden §14.5 term: {forbidden}"
