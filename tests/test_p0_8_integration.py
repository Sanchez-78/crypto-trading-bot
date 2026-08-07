"""P0.8 end-to-end integration (§22.2): market data -> feature -> candidate
-> signal -> cost evaluation -> P0 admit/reject -> (risk gap, honestly
reported). Proves strategy_trend_cost_aware_v1.py and signal_router.py
actually compose, not just pass in isolation.
"""
from src.services import strategy_trend_cost_aware_v1 as trend
from src.services.signal_router import evaluate_signal_for_paper_entry
from src.services.strategy_registry import StrategyRegistry


def _uptrend_candles(n=220, drift_bps=15.0, seed=42, range_mult=1.005):
    """range_mult default matches test_strategy_trend_cost_aware_v1.py's
    _make_candles -- a realistic ~0.5%/bar range, wide enough that the
    ATR-capped expected-move projection can clear the round-trip cost floor
    for a genuinely strong trend (see that file's docstring for why a
    tighter range makes a net-edge-positive fixture impossible to construct)."""
    import random
    rng = random.Random(seed)
    candles = []
    price = 1900.0
    t0 = 1_700_000_000_000
    for i in range(n):
        price = max(0.01, price * (1 + drift_bps / 10_000.0) + price * rng.uniform(-0.0002, 0.0002))
        candles.append({
            "open_time": t0 + i * 60_000,
            "open": price, "high": price * range_mult, "low": price * (2 - range_mult),
            "close": price, "volume": 12.0,
        })
    return candles


def test_end_to_end_uptrend_signal_reaches_router_and_is_evaluated():
    candles = _uptrend_candles()
    registry = StrategyRegistry()
    registry.register(trend.build_registration().__class__(
        strategy_id=trend.STRATEGY_ID,
        current_version=trend.STRATEGY_VERSION,
        enabled=True,
        evidence_only=True,
        allowed_symbols=frozenset({"ETHUSDT"}),
        allowed_regimes=frozenset({"BULL_TREND", "BEAR_TREND"}),
        allowed_sides=frozenset({"BUY", "SELL"}),
        exit_profile=trend.EXIT_PROFILE,
        minimum_warmup_seconds=0,
        required_feature_schema_version=trend.FEATURE_SCHEMA_VERSION,
    ))

    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=lambda *a: "sig-e2e-1",
        now_ms=candles[-1]["open_time"] + 50,
    )
    assert len(signals) >= 1
    sig = signals[0]

    evaluation = evaluate_signal_for_paper_entry(
        sig, registry=registry,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        requested_notional=25.0, visible_top_notional=1000.0,
        realized_volatility_bps=10.0, realized_volatility_bps_per_second=0.5,
        decision_latency_ms=30.0, now_ms=candles[-1]["open_time"] + 60,
    )

    # It must reach a real decision, not error out, and must not be
    # silently admitted (no risk guard exists yet -- P0.7 gap, honestly
    # surfaced end-to-end here too, not just at the router-unit-test level).
    assert evaluation.signal_id == sig.signal_id
    assert evaluation.admitted is False
    assert evaluation.risk_allowed is False
    assert evaluation.p0_segment_key == f"ETHUSDT:BUY:BULL_TREND:{trend.LEARNING_SOURCE}:{trend.EXIT_PROFILE}"


def test_end_to_end_rejected_candidate_never_reaches_router_as_a_signal():
    """A regime the strategy's own gate rejects produces zero signals --
    the router is never even invoked, which is the correct/expected shape
    (§10.7's candidate vs signal separation: an unadmitted candidate is not
    a StrategySignal at all)."""
    candles = _uptrend_candles(drift_bps=6.0, seed=43)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=lambda *a: "sig-e2e-2",
        now_ms=candles[-1]["open_time"] + 50,
    )
    assert signals == []
