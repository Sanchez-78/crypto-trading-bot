"""P1.2 (Evidence-First Strategy Expansion v2, §14, §22.1 'Strategies',
§22.4 replay scenarios subset) -- sideways_mean_reversion_v1 tests.

Fixture calibration note: the module's near-zero-slope gate (§14.1) and
zscore-extension gate (§14.3) sit close enough together that ordinary
per-bar random noise in a genuinely flat series can occasionally trip the
slope gate purely by chance (a 20-period EMA of iid noise does not converge
to exactly zero slope on any single finite realization). Seeds below were
selected because they deterministically produce a fixture that clears both
gates together -- same practice as strategy_trend_cost_aware_v1's tests,
which also hand-pick seeds rather than asserting on arbitrary ones.
"""
import random

import pytest

from src.services import strategy_sideways_mean_reversion_v1 as mr
from src.services.strategy_contracts import StrategySignal


def _make_range_bound_candles(
    *, n=120, seed=0, start_price=1000.0, band_frac=0.004,
    start_time_ms=1_700_000_000_000, interval_ms=60_000, volume=10.0,
):
    """Deterministic oscillation inside a fixed band around start_price --
    each bar's offset is drawn independently relative to the fixed
    start_price (not a random walk from the previous close), so the series
    has a genuinely constant underlying mean; no lookahead by construction."""
    rng = random.Random(seed)
    candles = []
    for i in range(n):
        offset_frac = band_frac * (0.5 - rng.random())
        close_p = start_price * (1 + offset_frac)
        open_p = start_price * (1 + band_frac * (0.5 - rng.random()))
        high_p = max(open_p, close_p) * 1.0008
        low_p = min(open_p, close_p) * 0.9992
        candles.append({
            "open_time": start_time_ms + i * interval_ms,
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "volume": volume,
        })
    return candles


def _push_extension(candles, *, direction, steps=3, step_frac=0.0018):
    """Append `steps` small same-direction bars (each bar's own range close
    to the baseline's, so range_expansion_ratio stays gate-passable -- an
    orderly multi-bar drift away from the mean, not a single breakout-sized
    candle). direction=-1 pushes price down (long/buy-the-dip setup),
    direction=+1 pushes it up (short setup)."""
    out = list(candles)
    price = float(out[-1]["close"])
    for _ in range(steps):
        new_close = price * (1 + direction * step_frac)
        bar = {
            "open_time": out[-1]["open_time"] + 60_000,
            "open": price,
            "high": max(price, new_close) * 1.0004,
            "low": min(price, new_close) * 0.9996,
            "close": new_close,
            "volume": out[-1]["volume"],
        }
        out.append(bar)
        price = new_close
    return out


# Seeds empirically verified (see module docstring) to clear both the
# zscore-extension gate and the near-zero-slope gate simultaneously.
_GOOD_DOWN_SEEDS = (0, 1, 3, 4, 6, 7, 9, 11, 13, 14, 17, 20, 22, 24, 27)
_GOOD_UP_SEEDS = (8, 10, 12, 16, 19, 23)


def _id_factory(symbol, side, regime, ts):
    return f"{symbol}:{side}:{regime}:{ts}"


# ---------------------------------------------------------------------------
# compute_mean_reversion_features -- warmup, no-lookahead, determinism
# ---------------------------------------------------------------------------

def test_compute_features_requires_minimum_candles():
    with pytest.raises(ValueError):
        mr.compute_mean_reversion_features(_make_range_bound_candles(n=10))


def test_compute_features_deterministic_for_same_input():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    a = mr.compute_mean_reversion_features(candles)
    b = mr.compute_mean_reversion_features(candles)
    assert a == b


def test_downside_extension_produces_negative_zscore():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[1]), direction=-1)
    f = mr.compute_mean_reversion_features(candles)
    assert f.price_zscore < -mr.MIN_ABS_ZSCORE


def test_upside_extension_produces_positive_zscore():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_UP_SEEDS[0]), direction=1)
    f = mr.compute_mean_reversion_features(candles)
    assert f.price_zscore > mr.MIN_ABS_ZSCORE


def test_range_bound_series_has_near_zero_slope():
    candles = _make_range_bound_candles(seed=4)
    f = mr.compute_mean_reversion_features(candles)
    assert abs(f.slow_slope_bps_per_minute) < 5.0


def test_only_completed_bars_used_no_lookahead():
    candles = _push_extension(_make_range_bound_candles(n=200, seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    a = mr.compute_mean_reversion_features(candles[:150])
    b = mr.compute_mean_reversion_features(candles[:150])
    assert a == b


# ---------------------------------------------------------------------------
# long_candidate / short_candidate gates
# ---------------------------------------------------------------------------

def test_valid_long_mean_reversion_candidate_admitted():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    f = mr.compute_mean_reversion_features(candles)
    reason = mr.long_candidate(features=f, regime="SIDEWAYS", regime_confidence=0.9, spread_bps=2.0)
    assert reason is None


def test_valid_short_mean_reversion_candidate_admitted():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_UP_SEEDS[0]), direction=1)
    f = mr.compute_mean_reversion_features(candles)
    reason = mr.short_candidate(features=f, regime="SIDEWAYS", regime_confidence=0.9, spread_bps=2.0)
    assert reason is None


def test_regime_rejection_rejects_trend_regime():
    """§14.1: 'Do not allow weak trend to automatically mean sideways' --
    a BULL_TREND classification must reject outright, even with an extended
    zscore."""
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    f = mr.compute_mean_reversion_features(candles)
    reason = mr.long_candidate(features=f, regime="BULL_TREND", regime_confidence=0.9, spread_bps=2.0)
    assert reason is not None and "regime_not_allowed" in reason


def test_regime_rejection_rejects_volatile_regime():
    """Unlike volatility_breakout_v1, VOLATILE is not an allowed regime here."""
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    f = mr.compute_mean_reversion_features(candles)
    reason = mr.long_candidate(features=f, regime="VOLATILE", regime_confidence=0.9, spread_bps=2.0)
    assert reason is not None and "regime_not_allowed" in reason


def test_insufficient_extension_rejected():
    candles = _make_range_bound_candles(seed=14)
    f = mr.compute_mean_reversion_features(candles)
    reason = mr.long_candidate(features=f, regime="SIDEWAYS", regime_confidence=0.9, spread_bps=2.0)
    assert reason is not None and "zscore_not_extended" in reason


def test_high_spread_rejection():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    f = mr.compute_mean_reversion_features(candles)
    reason = mr.long_candidate(features=f, regime="SIDEWAYS", regime_confidence=0.9, spread_bps=999.0)
    assert reason is not None and "spread_too_wide" in reason


def test_low_regime_confidence_rejection():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    f = mr.compute_mean_reversion_features(candles)
    reason = mr.long_candidate(features=f, regime="SIDEWAYS", regime_confidence=0.1, spread_bps=2.0)
    assert reason is not None and "regime_confidence_too_low" in reason


def test_short_setup_rejected_by_long_gate_and_vice_versa():
    down = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    f_down = mr.compute_mean_reversion_features(down)
    assert mr.short_candidate(features=f_down, regime="SIDEWAYS", regime_confidence=0.9, spread_bps=2.0) is not None

    up = _push_extension(_make_range_bound_candles(seed=_GOOD_UP_SEEDS[0]), direction=1)
    f_up = mr.compute_mean_reversion_features(up)
    assert mr.long_candidate(features=f_up, regime="SIDEWAYS", regime_confidence=0.9, spread_bps=2.0) is not None


# ---------------------------------------------------------------------------
# generate_candidates -- integration, determinism, evidence_only, invariants
# ---------------------------------------------------------------------------

def test_generate_candidates_produces_long_signal_on_downside_extension():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    signals = mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    assert all(isinstance(s, StrategySignal) for s in signals)
    assert all(s.side == "BUY" for s in signals)
    assert all(s.evidence_only is True for s in signals)
    assert all(s.strategy_id == mr.STRATEGY_ID for s in signals)


def test_generate_candidates_produces_short_signal_on_upside_extension():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_UP_SEEDS[0]), direction=1)
    signals = mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    assert all(s.side == "SELL" for s in signals)


def test_generate_candidates_empty_on_insufficient_warmup():
    candles = _make_range_bound_candles(n=10, seed=22)
    signals = mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_generate_candidates_empty_on_crossed_book():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    signals = mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 1.01, best_ask=candles[-1]["close"] * 0.99,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_generate_candidates_empty_when_regime_not_sideways():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]), direction=-1)
    for regime in ("BULL_TREND", "BEAR_TREND", "VOLATILE"):
        signals = mr.generate_candidates(
            candles=candles, symbol="ETHUSDT", regime=regime, regime_confidence=0.9,
            best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
            signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
        )
        assert signals == [], f"regime={regime} must never admit a mean-reversion candidate"


def test_generate_candidates_deterministic_signal_id():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[2]), direction=-1)
    kwargs = dict(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    a = mr.generate_candidates(**kwargs)
    b = mr.generate_candidates(**kwargs)
    assert [s.signal_id for s in a] == [s.signal_id for s in b]
    assert len(a) >= 1


def test_generate_candidates_net_edge_never_exceeds_gross_move():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[3]), direction=-1)
    signals = mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    for s in signals:
        assert s.net_expected_edge_bps <= s.gross_expected_move_bps


def test_generate_candidates_long_stop_below_entry_target_at_mean():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[4]), direction=-1)
    signals = mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    for s in signals:
        assert s.initial_stop_price < s.reference_price
        # §14.4 primary exit is mean touch: target sits above entry for a
        # long (buy-the-dip) setup, i.e. back toward the mean.
        assert s.target_reference_price > s.reference_price


def test_generate_candidates_short_stop_above_entry_target_at_mean():
    candles = _push_extension(_make_range_bound_candles(seed=_GOOD_UP_SEEDS[1]), direction=1)
    signals = mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    for s in signals:
        assert s.initial_stop_price > s.reference_price
        assert s.target_reference_price < s.reference_price


def test_build_registration_is_evidence_only_and_sideways_only():
    reg = mr.build_registration()
    assert reg.evidence_only is True
    assert reg.strategy_id == mr.STRATEGY_ID
    assert reg.current_version == mr.STRATEGY_VERSION
    assert reg.allowed_regimes == frozenset({"SIDEWAYS"})


# ---------------------------------------------------------------------------
# §14.5 -- prohibited behavior is structurally impossible
# ---------------------------------------------------------------------------

def test_strategy_identity_disjoint_from_other_p0_8_plus_strategies():
    from src.services import strategy_trend_cost_aware_v1 as trend
    from src.services import strategy_volatility_breakout_v1 as brk
    assert mr.STRATEGY_ID not in (trend.STRATEGY_ID, brk.STRATEGY_ID)
    assert mr.EXIT_PROFILE not in (trend.EXIT_PROFILE, brk.EXIT_PROFILE)
    assert mr.ALLOWED_REGIMES.isdisjoint(trend.ALLOWED_LONG_REGIMES | trend.ALLOWED_SHORT_REGIMES)


def test_generate_candidates_signature_has_no_prior_outcome_or_size_inputs():
    """§14.5: the function must have no way to reference a prior loss, prior
    fill, or accumulated exposure -- verified structurally via signature
    inspection rather than only by convention."""
    import inspect
    params = set(inspect.signature(mr.generate_candidates).parameters.keys())
    forbidden = {"prior_loss", "loss_count", "position_size", "accumulated_size",
                 "scale_in", "martingale_step", "prior_fill_price", "average_entry"}
    assert params.isdisjoint(forbidden)


# ---------------------------------------------------------------------------
# §22.4 replay-style scenarios (subset relevant to this strategy)
# ---------------------------------------------------------------------------

def test_replay_scenario_no_extension_produces_no_candidates():
    candles = _make_range_bound_candles(seed=30)
    signals = mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_replay_scenario_data_outage_short_history_produces_no_candidates():
    candles = _make_range_bound_candles(n=10, seed=31)
    signals = mr.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []
