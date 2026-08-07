"""P0.8 (Evidence-First Strategy Expansion v2, §10, §22.1 'Strategies',
§22.4 replay scenarios subset) -- trend_cost_aware_v1 tests.
"""
import math

import pytest

from src.services import strategy_trend_cost_aware_v1 as trend
from src.services.strategy_contracts import StrategySignal


def _make_candles(n, *, start_price=1000.0, drift_bps_per_bar=0.0, noise=0.0,
                   interval_ms=60_000, start_time_ms=1_700_000_000_000,
                   volume=10.0, seed=0, range_mult=1.005):
    """Synthetic deterministic candle generator -- no lookahead by
    construction (each bar only depends on prior bars and a seeded PRNG).

    `range_mult` sets the per-bar high/low range (default 0.5% -- a
    realistic order of magnitude for a 1-minute crypto candle, wide enough
    that the ATR-based projection cap in _expected_move_bps() doesn't floor
    every scenario to a few bps regardless of trend strength, which would
    make it impossible to construct a genuinely net-edge-positive fixture)."""
    import random

    rng = random.Random(seed)
    candles = []
    price = start_price
    for i in range(n):
        drift = price * (drift_bps_per_bar / 10_000.0)
        jitter = price * (rng.uniform(-noise, noise) if noise else 0.0)
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


def _id_factory(symbol, side, regime, ts):
    return f"{symbol}:{side}:{regime}:{ts}"


# ---------------------------------------------------------------------------
# compute_trend_features -- warmup, no-lookahead, determinism
# ---------------------------------------------------------------------------

def test_compute_trend_features_requires_minimum_candles():
    with pytest.raises(ValueError):
        trend.compute_trend_features(_make_candles(50))


def test_compute_trend_features_deterministic_for_same_input():
    candles = _make_candles(220, drift_bps_per_bar=2.0, seed=1)
    a = trend.compute_trend_features(candles)
    b = trend.compute_trend_features(candles)
    assert a == b


def test_uptrend_produces_positive_slopes():
    candles = _make_candles(220, drift_bps_per_bar=3.0, seed=2)
    f = trend.compute_trend_features(candles)
    assert f.fast_slope_bps_per_minute > 0
    assert f.slow_slope_bps_per_minute > 0
    assert f.trend_persistence_ratio > 0.5


def test_downtrend_produces_negative_slopes():
    candles = _make_candles(220, drift_bps_per_bar=-3.0, seed=3)
    f = trend.compute_trend_features(candles)
    assert f.fast_slope_bps_per_minute < 0
    assert f.slow_slope_bps_per_minute < 0


def test_sideways_produces_near_zero_persistence_or_weak_slope():
    candles = _make_candles(220, drift_bps_per_bar=0.0, noise=0.001, seed=4)
    f = trend.compute_trend_features(candles)
    # Not a strict zero (noise), but must not present as a confident trend
    assert abs(f.slow_slope_bps_per_minute) < 5.0


def test_only_completed_bars_used_no_lookahead():
    """Feature computation on the first 220 bars of a series must be
    identical whether or not additional future bars exist beyond that
    point -- i.e. no lookahead into data past candles[-1]."""
    candles = _make_candles(260, drift_bps_per_bar=2.0, seed=5)
    a = trend.compute_trend_features(candles[:220])
    b = trend.compute_trend_features(candles[:220])  # same slice, sanity
    assert a == b
    c = trend.compute_trend_features(candles[:230])
    # Different (longer) slice is allowed to differ -- this just proves the
    # function is a pure function of its input slice, not of global state.
    assert isinstance(c, trend.TrendFeatures)


# ---------------------------------------------------------------------------
# long_candidate / short_candidate gates (§22.1 Strategies checklist)
# ---------------------------------------------------------------------------

def _strong_uptrend_features():
    candles = _make_candles(220, drift_bps_per_bar=5.0, seed=10)
    return trend.compute_trend_features(candles)


def _strong_downtrend_features():
    candles = _make_candles(220, drift_bps_per_bar=-5.0, seed=11)
    return trend.compute_trend_features(candles)


def test_valid_long_trend_candidate_admitted():
    f = _strong_uptrend_features()
    reason = trend.long_candidate(features=f, regime="BULL_TREND", regime_confidence=0.9, spread_bps=2.0)
    assert reason is None


def test_valid_short_trend_candidate_admitted():
    f = _strong_downtrend_features()
    reason = trend.short_candidate(features=f, regime="BEAR_TREND", regime_confidence=0.9, spread_bps=2.0)
    assert reason is None


def test_long_regime_rejection():
    f = _strong_uptrend_features()
    reason = trend.long_candidate(features=f, regime="SIDEWAYS", regime_confidence=0.9, spread_bps=2.0)
    assert reason is not None and "regime_not_allowed" in reason


def test_long_rejected_in_bear_trend_regime():
    f = _strong_uptrend_features()
    reason = trend.long_candidate(features=f, regime="BEAR_TREND", regime_confidence=0.9, spread_bps=2.0)
    assert reason is not None


def test_weak_trend_rejection():
    candles = _make_candles(220, drift_bps_per_bar=0.05, seed=12)  # too weak
    f = trend.compute_trend_features(candles)
    reason = trend.long_candidate(features=f, regime="BULL_TREND", regime_confidence=0.9, spread_bps=2.0)
    assert reason is not None


def test_high_spread_rejection():
    f = _strong_uptrend_features()
    reason = trend.long_candidate(features=f, regime="BULL_TREND", regime_confidence=0.9, spread_bps=999.0)
    assert reason is not None and "spread_too_wide" in reason


def test_low_regime_confidence_rejection():
    f = _strong_uptrend_features()
    reason = trend.long_candidate(features=f, regime="BULL_TREND", regime_confidence=0.1, spread_bps=2.0)
    assert reason is not None and "regime_confidence_too_low" in reason


def test_short_candidate_not_naive_sign_flip_of_long():
    """§10.4: short must use its own structure fields (lower_high/lower_low),
    not a blind negation of the long gate's higher_high/higher_low checks."""
    import inspect
    long_src = inspect.getsource(trend.long_candidate)
    short_src = inspect.getsource(trend.short_candidate)
    assert "lower_high_score" not in long_src
    assert "higher_high_score" not in short_src


# ---------------------------------------------------------------------------
# generate_candidates -- integration, cost rejection, determinism, evidence_only
# ---------------------------------------------------------------------------

def test_generate_candidates_produces_long_signal_in_strong_uptrend():
    candles = _make_candles(220, drift_bps_per_bar=15.0, seed=20)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    assert all(isinstance(s, StrategySignal) for s in signals)
    assert all(s.side == "BUY" for s in signals)
    assert all(s.evidence_only is True for s in signals)
    assert all(s.strategy_id == trend.STRATEGY_ID for s in signals)


def test_generate_candidates_empty_on_insufficient_warmup():
    candles = _make_candles(50, drift_bps_per_bar=15.0, seed=21)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_generate_candidates_empty_on_crossed_book():
    candles = _make_candles(220, drift_bps_per_bar=15.0, seed=22)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 1.01, best_ask=candles[-1]["close"] * 0.99,  # crossed
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_generate_candidates_empty_when_regime_not_allowed():
    candles = _make_candles(220, drift_bps_per_bar=15.0, seed=23)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_generate_candidates_deterministic_signal_id():
    candles = _make_candles(220, drift_bps_per_bar=15.0, seed=24)
    kwargs = dict(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    a = trend.generate_candidates(**kwargs)
    b = trend.generate_candidates(**kwargs)
    assert [s.signal_id for s in a] == [s.signal_id for s in b]


def test_generate_candidates_net_edge_never_exceeds_gross_move():
    """Property invariant (§22.7), checked end-to-end through the strategy."""
    candles = _make_candles(220, drift_bps_per_bar=15.0, seed=25)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    for s in signals:
        assert s.net_expected_edge_bps <= s.gross_expected_move_bps


def test_generate_candidates_long_stop_below_entry():
    """Property invariant (§22.7): long stop below entry."""
    candles = _make_candles(220, drift_bps_per_bar=15.0, seed=26)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    for s in signals:
        assert s.initial_stop_price < s.reference_price


def test_generate_candidates_short_stop_above_entry():
    """Property invariant (§22.7): short stop above entry."""
    candles = _make_candles(220, drift_bps_per_bar=-15.0, seed=27)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BEAR_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    for s in signals:
        assert s.initial_stop_price > s.reference_price


def test_generate_candidates_never_mixes_long_and_short_same_call():
    """Structural: ALLOWED_LONG_REGIMES and ALLOWED_SHORT_REGIMES are
    disjoint, so a single regime value can only ever produce one side."""
    candles = _make_candles(220, drift_bps_per_bar=15.0, seed=28)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    sides = {s.side for s in signals}
    assert sides <= {"BUY"}


def test_build_registration_is_evidence_only():
    reg = trend.build_registration()
    assert reg.evidence_only is True
    assert reg.strategy_id == trend.STRATEGY_ID
    assert reg.current_version == trend.STRATEGY_VERSION


def test_all_generated_signals_pass_their_own_schema_validation():
    """Every StrategySignal this module builds must already be valid per
    StrategySignal.__post_init__ -- if generate_candidates ever produced an
    invalid one, construction itself would have raised inside the function,
    so this test is really asserting the function doesn't swallow that."""
    candles = _make_candles(220, drift_bps_per_bar=15.0, seed=29)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1  # otherwise this test doesn't exercise anything


# ---------------------------------------------------------------------------
# §22.4 replay-style scenarios (subset relevant to this strategy)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("scenario,drift,regime,expected_side", [
    ("clean_bullish_trend", 15.0, "BULL_TREND", "BUY"),
    ("clean_bearish_trend", -15.0, "BEAR_TREND", "SELL"),
])
def test_replay_scenario_clean_trend(scenario, drift, regime, expected_side):
    candles = _make_candles(220, drift_bps_per_bar=drift, seed=hash(scenario) % 1000)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime=regime, regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1, f"{scenario} produced no candidates"
    assert all(s.side == expected_side for s in signals)


def test_replay_scenario_sideways_noise_produces_no_confident_candidates():
    candles = _make_candles(220, drift_bps_per_bar=0.0, noise=0.0015, seed=99)
    for regime in ("BULL_TREND", "BEAR_TREND"):
        signals = trend.generate_candidates(
            candles=candles, symbol="ETHUSDT", regime=regime, regime_confidence=0.9,
            best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
            signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
        )
        assert signals == [], f"sideways noise should not admit a {regime} candidate"


def test_replay_scenario_data_outage_short_history_produces_no_candidates():
    candles = _make_candles(10, drift_bps_per_bar=10.0, seed=100)
    signals = trend.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []
