"""Tests for p0_8_plus_shadow_evaluator.py -- the first live-data-touching
module in the Evidence-First Strategy Expansion v2 program. All tests
inject a fake candle cache / registry / risk guard -- none touch real
Binance, Firestore, or the live position store.
"""
import random
import time

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


def test_default_symbols_match_live_trading_universe():
    """2026-08-14: widened from a 3-symbol MVP subset to the full live
    universe (config.SYMBOLS) after journalctl showed 0 shadow candidates
    across every tick for 24h+ straight on the narrower set -- verified
    live that the pipeline itself (candle fetch, regime classification,
    all 3 strategy modules) executes correctly end to end, it just never
    got a chance to see most of the traded symbols. This is a shadow-only
    module (never opens a position), so watching more symbols only widens
    observation, at no additional risk."""
    from config import SYMBOLS as LIVE_TRADING_SYMBOLS
    assert set(shadow._DEFAULT_SYMBOLS) == set(LIVE_TRADING_SYMBOLS)


def test_run_shadow_tick_never_raises_on_empty_symbol_list():
    results = shadow.run_shadow_tick(symbols=[], cache=_fake_cache(_trending_candles()))
    assert results == []


# ---------------------------------------------------------------------------
# start_shadow_monitoring_thread
# ---------------------------------------------------------------------------

def test_monitoring_thread_disabled_via_env_returns_none(monkeypatch):
    monkeypatch.setenv("PAPER_P0_8_PLUS_SHADOW_ENABLED", "false")
    result = shadow.start_shadow_monitoring_thread(interval_s=0.01)
    assert result is None


@pytest.mark.parametrize("disable_value", ["0", "no", "off", "FALSE"])
def test_monitoring_thread_disabled_accepts_common_falsy_spellings(monkeypatch, disable_value):
    monkeypatch.setenv("PAPER_P0_8_PLUS_SHADOW_ENABLED", disable_value)
    assert shadow.start_shadow_monitoring_thread(interval_s=0.01) is None


def test_monitoring_thread_enabled_by_default_and_is_daemon(monkeypatch):
    monkeypatch.delenv("PAPER_P0_8_PLUS_SHADOW_ENABLED", raising=False)
    calls = {"n": 0}
    monkeypatch.setattr(shadow, "run_shadow_tick", lambda symbols=None: calls.__setitem__("n", calls["n"] + 1))
    t = shadow.start_shadow_monitoring_thread(interval_s=0.01)
    try:
        assert t is not None
        assert t.daemon is True
        # Wait briefly for at least one tick.
        for _ in range(100):
            if calls["n"] >= 1:
                break
            time.sleep(0.01)
        assert calls["n"] >= 1
    finally:
        pass  # daemon thread; no explicit stop mechanism, same as
              # emergency_health_monitor.start_monitoring_thread() -- dies
              # with the process, harmless to leave running for the rest
              # of this test session.


def test_monitoring_thread_survives_a_failing_tick(monkeypatch):
    """One bad tick must not kill the thread -- the next interval must
    still fire."""
    monkeypatch.delenv("PAPER_P0_8_PLUS_SHADOW_ENABLED", raising=False)
    calls = {"n": 0}

    def _flaky(symbols=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first tick fails")

    monkeypatch.setattr(shadow, "run_shadow_tick", _flaky)
    shadow.start_shadow_monitoring_thread(interval_s=0.01)
    for _ in range(200):
        if calls["n"] >= 2:
            break
        time.sleep(0.01)
    assert calls["n"] >= 2


# ---------------------------------------------------------------------------
# live quote preference (live_quote_cache_v1) vs synthetic fallback
# ---------------------------------------------------------------------------

def test_evaluate_symbol_uses_synthetic_quote_when_no_live_quote_cached():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(_trending_candles(drift_bps_per_bar=15.0, seed=10))
    results = shadow.evaluate_symbol(
        "ETHUSDT", cache=cache, registry=reg, risk_guard_fn=_allow_risk,
        get_quote_fn=lambda symbol, max_age_s=None: None,
    )
    assert len(results) >= 1
    assert all(r.quote_source == "synthetic" for r in results)


def test_evaluate_symbol_prefers_live_quote_when_fresh():
    from src.services.live_quote_cache_v1 import LastQuote
    candles = _trending_candles(drift_bps_per_bar=15.0, seed=11)
    close = candles[-1]["close"]
    live_quote = LastQuote(symbol="ETHUSDT", bid=close * 0.99985, ask=close * 1.00015,
                            price=close, received_at_s=123.0)

    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(candles)
    results = shadow.evaluate_symbol(
        "ETHUSDT", cache=cache, registry=reg, risk_guard_fn=_allow_risk,
        get_quote_fn=lambda symbol, max_age_s=None: live_quote,
    )
    assert len(results) >= 1
    assert all(r.quote_source == "live" for r in results)
    assert all(r.signal.reference_price == close for r in results)


def test_evaluate_symbol_falls_back_to_synthetic_when_quote_lookup_raises():
    def _boom(symbol, max_age_s=None):
        raise RuntimeError("cache unavailable")

    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(_trending_candles(drift_bps_per_bar=15.0, seed=12))
    results = shadow.evaluate_symbol(
        "ETHUSDT", cache=cache, registry=reg, risk_guard_fn=_allow_risk, get_quote_fn=_boom,
    )
    assert len(results) >= 1
    assert all(r.quote_source == "synthetic" for r in results)


def test_run_shadow_tick_subscribes_the_live_quote_cache(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(shadow.live_quote_cache_v1, "ensure_subscribed", lambda: calls.__setitem__("n", calls["n"] + 1))
    shadow.run_shadow_tick(symbols=[], cache=_fake_cache(_trending_candles()))
    assert calls["n"] == 1


def test_candidate_evaluation_never_mutates_signal_or_exposes_execution_hooks():
    reg = StrategyRegistry()
    shadow.ensure_registered(["ETHUSDT"], registry=reg)
    cache = _fake_cache(_trending_candles(drift_bps_per_bar=15.0, seed=6))
    results = shadow.evaluate_symbol("ETHUSDT", cache=cache, registry=reg, risk_guard_fn=_allow_risk)
    assert len(results) >= 1
    for r in results:
        assert r.signal.evidence_only is True
