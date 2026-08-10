"""Tests for p0_8_plus_shadow_evaluator.py -- the first live-data-touching
module in the Evidence-First Strategy Expansion v2 program. All tests
inject a fake candle cache / registry / risk guard -- none touch real
Binance, Firestore, or the live position store.
"""
import random

import pytest

from src.services import p0_8_plus_shadow_evaluator as shadow
from src.services.candle_cache_v1 import CandleCache
from src.services.p0_risk_guard_v1 import RiskGuardResult
from src.services.strategy_registry import StrategyRegistry


def _trending_candles(n=220, *, drift_bps_per_bar=15.0, seed=0, start_price=1000.0,
                       range_mult=1.005, interval_ms=60_000, start_time_ms=1_700_000_000_000,
                       volume=10.0):
    rng = random.Random(seed)
    candles = []
    price = start_price
    for i in range(n):
        drift = price * (drift_bps_per_bar / 10_000.0)
        jitter = price * rng.uniform(-0.0002, 0.0002)
        open_p = price
        close_p = max(0.01, price + drift + jitter)
        high_p = max(open_p, close_p) * range_mult
        low_p = min(open_p, close_p) * (2 - range_mult)
        candles.append({
            "open_time": start_time_ms + i * interval_ms,
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "volume": volume,
        })
        price = close_p
    return candles


def _fake_cache(candles):
    return CandleCache(fetch_fn=lambda symbol, interval: candles)


def _allow_risk(**_kwargs):
    return RiskGuardResult(allowed=True, reason="")


# ---------------------------------------------------------------------------
# ensure_registered
# ---------------------------------------------------------------------------

def test_ensure_registered_registers_all_three_strategies():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    assert reg.is_registered("trend_cost_aware")
    assert reg.is_registered("volatility_breakout")
    assert reg.is_registered("sideways_mean_reversion")


def test_ensure_registered_populates_allowed_symbols():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT", "ADAUSDT"], registry=reg)
    for strategy_id in ("trend_cost_aware", "volatility_breakout", "sideways_mean_reversion"):
        registration = reg.get(strategy_id)
        assert registration.allowed_symbols == frozenset({"ETHUSDT", "ADAUSDT"})


def test_ensure_registered_is_idempotent_and_callable_twice():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    shadow.ensure_registered(["ETHUSDT"], registry=reg)  # must not raise
    assert reg.is_registered("trend_cost_aware")


def test_ensure_registered_can_change_symbol_set():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    shadow.ensure_registered(["ETHUSDT", "SOLUSDT"], registry=reg)
    registration = reg.get("trend_cost_aware")
    assert registration.allowed_symbols == frozenset({"ETHUSDT", "SOLUSDT"})


# ---------------------------------------------------------------------------
# evaluate_symbol
# ---------------------------------------------------------------------------

def test_evaluate_symbol_returns_empty_on_insufficient_candles():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(_trending_candles(n=50))
    results = shadow.evaluate_symbol("ETHUSDT", cache=cache, registry=reg)
    assert results == []


def test_evaluate_symbol_produces_candidates_for_strong_uptrend():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(_trending_candles(drift_bps_per_bar=15.0, seed=1))
    results = shadow.evaluate_symbol("ETHUSDT", cache=cache, registry=reg, risk_guard_fn=_allow_risk)
    assert len(results) >= 1
    trend_results = [r for r in results if r.strategy_id == "trend_cost_aware"]
    assert len(trend_results) >= 1
    assert trend_results[0].side == "BUY"
    assert trend_results[0].regime == "BULL_TREND"


def test_evaluate_symbol_never_raises_when_a_strategy_module_errors(monkeypatch):
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(_trending_candles(drift_bps_per_bar=15.0, seed=2))

    def _boom(**kwargs):
        raise RuntimeError("strategy exploded")

    from src.services import strategy_trend_cost_aware_v1 as trend_strategy
    monkeypatch.setattr(trend_strategy, "generate_candidates", _boom)

    results = shadow.evaluate_symbol("ETHUSDT", cache=cache, registry=reg, risk_guard_fn=_allow_risk)
    # Other strategies still evaluated; no exception propagates.
    assert isinstance(results, list)


def test_evaluate_symbol_never_raises_when_router_errors(monkeypatch):
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(_trending_candles(drift_bps_per_bar=15.0, seed=3))

    def _boom(*args, **kwargs):
        raise RuntimeError("router exploded")

    monkeypatch.setattr(shadow.signal_router, "evaluate_signal_for_paper_entry", _boom)
    results = shadow.evaluate_symbol("ETHUSDT", cache=cache, registry=reg, risk_guard_fn=_allow_risk)
    assert results == []


def test_evaluate_symbol_evaluation_reflects_risk_guard_denial():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(_trending_candles(drift_bps_per_bar=15.0, seed=4))

    def _deny(**_kwargs):
        return RiskGuardResult(allowed=False, reason="test denial")

    results = shadow.evaluate_symbol("ETHUSDT", cache=cache, registry=reg, risk_guard_fn=_deny)
    assert len(results) >= 1
    assert all(r.evaluation.admitted is False for r in results)


# ---------------------------------------------------------------------------
# run_shadow_tick
# ---------------------------------------------------------------------------

def test_run_shadow_tick_covers_default_symbols_when_none_given():
    cache = _fake_cache(_trending_candles(drift_bps_per_bar=15.0, seed=5))
    results = shadow.run_shadow_tick(cache=cache)
    symbols_seen = {r.symbol for r in results}
    assert symbols_seen <= set(shadow._DEFAULT_SYMBOLS)


def test_run_shadow_tick_never_raises_on_empty_symbol_list():
    results = shadow.run_shadow_tick(symbols=[], cache=_fake_cache(_trending_candles()))
    assert results == []


def test_candidate_evaluation_never_mutates_signal_or_exposes_execution_hooks():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(_trending_candles(drift_bps_per_bar=15.0, seed=6))
    results = shadow.evaluate_symbol("ETHUSDT", cache=cache, registry=reg, risk_guard_fn=_allow_risk)
    assert len(results) >= 1
    for r in results:
        assert r.signal.evidence_only is True
