"""§22.3 bypass architecture test for p0_8_plus_shadow_evaluator.py.

This module STRUCTURALLY CANNOT open a position -- it must never call or
import open_paper_position or any other entry primitive, and must never
import trade_executor/execution_engine/paper_training_sampler/
paper_exploration. paper_trade_executor is not needed by this module at
all (unlike p0_risk_guard_v1.py, which legitimately reads open positions)
and must not appear here either.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = "src/services/p0_8_plus_shadow_evaluator.py"

FORBIDDEN_ENTRY_SYMBOLS = {
    "open_paper_position", "open_position", "place_order",
    "create_order", "maybe_open_training_sample",
}
FORBIDDEN_ENTRY_MODULES = {
    "paper_trade_executor", "trade_executor", "paper_training_sampler",
    "paper_exploration", "execution_engine",
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


def test_module_never_opens_a_position_at_runtime(monkeypatch):
    import src.services.paper_trade_executor as pte

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("p0_8_plus_shadow_evaluator reached open_paper_position()!")

    monkeypatch.setattr(pte, "open_paper_position", _must_not_be_called, raising=True)

    from src.services import p0_8_plus_shadow_evaluator as shadow
    from src.services.candle_cache_v1 import CandleCache
    from src.services.strategy_registry import StrategyRegistry

    candles = []
    price = 1000.0
    for i in range(220):
        price *= 1.0006
        candles.append({
            "open_time": 1_700_000_000_000 + i * 60_000,
            "open": price, "high": price * 1.0005, "low": price * 0.9995,
            "close": price, "volume": 10.0,
        })
    cache = CandleCache(fetch_fn=lambda symbol, interval: candles)
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    shadow.evaluate_symbol("ETHUSDT", cache=cache, registry=reg)
    shadow.run_shadow_tick(symbols=["ETHUSDT"], cache=cache)
    # If we reach here, open_paper_position was never called.
