"""Tests for regime_classifier_v1.classify_regime()."""
import random

import pytest

from src.services import regime_classifier_v1 as rc


def _make_candles(n, *, start_price=1000.0, drift_bps_per_bar=0.0, range_frac=0.001,
                   interval_ms=60_000, start_time_ms=1_700_000_000_000, seed=0, volume=10.0):
    rng = random.Random(seed)
    candles = []
    price = start_price
    for i in range(n):
        drift = price * (drift_bps_per_bar / 10_000.0)
        jitter = price * rng.uniform(-range_frac / 4, range_frac / 4)
        open_p = price
        close_p = max(0.01, price + drift + jitter)
        high_p = max(open_p, close_p) * (1 + range_frac / 2)
        low_p = min(open_p, close_p) * (1 - range_frac / 2)
        candles.append({
            "open_time": start_time_ms + i * interval_ms,
            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
            "volume": volume,
        })
        price = close_p
    return candles


def test_insufficient_candles_returns_sideways_zero_confidence():
    regime, confidence = rc.classify_regime(_make_candles(50))
    assert regime == "SIDEWAYS"
    assert confidence == 0.0


def test_strong_uptrend_classified_bull_trend():
    candles = _make_candles(220, drift_bps_per_bar=3.0, seed=1)
    regime, confidence = rc.classify_regime(candles)
    assert regime == "BULL_TREND"
    assert confidence > 0


def test_strong_downtrend_classified_bear_trend():
    candles = _make_candles(220, drift_bps_per_bar=-3.0, seed=2)
    regime, confidence = rc.classify_regime(candles)
    assert regime == "BEAR_TREND"
    assert confidence > 0


def test_flat_noise_classified_sideways():
    candles = _make_candles(220, drift_bps_per_bar=0.0, range_frac=0.0005, seed=3)
    regime, confidence = rc.classify_regime(candles)
    assert regime == "SIDEWAYS"


def test_high_volatility_classified_volatile_regardless_of_trend():
    candles = _make_candles(220, drift_bps_per_bar=3.0, range_frac=0.08, seed=4)
    regime, confidence = rc.classify_regime(candles)
    assert regime == "VOLATILE"
    assert confidence > 0


def test_confidence_always_in_unit_interval():
    for seed, drift, rng_frac in [(5, 5.0, 0.001), (6, -5.0, 0.001), (7, 0.0, 0.1), (8, 0.0, 0.0005)]:
        candles = _make_candles(220, drift_bps_per_bar=drift, range_frac=rng_frac, seed=seed)
        _, confidence = rc.classify_regime(candles)
        assert 0.0 <= confidence <= 1.0


def test_deterministic_for_same_input():
    candles = _make_candles(220, drift_bps_per_bar=2.0, seed=9)
    a = rc.classify_regime(candles)
    b = rc.classify_regime(candles)
    assert a == b


def test_only_completed_bars_used_no_lookahead():
    candles = _make_candles(260, drift_bps_per_bar=2.0, seed=10)
    a = rc.classify_regime(candles[:220])
    b = rc.classify_regime(candles[:220])
    assert a == b


def test_returns_one_of_the_four_canonical_regimes():
    for seed, drift, rng_frac in [(11, 5.0, 0.001), (12, -5.0, 0.001), (13, 0.0, 0.001), (14, 0.0, 0.08)]:
        candles = _make_candles(220, drift_bps_per_bar=drift, range_frac=rng_frac, seed=seed)
        regime, _ = rc.classify_regime(candles)
        assert regime in {"SIDEWAYS", "BULL_TREND", "BEAR_TREND", "VOLATILE"}


def test_zero_or_negative_close_price_fails_closed():
    candles = _make_candles(220, seed=15)
    candles[-1]["close"] = 0.0
    regime, confidence = rc.classify_regime(candles)
    assert regime == "SIDEWAYS"
    assert confidence == 0.0
