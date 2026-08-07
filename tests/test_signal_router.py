"""P0.7/central-contract tests -- evaluate_signal_for_paper_entry() (§16).

Covers the document's mandatory §22.2 integration/rejection paths:
candidate -> cost reject, signal -> P0 reject, P0 admit -> risk reject
(no central risk guard exists yet, so risk always currently rejects --
asserted explicitly, not silently passed).
"""
import pytest

from src.services import strategy_contracts as sc
from src.services.signal_router import evaluate_signal_for_paper_entry
from src.services.strategy_registry import StrategyRegistration, StrategyRegistry


def _signal(**overrides):
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
    return sc.StrategySignal(**kwargs)


def _registry(**reg_overrides):
    reg = StrategyRegistry()
    kwargs = dict(
        strategy_id="trend_cost_aware",
        current_version="1",
        enabled=True,
        evidence_only=True,
        allowed_symbols=frozenset({"ETHUSDT"}),
        allowed_regimes=frozenset({"BULL_TREND"}),
        allowed_sides=frozenset({"BUY"}),
        exit_profile="dynamic_trend_exit_v1",
        minimum_warmup_seconds=60,
        required_feature_schema_version="v1",
    )
    kwargs.update(reg_overrides)
    reg.register(StrategyRegistration(**kwargs))
    return reg


def _market_kwargs(**overrides):
    kwargs = dict(
        best_bid=1899.9,
        best_ask=1900.1,
        requested_notional=25.0,
        visible_top_notional=1000.0,
        realized_volatility_bps=10.0,
        realized_volatility_bps_per_second=0.5,
        decision_latency_ms=20.0,
        now_ms=1_700_000_000_050,
    )
    kwargs.update(overrides)
    return kwargs


def test_unknown_strategy_rejected():
    ev = evaluate_signal_for_paper_entry(
        _signal(), registry=StrategyRegistry(),  # empty registry
        **_market_kwargs(),
    )
    assert ev.admitted is False
    assert ev.decision_code == sc.REJECT_UNKNOWN_STRATEGY


def test_disabled_strategy_rejected():
    reg = _registry(enabled=False)
    ev = evaluate_signal_for_paper_entry(_signal(), registry=reg, **_market_kwargs())
    assert ev.admitted is False
    assert ev.decision_code == sc.REJECT_STRATEGY_DISABLED


def test_symbol_not_allowed_rejected():
    reg = _registry(allowed_symbols=frozenset({"BTCUSDT"}))
    ev = evaluate_signal_for_paper_entry(_signal(), registry=reg, **_market_kwargs())
    assert ev.admitted is False
    assert ev.decision_code == sc.REJECT_SIGNAL_SCHEMA


def test_stale_market_data_rejected():
    reg = _registry()
    ev = evaluate_signal_for_paper_entry(
        _signal(), registry=reg,
        **_market_kwargs(now_ms=1_700_000_100_000),  # ~100s later, way stale
    )
    assert ev.admitted is False
    assert ev.decision_code == sc.REJECT_STALE_MARKET_DATA


def test_future_market_data_rejected():
    reg = _registry()
    ev = evaluate_signal_for_paper_entry(
        _signal(), registry=reg,
        **_market_kwargs(now_ms=1_699_999_999_000),  # before market_data_event_time_ms
    )
    assert ev.admitted is False
    assert ev.decision_code == sc.REJECT_STALE_MARKET_DATA


def test_cost_reject_when_gross_move_too_thin():
    reg = _registry()
    ev = evaluate_signal_for_paper_entry(
        _signal(gross_expected_move_bps=0.01), registry=reg, **_market_kwargs(),
    )
    assert ev.admitted is False
    assert ev.decision_code == sc.REJECT_NEGATIVE_NET_EDGE


def test_quarantined_symbol_rejected_by_p0():
    """BTCUSDT is quarantined in the existing P0SegmentEVGate."""
    reg = _registry(allowed_symbols=frozenset({"BTCUSDT"}))
    ev = evaluate_signal_for_paper_entry(
        _signal(symbol="BTCUSDT"), registry=reg, **_market_kwargs(),
    )
    assert ev.admitted is False
    assert ev.decision_code in (sc.P0_REJECT_QUARANTINED, sc.REJECT_RISK_UNAVAILABLE)
    assert "quarantined" in ev.decision_reasons[0]


def test_evidence_collection_admitted_by_p0_but_blocked_by_missing_risk_guard():
    """§16 step 9 / P0.7 gap: no central risk guard exists yet. A signal
    that clears cost + P0 (evidence-collection scope) must still come back
    admitted=False, with an explicit, honest reason -- not a silent pass."""
    reg = _registry()
    ev = evaluate_signal_for_paper_entry(_signal(), registry=reg, **_market_kwargs())
    assert ev.p0_strict_ev is False  # evidence_only signal, §2.4
    assert ev.p0_readiness_eligible is False
    assert ev.admitted is False  # blocked on the missing risk guard, not on P0
    assert ev.risk_allowed is False
    assert "no central risk guard" in ev.risk_reason


def test_evidence_only_signal_never_gets_strict_ev_even_with_registration_not_evidence_only():
    """§2.4: evidence_only on the SIGNAL itself is an independent floor."""
    reg = _registry(evidence_only=False)
    ev = evaluate_signal_for_paper_entry(
        _signal(evidence_only=True), registry=reg, **_market_kwargs(),
    )
    assert ev.p0_strict_ev is False
    assert ev.p0_readiness_eligible is False


def test_p0_segment_key_format_matches_existing_gate_fields():
    reg = _registry()
    ev = evaluate_signal_for_paper_entry(_signal(), registry=reg, **_market_kwargs())
    assert ev.p0_segment_key == "ETHUSDT:BUY:BULL_TREND:trend_cost_aware_v1:dynamic_trend_exit_v1"


def test_evaluation_never_mutates_the_input_signal():
    reg = _registry()
    sig = _signal()
    before = sig.gross_expected_move_bps
    evaluate_signal_for_paper_entry(sig, registry=reg, **_market_kwargs())
    assert sig.gross_expected_move_bps == before  # frozen dataclass, but assert anyway


def test_net_expected_edge_never_exceeds_gross_move():
    """Property invariant (§22.7)."""
    reg = _registry()
    ev = evaluate_signal_for_paper_entry(_signal(), registry=reg, **_market_kwargs())
    assert ev.net_expected_edge_bps <= ev.gross_expected_move_bps
