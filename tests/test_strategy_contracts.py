"""P0.7/central-contract tests -- StrategySignal / SignalEvaluation (§7, §2.5)."""
import math

import pytest

from src.services import strategy_contracts as sc


def _valid_kwargs(**overrides):
    kwargs = dict(
        signal_id="sig-1",
        strategy_id="trend_cost_aware",
        strategy_version="1",
        symbol="ETHUSDT",
        side="BUY",
        regime="BULL_TREND",
        learning_source="trend_cost_aware_v1",
        generated_event_time_ms=1_700_000_000_000,
        generated_processing_time_ms=1_700_000_000_010,
        market_data_event_time_ms=1_700_000_000_005,
        feature_snapshot_time_ms=1_700_000_000_005,
        expected_horizon_seconds=300,
        reference_price=1900.0,
        gross_expected_move_bps=30.0,
        expected_cost_bps=10.0,
        uncertainty_buffer_bps=2.0,
        net_expected_edge_bps=18.0,
        confidence=0.6,
        invalidation_price=1890.0,
        initial_stop_price=1890.0,
        target_reference_price=1930.0,
        exit_profile="dynamic_trend_exit_v1",
        feature_schema_version="v1",
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_signal_constructs():
    sig = sc.StrategySignal(**_valid_kwargs())
    assert sig.symbol == "ETHUSDT"
    assert sig.evidence_only is True  # default per §2.4


def test_signal_is_frozen():
    sig = sc.StrategySignal(**_valid_kwargs())
    with pytest.raises(Exception):
        sig.symbol = "BTCUSDT"  # type: ignore[misc]


@pytest.mark.parametrize("field", [
    "strategy_id", "strategy_version", "symbol", "side", "regime",
    "learning_source", "exit_profile", "feature_schema_version", "signal_id",
])
def test_signal_rejects_empty_string_fields(field):
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(**{field: ""}))


def test_signal_rejects_invalid_side():
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(side="SIDEWAYS"))


@pytest.mark.parametrize("side", ["BUY", "SELL", "LONG", "SHORT", "buy", "sell"])
def test_signal_accepts_known_sides_case_insensitive(side):
    sc.StrategySignal(**_valid_kwargs(side=side))  # must not raise


@pytest.mark.parametrize("field", [
    "reference_price", "gross_expected_move_bps", "expected_cost_bps",
    "uncertainty_buffer_bps", "net_expected_edge_bps", "confidence",
    "invalidation_price", "initial_stop_price",
])
def test_signal_rejects_nan(field):
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(**{field: float("nan")}))


@pytest.mark.parametrize("field", [
    "reference_price", "gross_expected_move_bps", "expected_cost_bps",
    "uncertainty_buffer_bps", "net_expected_edge_bps",
    "invalidation_price", "initial_stop_price",
])
def test_signal_rejects_infinite(field):
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(**{field: float("inf")}))


def test_signal_rejects_target_reference_price_nan_but_allows_none():
    sc.StrategySignal(**_valid_kwargs(target_reference_price=None))  # must not raise
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(target_reference_price=float("nan")))


@pytest.mark.parametrize("confidence", [-0.01, 1.01, -1.0, 2.0])
def test_signal_rejects_confidence_out_of_range(confidence):
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(confidence=confidence))


@pytest.mark.parametrize("confidence", [0.0, 1.0, 0.5])
def test_signal_accepts_confidence_boundary_values(confidence):
    sc.StrategySignal(**_valid_kwargs(confidence=confidence))  # must not raise


def test_signal_rejects_non_positive_reference_price():
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(reference_price=0.0))
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(reference_price=-1.0))


def test_signal_rejects_non_positive_horizon():
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(expected_horizon_seconds=0))
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(expected_horizon_seconds=-5))


@pytest.mark.parametrize("field", [
    "generated_event_time_ms", "generated_processing_time_ms",
    "market_data_event_time_ms", "feature_snapshot_time_ms",
])
def test_signal_rejects_non_positive_timestamps(field):
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(**{field: 0}))
    with pytest.raises(ValueError):
        sc.StrategySignal(**_valid_kwargs(**{field: -1}))


def test_signal_default_feature_snapshot_is_empty_mapping():
    sig = sc.StrategySignal(**_valid_kwargs())
    assert dict(sig.feature_snapshot) == {}


def test_signal_default_reason_codes_is_empty_tuple():
    sig = sc.StrategySignal(**_valid_kwargs())
    assert sig.reason_codes == ()


def test_signal_evidence_only_defaults_true():
    """§2.4: 'All new strategies begin as evidence-only sources.'"""
    sig = sc.StrategySignal(**_valid_kwargs())
    assert sig.evidence_only is True


def test_signal_evaluation_is_frozen():
    ev = sc.SignalEvaluation(
        signal_id="s1", admitted=True, decision_code="P0_ADMIT_EVIDENCE_COLLECTION",
        decision_reasons=("ok",), gross_expected_move_bps=1.0, expected_cost_bps=1.0,
        uncertainty_buffer_bps=1.0, net_expected_edge_bps=1.0, p0_segment_key="k",
        p0_strict_ev=False, p0_readiness_eligible=False, risk_allowed=True,
        risk_reason="", evaluated_at_ms=1,
    )
    with pytest.raises(Exception):
        ev.admitted = False  # type: ignore[misc]
