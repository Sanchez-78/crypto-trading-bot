"""P1.1 §22.3 bypass architecture test for strategy_volatility_breakout_v1.py.

Same discipline as tests/test_strategy_trend_cost_aware_v1_bypass.py,
extended to this new strategy module: it must never call or import a
paper-entry primitive, and must contain no promotion logic.
"""
import ast
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = "src/services/strategy_volatility_breakout_v1.py"

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
        raise AssertionError("strategy_volatility_breakout_v1 reached open_paper_position()!")

    monkeypatch.setattr(pte, "open_paper_position", _must_not_be_called, raising=True)

    from src.services import strategy_volatility_breakout_v1 as brk

    rng = random.Random(0)
    candles = []
    price = 1000.0
    n = 140
    for i in range(n):
        t = i / max(1, n - 1)
        range_frac = 0.006 + (0.0004 - 0.006) * t
        jitter = price * rng.uniform(-range_frac / 2, range_frac / 2)
        open_p = price
        close_p = max(0.01, price + jitter)
        high_p = max(open_p, close_p) * (1 + range_frac / 2)
        low_p = min(open_p, close_p) * (1 - range_frac / 2)
        candles.append({
            "open_time": 1_700_000_000_000 + i * 60_000,
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "volume": 20.0 + (3.0 - 20.0) * t,
        })
        price = close_p
    candles.append({
        "open_time": 1_700_000_000_000 + n * 60_000,
        "open": price, "high": price * 1.021, "low": price * 0.999,
        "close": price * 1.02, "volume": 60.0,
    })

    brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=lambda *a: "sig-1", now_ms=candles[-1]["open_time"] + 100,
    )
    # If we reach here, open_paper_position was never called.


def test_strategy_module_registry_has_no_promotion_logic():
    """§13's implicit inheritance of §10.9's rule: no promotion logic may
    exist inside the strategy. Static check on executable code only."""
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
