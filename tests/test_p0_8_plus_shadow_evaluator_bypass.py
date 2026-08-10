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


def test_signal_router_source_has_no_forbidden_invocation_pattern():
    """Belt-and-braces plain-text check (mirrors
    test_signal_router_bypass.py's identically-named test) in case a future
    edit references a forbidden name through a string/getattr the AST
    Call/Import scan above wouldn't catch. Docstring excluded (it
    legitimately discusses these names -- that's the point of documenting
    the bypass guarantee)."""
    tree = ast.parse((REPO / MODULE).read_text(encoding="utf-8"))
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body = tree.body[1:]
    code_only = ast.unparse(tree)
    for forbidden in FORBIDDEN_ENTRY_SYMBOLS | FORBIDDEN_ENTRY_MODULES:
        assert forbidden not in code_only, (
            f"{MODULE}'s executable code (docstring excluded) references forbidden name: {forbidden}"
        )


def _strong_uptrend_candles(n=220, start_price=1000.0, drift_bps_per_bar=15.0, range_mult=1.005):
    """Same shape/magnitude fixture strategy_trend_cost_aware_v1's own
    tests use to reliably produce an admitted candidate (§10 tests,
    drift=15bps/bar, range_mult=0.5% -- "wide enough that the ATR-based
    projection cap in _expected_move_bps() doesn't floor every scenario to
    a few bps", per that test file's own fixture docstring). A tighter
    range (e.g. the previous 0.05% high/low used here before) produces a
    smaller ATR, which floors the projected move below the round-trip
    cost and reliably yields ZERO candidates -- which made the runtime-spy
    test below vacuous: the `for signal in signals:` loop (where a real
    regression reaching open_paper_position would actually live) never
    executed, so the test passed regardless of what that loop contained.
    Found by an independent audit (trading-safety-agent, 2026-08-10) via
    mutation testing: a planted `if signals: pte.open_paper_position(...)`
    was NOT caught by this test as it stood."""
    candles = []
    price = start_price
    for i in range(n):
        open_p = price
        close_p = price * (1 + drift_bps_per_bar / 10_000.0)
        high_p = max(open_p, close_p) * range_mult
        low_p = min(open_p, close_p) * (2 - range_mult)
        candles.append({
            "open_time": 1_700_000_000_000 + i * 60_000,
            "open": open_p, "high": high_p, "low": low_p,
            "close": close_p, "volume": 10.0,
        })
        price = close_p
    return candles


def test_module_never_opens_a_position_at_runtime(monkeypatch):
    import src.services.paper_trade_executor as pte

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("p0_8_plus_shadow_evaluator reached open_paper_position()!")

    monkeypatch.setattr(pte, "open_paper_position", _must_not_be_called, raising=True)

    from src.services import p0_8_plus_shadow_evaluator as shadow
    from src.services.candle_cache_v1 import CandleCache
    from src.services.strategy_registry import StrategyRegistry

    # Confirm the router's admission-evaluation loop is actually exercised
    # (not just that generate_candidates() ran) -- a real spy on the
    # forbidden call alone doesn't prove the surrounding loop body ran.
    router_calls = {"n": 0}
    real_evaluate = shadow.signal_router.evaluate_signal_for_paper_entry

    def _counting_evaluate(*args, **kwargs):
        router_calls["n"] += 1
        return real_evaluate(*args, **kwargs)

    monkeypatch.setattr(shadow.signal_router, "evaluate_signal_for_paper_entry", _counting_evaluate)

    candles = _strong_uptrend_candles()
    cache = CandleCache(fetch_fn=lambda symbol, interval: candles)
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    shadow.evaluate_symbol("ETHUSDT", cache=cache, registry=reg)
    shadow.run_shadow_tick(symbols=["ETHUSDT"], cache=cache)
    # If we reach here, open_paper_position was never called.
    assert router_calls["n"] >= 1, (
        "fixture produced zero candidates -- this test proves nothing about "
        "the loop that evaluates them; see _strong_uptrend_candles() docstring"
    )
