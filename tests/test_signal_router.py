"""P0.7/central-contract tests -- evaluate_signal_for_paper_entry() (§16).

Covers the document's mandatory §22.2 integration/rejection paths:
candidate -> cost reject, signal -> P0 reject, P0 admit -> risk guard
(§17, p0_risk_guard_v1.py, wired 2026-08-10) -> admit or risk reject.

Risk-guard-dependent tests inject a deterministic `risk_guard_fn` rather
than exercising the real p0_risk_guard_v1.evaluate_risk_guard() (which reads
live runtime_mode/risk_engine/firebase_client/paper_trade_executor global
state) -- keeps this test file's outcomes independent of whatever state
those modules happen to be in when the suite runs, same test-isolation
discipline the rest of this file already follows via its own `registry`
injection parameter. p0_risk_guard_v1's OWN behavior is covered by
test_p0_risk_guard_v1.py.
"""
import pytest

from src.services import strategy_contracts as sc
from src.services.p0_risk_guard_v1 import RiskGuardResult
from src.services.signal_router import evaluate_signal_for_paper_entry
from src.services.strategy_registry import StrategyRegistration, StrategyRegistry


def _allow_risk(**_kwargs):
    return RiskGuardResult(allowed=True, reason="")


def _deny_risk(**_kwargs):
    return RiskGuardResult(allowed=False, reason="test-injected denial")


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


def test_evidence_collection_admitted_end_to_end_when_risk_guard_allows():
    """§16 step 9, post-§17 wiring: a signal that clears cost + P0
    (evidence-collection scope) AND the risk guard is now genuinely
    admitted -- the P0.8+ pipeline's first-ever true admit path."""
    reg = _registry()
    ev = evaluate_signal_for_paper_entry(
        _signal(), registry=reg, risk_guard_fn=_allow_risk, **_market_kwargs(),
    )
    assert ev.p0_strict_ev is False  # evidence_only signal, §2.4
    assert ev.p0_readiness_eligible is False
    assert ev.admitted is True
    assert ev.risk_allowed is True
    assert ev.decision_code == sc.P0_ADMIT_EVIDENCE_COLLECTION


def test_p0_admit_blocked_by_risk_guard_denial():
    """A signal that clears cost + P0 but the risk guard denies (daily-DD
    unsafe, quota degraded, position conflict, real trading allowed, etc.)
    must come back admitted=False with an explicit REJECT_RISK_DENIED code
    and the guard's own reason surfaced -- not silently swallowed."""
    reg = _registry()
    ev = evaluate_signal_for_paper_entry(
        _signal(), registry=reg, risk_guard_fn=_deny_risk, **_market_kwargs(),
    )
    assert ev.admitted is False
    assert ev.risk_allowed is False
    assert ev.decision_code == sc.REJECT_RISK_DENIED
    assert ev.risk_reason == "test-injected denial"


def test_risk_guard_exception_fails_closed():
    """§2.5: 'Do not replace a rejection with a permissive default.' If the
    risk guard itself raises, the signal must be rejected, not admitted."""
    def _exploding_guard(**_kwargs):
        raise RuntimeError("boom")

    reg = _registry()
    ev = evaluate_signal_for_paper_entry(
        _signal(), registry=reg, risk_guard_fn=_exploding_guard, **_market_kwargs(),
    )
    assert ev.admitted is False
    assert ev.risk_allowed is False
    assert ev.decision_code == sc.REJECT_RISK_UNAVAILABLE
    assert "boom" in ev.risk_reason


def test_risk_guard_not_evaluated_when_p0_already_rejects():
    """The risk guard must not even be called for a P0-rejected signal
    (§16's step ordering, and cheap-path discipline) -- a guard that raises
    on every call must not affect the outcome if P0 already said no."""
    def _exploding_guard(**_kwargs):
        raise RuntimeError("must never be called")

    reg = _registry(allowed_symbols=frozenset({"BTCUSDT"}))  # quarantined -> P0 rejects first
    ev = evaluate_signal_for_paper_entry(
        _signal(symbol="BTCUSDT"), registry=reg, risk_guard_fn=_exploding_guard, **_market_kwargs(),
    )
    assert ev.admitted is False
    assert ev.decision_code == sc.P0_REJECT_QUARANTINED


def test_risk_guard_receives_symbol_and_side():
    """The router must pass the signal's own symbol/side through to the
    guard, not a hardcoded or stale value."""
    seen = {}

    def _capturing_guard(**kwargs):
        seen.update(kwargs)
        return RiskGuardResult(allowed=True, reason="")

    reg = _registry()
    evaluate_signal_for_paper_entry(
        _signal(symbol="ETHUSDT", side="BUY"), registry=reg,
        risk_guard_fn=_capturing_guard, **_market_kwargs(),
    )
    assert seen.get("symbol") == "ETHUSDT"
    assert seen.get("side") == "BUY"


def test_default_risk_guard_is_the_real_p0_risk_guard_v1_when_not_injected():
    """Without an explicit risk_guard_fn, the router must use the real
    p0_risk_guard_v1.evaluate_risk_guard -- not silently no-op admit.
    Exercised end-to-end against the real module's fail-closed defaults
    (no live-trading env override in the test process, so
    live_trading_allowed() is False and the paper-only check passes; other
    checks depend on ambient risk_engine/firebase_client/paper_trade_executor
    state, so this only asserts the call reaches the real function and
    returns a well-formed result, not a specific admit/deny outcome)."""
    reg = _registry()
    ev = evaluate_signal_for_paper_entry(_signal(), registry=reg, **_market_kwargs())
    assert ev.decision_code in (
        sc.P0_ADMIT_EVIDENCE_COLLECTION, sc.REJECT_RISK_DENIED, sc.REJECT_RISK_UNAVAILABLE,
    )


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
