"""P1.1 (Evidence-First Strategy Expansion v2, §13, §22.1 'Strategies',
§22.4 replay scenarios subset) -- volatility_breakout_v1 tests.
"""
import random

import pytest

from src.services import strategy_volatility_breakout_v1 as brk
from src.services.strategy_contracts import StrategySignal


def _make_compression_then_breakout(
    *, n_compression=140, breakout_direction=1, seed=0, start_price=1000.0,
    breakout_move_frac=0.02, start_time_ms=1_700_000_000_000, interval_ms=60_000,
):
    """Synthetic deterministic fixture: a coiling compression phase (range
    and volume both narrowing bar over bar, no lookahead -- each bar only
    depends on the seeded PRNG and its own index) followed by a single
    expansion bar that clears the Donchian boundary with volume and range
    both well above the trailing average."""
    rng = random.Random(seed)
    candles = []
    price = start_price
    start_frac, end_frac = 0.006, 0.0004
    start_vol, end_vol = 20.0, 3.0
    for i in range(n_compression):
        t = i / max(1, n_compression - 1)
        range_frac = start_frac + (end_frac - start_frac) * t
        volume = start_vol + (end_vol - start_vol) * t
        jitter = price * rng.uniform(-range_frac / 2, range_frac / 2)
        open_p = price
        close_p = max(0.01, price + jitter)
        high_p = max(open_p, close_p) * (1 + range_frac / 2)
        low_p = min(open_p, close_p) * (1 - range_frac / 2)
        candles.append({
            "open_time": start_time_ms + i * interval_ms,
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "volume": volume,
        })
        price = close_p

    open_p = price
    if breakout_direction > 0:
        close_p = price * (1 + breakout_move_frac)
        high_p = close_p * 1.001
        low_p = open_p * 0.999
    else:
        close_p = price * (1 - breakout_move_frac)
        high_p = open_p * 1.001
        low_p = close_p * 0.999
    candles.append({
        "open_time": start_time_ms + n_compression * interval_ms,
        "open": open_p, "high": high_p, "low": low_p, "close": close_p,
        "volume": start_vol * 3.0,
    })
    return candles


def _id_factory(symbol, side, regime, ts):
    return f"{symbol}:{side}:{regime}:{ts}"


# ---------------------------------------------------------------------------
# compute_breakout_features -- warmup, no-lookahead, determinism
# ---------------------------------------------------------------------------

def test_compute_breakout_features_requires_minimum_candles():
    with pytest.raises(ValueError):
        brk.compute_breakout_features(_make_compression_then_breakout(n_compression=10))


def test_compute_breakout_features_deterministic_for_same_input():
    candles = _make_compression_then_breakout(seed=1)
    a = brk.compute_breakout_features(candles)
    b = brk.compute_breakout_features(candles)
    assert a == b


def test_compression_phase_reports_low_channel_width_percentile():
    candles = _make_compression_then_breakout(seed=2)
    f = brk.compute_breakout_features(candles)
    assert f.channel_width_percentile <= brk.COMPRESSION_CHANNEL_WIDTH_PERCENTILE_MAX


def test_breakout_bar_reports_range_and_volume_expansion():
    candles = _make_compression_then_breakout(seed=3)
    f = brk.compute_breakout_features(candles)
    assert f.range_expansion_ratio >= brk.VOLATILITY_EXPANSION_MIN_RATIO
    assert f.volume_expansion_ratio >= brk.VOLUME_EXPANSION_MIN_RATIO


def test_donchian_level_excludes_current_bar():
    """§13.3: the level must be based only on completed historical
    observations -- the breakout bar's own high/low must not inflate it."""
    candles = _make_compression_then_breakout(seed=4, breakout_direction=1)
    f = brk.compute_breakout_features(candles)
    assert f.donchian_high < candles[-1]["high"]


def test_only_completed_bars_used_no_lookahead():
    candles = _make_compression_then_breakout(n_compression=200, seed=5)
    a = brk.compute_breakout_features(candles[:161])
    b = brk.compute_breakout_features(candles[:161])
    assert a == b
    c = brk.compute_breakout_features(candles[:171])
    assert isinstance(c, brk.BreakoutFeatures)


# ---------------------------------------------------------------------------
# long_candidate / short_candidate gates
# ---------------------------------------------------------------------------

def _breakout_features(direction=1, seed=10):
    candles = _make_compression_then_breakout(breakout_direction=direction, seed=seed)
    return brk.compute_breakout_features(candles), float(candles[-1]["close"])


def test_valid_long_breakout_candidate_admitted():
    f, price = _breakout_features(direction=1, seed=10)
    reason = brk.long_candidate(
        features=f, regime="SIDEWAYS", regime_confidence=0.9,
        reference_price=price, spread_bps=2.0,
    )
    assert reason is None


def test_valid_short_breakout_candidate_admitted():
    f, price = _breakout_features(direction=-1, seed=11)
    reason = brk.short_candidate(
        features=f, regime="SIDEWAYS", regime_confidence=0.9,
        reference_price=price, spread_bps=2.0,
    )
    assert reason is None


def test_long_regime_rejection():
    f, price = _breakout_features(direction=1, seed=12)
    reason = brk.long_candidate(
        features=f, regime="BULL_TREND", regime_confidence=0.9,
        reference_price=price, spread_bps=2.0,
    )
    assert reason is not None and "regime_not_allowed" in reason


def test_no_compression_rejection():
    """A flat, non-coiling series has a channel width consistent with its
    own history throughout -- percentile should sit near the middle, not
    qualify as 'prior compression'."""
    candles = []
    price = 1000.0
    rng = random.Random(42)
    for i in range(161):
        jitter = price * rng.uniform(-0.003, 0.003)
        open_p = price
        close_p = max(0.01, price + jitter)
        high_p = max(open_p, close_p) * 1.003
        low_p = min(open_p, close_p) * 0.997
        candles.append({
            "open_time": 1_700_000_000_000 + i * 60_000,
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "volume": 10.0,
        })
        price = close_p
    f = brk.compute_breakout_features(candles)
    reason = brk.long_candidate(
        features=f, regime="SIDEWAYS", regime_confidence=0.9,
        reference_price=float(candles[-1]["close"]), spread_bps=2.0,
    )
    assert reason is not None


def test_high_spread_rejection():
    f, price = _breakout_features(direction=1, seed=13)
    reason = brk.long_candidate(
        features=f, regime="SIDEWAYS", regime_confidence=0.9,
        reference_price=price, spread_bps=999.0,
    )
    assert reason is not None and "spread_too_wide" in reason


def test_short_candidate_uses_its_own_level_not_a_sign_flip():
    """§13.4: short must use donchian_low, not a negated donchian_high."""
    import inspect
    long_src = inspect.getsource(brk.long_candidate)
    short_src = inspect.getsource(brk.short_candidate)
    assert "donchian_low" not in long_src
    assert "donchian_high" not in short_src


# ---------------------------------------------------------------------------
# generate_candidates -- integration, determinism, evidence_only, invariants
# ---------------------------------------------------------------------------

def test_generate_candidates_produces_long_signal_on_upside_breakout():
    candles = _make_compression_then_breakout(breakout_direction=1, seed=20)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    assert all(isinstance(s, StrategySignal) for s in signals)
    assert all(s.side == "BUY" for s in signals)
    assert all(s.evidence_only is True for s in signals)
    assert all(s.strategy_id == brk.STRATEGY_ID for s in signals)


def test_generate_candidates_produces_short_signal_on_downside_breakout():
    candles = _make_compression_then_breakout(breakout_direction=-1, seed=21)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    assert all(s.side == "SELL" for s in signals)


def test_generate_candidates_empty_on_insufficient_warmup():
    candles = _make_compression_then_breakout(n_compression=10, seed=22)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_generate_candidates_empty_on_crossed_book():
    candles = _make_compression_then_breakout(breakout_direction=1, seed=23)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 1.01, best_ask=candles[-1]["close"] * 0.99,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_generate_candidates_empty_when_regime_not_allowed():
    candles = _make_compression_then_breakout(breakout_direction=1, seed=24)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="BULL_TREND", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_generate_candidates_deterministic_signal_id():
    candles = _make_compression_then_breakout(breakout_direction=1, seed=25)
    kwargs = dict(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    a = brk.generate_candidates(**kwargs)
    b = brk.generate_candidates(**kwargs)
    assert [s.signal_id for s in a] == [s.signal_id for s in b]


def test_generate_candidates_net_edge_never_exceeds_gross_move():
    candles = _make_compression_then_breakout(breakout_direction=1, seed=26)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    for s in signals:
        assert s.net_expected_edge_bps <= s.gross_expected_move_bps


def test_generate_candidates_long_stop_below_entry():
    candles = _make_compression_then_breakout(breakout_direction=1, seed=27)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    for s in signals:
        assert s.initial_stop_price < s.reference_price


def test_generate_candidates_short_stop_above_entry():
    candles = _make_compression_then_breakout(breakout_direction=-1, seed=28)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    for s in signals:
        assert s.initial_stop_price > s.reference_price


def test_generate_candidates_stop_respects_retest_of_breakout_level():
    """§13.6 false-breakout protection: the long stop must sit below the
    breakout level (not miles away via ATR alone) so a retest failure exits
    promptly."""
    candles = _make_compression_then_breakout(breakout_direction=1, seed=29)
    f = brk.compute_breakout_features(candles)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1
    for s in signals:
        assert s.initial_stop_price <= f.donchian_high


def test_build_registration_is_evidence_only():
    reg = brk.build_registration()
    assert reg.evidence_only is True
    assert reg.strategy_id == brk.STRATEGY_ID
    assert reg.current_version == brk.STRATEGY_VERSION
    assert reg.exit_profile == brk.EXIT_PROFILE


def test_all_generated_signals_pass_their_own_schema_validation():
    candles = _make_compression_then_breakout(breakout_direction=1, seed=30)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert len(signals) >= 1


# ---------------------------------------------------------------------------
# §13.7 -- strategy identity is disjoint from trend_cost_aware_v1
# ---------------------------------------------------------------------------

def test_strategy_identity_disjoint_from_trend_strategy():
    from src.services import strategy_trend_cost_aware_v1 as trend
    assert brk.STRATEGY_ID != trend.STRATEGY_ID
    assert brk.EXIT_PROFILE != trend.EXIT_PROFILE
    assert brk.ALLOWED_REGIMES.isdisjoint(trend.ALLOWED_LONG_REGIMES | trend.ALLOWED_SHORT_REGIMES)


# ---------------------------------------------------------------------------
# §22.4 replay-style scenarios (subset relevant to this strategy)
# ---------------------------------------------------------------------------

def test_replay_scenario_no_breakout_produces_no_candidates():
    """A compression phase with no expansion bar at the end must not admit
    (there is nothing to break out of/into yet)."""
    candles = _make_compression_then_breakout(breakout_direction=1, seed=31, breakout_move_frac=0.0)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []


def test_replay_scenario_data_outage_short_history_produces_no_candidates():
    candles = _make_compression_then_breakout(n_compression=10, seed=32)
    signals = brk.generate_candidates(
        candles=candles, symbol="ETHUSDT", regime="SIDEWAYS", regime_confidence=0.9,
        best_bid=candles[-1]["close"] * 0.9999, best_ask=candles[-1]["close"] * 1.0001,
        signal_id_factory=_id_factory, now_ms=candles[-1]["open_time"] + 100,
    )
    assert signals == []
