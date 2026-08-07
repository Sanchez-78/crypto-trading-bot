"""P1.0 Sec 22.3 bypass architecture test for dynamic_trend_exit_v1.py.

This module returns exit DECISIONS -- it never closes a position itself and
never opens a new (opposite) entry (Sec 12.6: "An exit signal must not
automatically become an opposite entry signal").
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE = "src/services/dynamic_trend_exit_v1.py"

FORBIDDEN_SYMBOLS = {
    "open_paper_position", "open_position", "place_order", "create_order",
    "maybe_open_training_sample", "close_position", "record_close",
}
FORBIDDEN_MODULES = {
    "paper_trade_executor", "trade_executor", "paper_training_sampler",
    "paper_exploration", "execution_engine",
}


def test_module_has_no_forbidden_symbol_calls():
    src = (REPO / MODULE).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=MODULE)
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    hit = called & FORBIDDEN_SYMBOLS
    assert not hit, f"{MODULE} calls forbidden symbol(s): {hit}"


def test_module_has_no_forbidden_module_imports():
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
    hit = imported & FORBIDDEN_MODULES
    assert not hit, f"{MODULE} imports forbidden module(s): {hit}"


def test_evaluate_exit_never_constructs_a_strategy_signal():
    """Sec 12.6: an exit must not automatically become an opposite entry
    signal -- this module must not even import StrategySignal."""
    src = (REPO / MODULE).read_text(encoding="utf-8")
    assert "StrategySignal(" not in src
