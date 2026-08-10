"""Central P0 routing — Evidence-First Strategy Expansion v2, §16.

`evaluate_signal_for_paper_entry()` is the one function every new strategy
signal must pass through. It validates the signal, computes cost/edge via
cost_model.py, and calls the EXISTING P0SegmentEVGate (src/services/
p0_segment_ev_gate.py) -- reused, not reimplemented, per Gate G0's finding
that this module already is the document's "Central P0 Segment EV Gate"
(same segment-key shape, same n>=30/PF>=1.2/timeout<=60% thresholds, same
quarantine/evidence-collection reason-code vocabulary).

This module deliberately does NOT open a position (§16 point 13: "prefer
explicit separation between evaluation and execution"). It has no import of
paper_trade_executor, trade_executor, or any open_paper_position call site --
enforced by tests/test_signal_router_bypass.py's static source scan. The
risk guard it calls (p0_risk_guard_v1.py, §17) DOES need to read open
positions to check for duplicate/opposite-position conflicts, but does so
via a lazy, function-body-scoped import specifically so it never becomes a
module-level dependency of THIS file (see p0_risk_guard_v1.py's own
docstring) -- verified by the same bypass test's AST scan, which only
inspects this file's own import statements.

`market_state`/`portfolio_state` are NOT modeled as new dataclasses in this
phase: no existing equivalent was found in Gate G0's reconnaissance to adapt,
and inventing an unverified abstraction here would be exactly the "assumption
over repository fact" this program's own §0.1 forbids. This function instead
takes the specific fields cost_model.evaluate_edge() and the P0 gate actually
need as explicit keyword arguments -- narrower, but honest about what is and
is not yet wired.

2026-08-10: `risk_allowed` was hardcoded False from this module's very first
commit (d4d69ee) -- meaning the entire P0.8+ pipeline had never admitted a
single signal, ever, regardless of edge or P0 eligibility. p0_risk_guard_v1.py
(§17) closes that gap; see its own docstring for exactly what it does and
does not check.
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Sequence

from src.services import cost_model
from src.services import strategy_contracts as sc
from src.services.p0_risk_guard_v1 import RiskGuardResult, evaluate_risk_guard
from src.services.p0_segment_ev_gate import P0SegmentEVGate
from src.services.strategy_registry import StrategyRegistry, get_default_registry

DEFAULT_MAX_DATA_AGE_MS = 5_000


def evaluate_signal_for_paper_entry(
    signal: sc.StrategySignal,
    *,
    best_bid: float,
    best_ask: float,
    requested_notional: float,
    visible_top_notional: float,
    realized_volatility_bps: float,
    realized_volatility_bps_per_second: float,
    decision_latency_ms: float,
    closed_trades: Sequence[dict] = (),
    seconds_to_next_funding: Optional[float] = None,
    current_funding_rate_bps: Optional[float] = None,
    now_ms: Optional[int] = None,
    max_data_age_ms: int = DEFAULT_MAX_DATA_AGE_MS,
    registry: Optional[StrategyRegistry] = None,
    risk_guard_fn: Optional[Callable[..., RiskGuardResult]] = None,
) -> sc.SignalEvaluation:
    """Evaluate one StrategySignal for paper-entry admission.

    Never opens a position. Never mutates `signal`. Returns an immutable
    SignalEvaluation whose `admitted` flag a caller (P0.8+ strategy glue,
    not this module) may act on.
    """
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    reg = registry if registry is not None else get_default_registry()

    def _reject(code: str, reason: str) -> sc.SignalEvaluation:
        return sc.SignalEvaluation(
            signal_id=signal.signal_id,
            admitted=False,
            decision_code=code,
            decision_reasons=(reason,),
            gross_expected_move_bps=signal.gross_expected_move_bps,
            expected_cost_bps=0.0,
            uncertainty_buffer_bps=signal.uncertainty_buffer_bps,
            net_expected_edge_bps=0.0,
            p0_segment_key="",
            p0_strict_ev=False,
            p0_readiness_eligible=False,
            risk_allowed=False,
            risk_reason=reason,
            evaluated_at_ms=now_ms,
        )

    # 1-2. Strategy registration (§16 steps 1,3; §16.3 unknown-strategy reject)
    registration = reg.get(signal.strategy_id)
    if registration is None:
        return _reject(sc.REJECT_UNKNOWN_STRATEGY, f"strategy_id {signal.strategy_id!r} is not registered")
    if not registration.enabled:
        return _reject(sc.REJECT_STRATEGY_DISABLED, f"strategy_id {signal.strategy_id!r} is disabled")
    if signal.strategy_version != registration.current_version:
        return _reject(
            sc.REJECT_UNKNOWN_STRATEGY,
            f"strategy_version {signal.strategy_version!r} does not match registered "
            f"current_version {registration.current_version!r}",
        )
    if signal.symbol not in registration.allowed_symbols:
        return _reject(sc.REJECT_SIGNAL_SCHEMA, f"symbol {signal.symbol!r} not allowed for {signal.strategy_id!r}")
    if signal.regime not in registration.allowed_regimes:
        return _reject(sc.REJECT_SIGNAL_SCHEMA, f"regime {signal.regime!r} not allowed for {signal.strategy_id!r}")
    if signal.side.upper() not in registration.allowed_sides:
        return _reject(sc.REJECT_SIGNAL_SCHEMA, f"side {signal.side!r} not allowed for {signal.strategy_id!r}")
    if signal.feature_schema_version != registration.required_feature_schema_version:
        return _reject(
            sc.REJECT_SIGNAL_SCHEMA,
            f"feature_schema_version {signal.feature_schema_version!r} != required "
            f"{registration.required_feature_schema_version!r}",
        )

    # 2b. Freshness (§2.5 "stale market data")
    data_age_ms = now_ms - signal.market_data_event_time_ms
    if data_age_ms < 0:
        return _reject(sc.REJECT_STALE_MARKET_DATA, f"market_data_event_time_ms is in the future by {-data_age_ms}ms")
    if data_age_ms > max_data_age_ms:
        return _reject(sc.REJECT_STALE_MARKET_DATA, f"market data age {data_age_ms}ms exceeds max {max_data_age_ms}ms")

    # 5-6. Cost + net edge (§16 steps 5-6)
    try:
        edge = cost_model.evaluate_edge(
            side=signal.side,
            gross_expected_move_bps=signal.gross_expected_move_bps,
            best_bid=best_bid,
            best_ask=best_ask,
            requested_notional=requested_notional,
            visible_top_notional=visible_top_notional,
            realized_volatility_bps=realized_volatility_bps,
            realized_volatility_bps_per_second=realized_volatility_bps_per_second,
            decision_latency_ms=decision_latency_ms,
            expected_horizon_seconds=float(signal.expected_horizon_seconds),
            seconds_to_next_funding=seconds_to_next_funding,
            current_funding_rate_bps=current_funding_rate_bps,
            uncertainty_buffer_bps=signal.uncertainty_buffer_bps,
        )
    except ValueError as exc:
        return _reject(sc.REJECT_COST_UNAVAILABLE, f"cost model rejected inputs: {exc}")

    if not edge.admitted:
        code = sc.REJECT_NEGATIVE_NET_EDGE if edge.net_expected_edge_bps <= 0 else sc.REJECT_EDGE_BELOW_BUFFER
        return sc.SignalEvaluation(
            signal_id=signal.signal_id,
            admitted=False,
            decision_code=code,
            decision_reasons=(
                f"net_expected_edge_bps={edge.net_expected_edge_bps:.2f} <= "
                f"minimum_net_edge_bps={edge.minimum_net_edge_bps:.2f}",
            ),
            gross_expected_move_bps=edge.gross_expected_move_bps,
            expected_cost_bps=edge.all_in_cost_bps,
            uncertainty_buffer_bps=edge.uncertainty_buffer_bps,
            net_expected_edge_bps=edge.net_expected_edge_bps,
            p0_segment_key="",
            p0_strict_ev=False,
            p0_readiness_eligible=False,
            risk_allowed=False,
            risk_reason=code,
            evaluated_at_ms=now_ms,
        )

    # 7-8. P0 segment key + central P0 gate (§16 steps 7-8) -- reuse the
    # existing gate rather than reimplementing it (Gate G0 finding).
    segment_key = P0SegmentEVGate.build_segment_key(
        symbol=signal.symbol,
        side=signal.side,
        regime=signal.regime,
        source=signal.learning_source,
        tp_sl_profile=signal.exit_profile,
    )
    segment_key_str = (
        f"{segment_key.symbol}:{segment_key.side}:{segment_key.regime}:"
        f"{segment_key.source}:{segment_key.tp_sl_profile}"
    )

    is_quarantined, quarantine_reason = P0SegmentEVGate.is_quarantined_for_strict_ev(signal.symbol, signal.regime)
    is_evidence_eligible, evidence_reason = P0SegmentEVGate.is_eligible_for_evidence_collection(signal.symbol, signal.regime)

    # §2.4: "All new strategies begin as evidence-only sources
    # (strict_ev=false, readiness_eligible=false) until they separately
    # satisfy the existing central eligibility rules." A strategy or signal
    # marked evidence_only=True can never receive strict_ev/readiness
    # regardless of what the underlying segment stats would otherwise allow.
    strict_ev = False
    readiness_eligible = False
    p0_reason = quarantine_reason if is_quarantined else evidence_reason

    if not registration.evidence_only and not signal.evidence_only and not is_quarantined:
        stats = P0SegmentEVGate.compute_segment_stats(list(closed_trades), segment_key)
        if stats is not None:
            decision = P0SegmentEVGate.evaluate_segment_for_strict_ev(stats)
            strict_ev = decision.strict_ev_allowed
            readiness_eligible = decision.readiness_eligible
            p0_reason = decision.reason

    if is_quarantined:
        p0_code = sc.P0_REJECT_QUARANTINED
        admitted_by_p0 = False
    elif not is_evidence_eligible and not strict_ev:
        p0_code = sc.P0_REJECT_NOT_IN_EVIDENCE_SCOPE
        admitted_by_p0 = False
    else:
        p0_code = sc.P0_ADMIT_STRICT_EV if strict_ev else sc.P0_ADMIT_EVIDENCE_COLLECTION
        admitted_by_p0 = True

    # 9. Risk guard (§16 step 9). Only actually evaluated if P0 would
    # otherwise admit -- an already-rejected signal has no need to touch
    # live risk state (position lists, daily-DD tracker, Firebase health),
    # keeping the common (rejected) path cheap and side-effect-free, same
    # as the cost-check short-circuit above.
    risk_code = sc.REJECT_RISK_UNAVAILABLE
    if not admitted_by_p0:
        risk_allowed = False
        risk_reason = "risk guard not evaluated -- signal already rejected upstream (P0)"
    else:
        guard = risk_guard_fn if risk_guard_fn is not None else evaluate_risk_guard
        try:
            result = guard(symbol=signal.symbol, side=signal.side)
            risk_allowed = bool(result.allowed)
            risk_reason = result.reason if not risk_allowed else "risk guard: OK"
            if not risk_allowed:
                risk_code = sc.REJECT_RISK_DENIED
        except Exception as exc:  # fail closed (§2.5) -- never let a risk-guard
            # exception silently become a permissive default.
            risk_allowed = False
            risk_reason = f"risk guard raised: {exc!r}"
            risk_code = sc.REJECT_RISK_UNAVAILABLE

    admitted = admitted_by_p0 and risk_allowed

    return sc.SignalEvaluation(
        signal_id=signal.signal_id,
        admitted=admitted,
        decision_code=p0_code if not admitted_by_p0 else (risk_code if not risk_allowed else p0_code),
        decision_reasons=(p0_reason, risk_reason) if not admitted else (p0_reason,),
        gross_expected_move_bps=edge.gross_expected_move_bps,
        expected_cost_bps=edge.all_in_cost_bps,
        uncertainty_buffer_bps=edge.uncertainty_buffer_bps,
        net_expected_edge_bps=edge.net_expected_edge_bps,
        p0_segment_key=segment_key_str,
        p0_strict_ev=strict_ev,
        p0_readiness_eligible=readiness_eligible,
        risk_allowed=risk_allowed,
        risk_reason=risk_reason,
        evaluated_at_ms=now_ms,
    )
