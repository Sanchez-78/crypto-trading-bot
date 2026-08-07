"""Centralized cost model — Evidence-First Strategy Expansion v2, Phase P0.7 (§9).

Additive module. Does NOT change any existing canonical PnL calculation in
paper_trade_executor.py (§9.9: "Do not overwrite the currently canonical PnL
calculation without reconciliation tests. Create parallel diagnostic fields
first if necessary."). This is new admission/observability infrastructure
that P0.8+ strategy modules will consult; it is not wired into the existing
paper_trade_executor open/close path in this phase, and changes zero live
behavior on its own.

Cross-checked against src/clean_core/execution/{fees,funding}.py (an
isolated, independently-tested reference implementation — see
docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md §2) for formula sanity, without
importing from it (clean_core is deliberately isolated by its own tests;
see tests/clean_core/test_no_legacy_runtime_wiring.py).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# Separate env namespace (COST_MODEL_*) from paper_trade_executor.py's
# PAPER_FEE_PCT/PAPER_SLIPPAGE_PCT, so this module can never silently
# reinterpret the executor's live config under a different name. §9.3
# requires explicit, logged, non-secret configuration -- see
# log_effective_cost_config() below.
MAKER_FEE_BPS = _env_float("COST_MODEL_MAKER_FEE_BPS", 2.0)
TAKER_FEE_BPS = _env_float("COST_MODEL_TAKER_FEE_BPS", 4.0)
FUNDING_BUFFER_BPS = _env_float("COST_MODEL_FUNDING_BUFFER_BPS", 0.0)
LATENCY_BUFFER_FLOOR_BPS = _env_float("COST_MODEL_LATENCY_BUFFER_FLOOR_BPS", 0.5)
SLIPPAGE_FLOOR_BPS = _env_float("COST_MODEL_SLIPPAGE_FLOOR_BPS", 0.5)
UNCERTAINTY_BUFFER_BPS = _env_float("COST_MODEL_UNCERTAINTY_BUFFER_BPS", 2.0)
MINIMUM_EDGE_BUFFER_BPS = _env_float("COST_MODEL_MINIMUM_EDGE_BUFFER_BPS", 1.0)
MINIMUM_NET_EDGE_BPS = _env_float("COST_MODEL_MINIMUM_NET_EDGE_BPS", 0.0)

_EXIT_ORDER_TYPE_RAW = os.getenv("COST_MODEL_EXPECTED_EXIT_ORDER_TYPE", "taker").strip().lower()
EXPECTED_EXIT_ORDER_TYPE = _EXIT_ORDER_TYPE_RAW if _EXIT_ORDER_TYPE_RAW in ("maker", "taker") else "taker"


@dataclass(frozen=True)
class CostBreakdown:
    """All-in cost decomposition for one candidate entry (§9.2)."""

    entry_fee_bps: float
    expected_exit_fee_bps: float
    entry_spread_cost_bps: float
    expected_exit_spread_cost_bps: float
    expected_entry_slippage_bps: float
    expected_exit_slippage_bps: float
    expected_funding_bps: float
    latency_adverse_move_bps: float

    @property
    def all_in_cost_bps(self) -> float:
        return (
            self.entry_fee_bps
            + self.expected_exit_fee_bps
            + self.entry_spread_cost_bps
            + self.expected_exit_spread_cost_bps
            + self.expected_entry_slippage_bps
            + self.expected_exit_slippage_bps
            + self.expected_funding_bps
            + self.latency_adverse_move_bps
        )


@dataclass(frozen=True)
class EdgeEvaluation:
    """Net-edge admission result (§9.2 admission rule)."""

    gross_expected_move_bps: float
    cost: CostBreakdown
    uncertainty_buffer_bps: float
    minimum_edge_buffer_bps: float
    minimum_net_edge_bps: float

    @property
    def all_in_cost_bps(self) -> float:
        return self.cost.all_in_cost_bps

    @property
    def required_edge_bps(self) -> float:
        return self.all_in_cost_bps + self.uncertainty_buffer_bps + self.minimum_edge_buffer_bps

    @property
    def net_expected_edge_bps(self) -> float:
        return self.gross_expected_move_bps - self.all_in_cost_bps - self.uncertainty_buffer_bps

    @property
    def admitted(self) -> bool:
        return self.net_expected_edge_bps > self.minimum_net_edge_bps


def entry_spread_cost_bps(side: str, best_bid: float, best_ask: float) -> float:
    """§9.4 -- immediate-taker crossing cost relative to mid, side-aware."""
    if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
        raise ValueError(f"invalid book: bid={best_bid} ask={best_ask}")
    mid = (best_bid + best_ask) / 2.0
    side_u = str(side or "").upper()
    if side_u in ("BUY", "LONG"):
        return (best_ask - mid) / mid * 10_000.0
    if side_u in ("SELL", "SHORT"):
        return (mid - best_bid) / mid * 10_000.0
    raise ValueError(f"unknown side: {side!r}")


def slippage_estimate_bps(
    *,
    requested_notional: float,
    visible_top_notional: float,
    spread_bps: float,
    realized_volatility_bps: float,
    floor_bps: float = SLIPPAGE_FLOOR_BPS,
) -> float:
    """§9.5 -- conservative top-of-book slippage proxy.

    Deliberately named *_estimate*, not *_actual* (§9.5: "Name the field
    honestly") -- this is not a full order-book slippage model.
    """
    if requested_notional < 0 or visible_top_notional < 0:
        raise ValueError("notionals must be non-negative")
    if floor_bps < 0:
        raise ValueError("floor_bps must be non-negative")
    size_pressure = 1.0 if visible_top_notional <= 0 else min(2.0, requested_notional / visible_top_notional)
    size_pressure_component = size_pressure * max(0.0, spread_bps) * 0.5
    volatility_component = max(0.0, realized_volatility_bps) * 0.1
    return floor_bps + size_pressure_component + volatility_component


def latency_cost_bps(
    *,
    decision_latency_ms: float,
    realized_volatility_bps_per_second: float,
    floor_bps: float = LATENCY_BUFFER_FLOOR_BPS,
) -> float:
    """§9.6 -- conservative adverse-move-during-latency estimate."""
    if decision_latency_ms < 0:
        raise ValueError("decision_latency_ms must be non-negative")
    seconds = decision_latency_ms / 1000.0
    return floor_bps + max(0.0, realized_volatility_bps_per_second) * seconds


def funding_cost_bps(
    *,
    side: str,
    expected_horizon_seconds: float,
    seconds_to_next_funding: Optional[float],
    current_funding_rate_bps: Optional[float],
    funding_interval_seconds: float = 8 * 3600.0,
) -> float:
    """§9.7 -- expected funding cost.

    Zero unless the holding horizon plausibly spans a funding settlement.
    A favorable funding direction is floored at zero -- this function only
    ever returns a cost to SUBTRACT from edge (§9.2's admission formula has
    no term for a funding tailwind inflating gross_expected_move_bps; that
    would double-count optimism into the admission gate).
    """
    if expected_horizon_seconds < 0:
        raise ValueError("expected_horizon_seconds must be non-negative")
    if seconds_to_next_funding is None or current_funding_rate_bps is None:
        return FUNDING_BUFFER_BPS
    if seconds_to_next_funding < 0 or funding_interval_seconds <= 0:
        return FUNDING_BUFFER_BPS
    if seconds_to_next_funding > expected_horizon_seconds:
        return 0.0  # position closes before settlement -- §9.7
    side_u = str(side or "").upper()
    sign = 1.0 if side_u in ("BUY", "LONG") else -1.0 if side_u in ("SELL", "SHORT") else 0.0
    signed_rate_bps = current_funding_rate_bps * sign
    return max(0.0, signed_rate_bps) + FUNDING_BUFFER_BPS


def evaluate_edge(
    *,
    side: str,
    gross_expected_move_bps: float,
    best_bid: float,
    best_ask: float,
    requested_notional: float,
    visible_top_notional: float,
    realized_volatility_bps: float,
    realized_volatility_bps_per_second: float,
    decision_latency_ms: float,
    expected_horizon_seconds: float,
    seconds_to_next_funding: Optional[float] = None,
    current_funding_rate_bps: Optional[float] = None,
    expected_exit_order_type: Optional[str] = None,
    uncertainty_buffer_bps: float = UNCERTAINTY_BUFFER_BPS,
    minimum_edge_buffer_bps: float = MINIMUM_EDGE_BUFFER_BPS,
    minimum_net_edge_bps: float = MINIMUM_NET_EDGE_BPS,
) -> EdgeEvaluation:
    """Compose the full §9.2 cost/edge evaluation for one candidate.

    Raises ValueError on non-finite or structurally invalid inputs (fail
    closed per §2.5's "NaN or infinite numbers" / "invalid feature values"
    rejection requirements) rather than silently admitting a bad candidate.
    """
    for name, val in (
        ("gross_expected_move_bps", gross_expected_move_bps),
        ("best_bid", best_bid),
        ("best_ask", best_ask),
        ("requested_notional", requested_notional),
        ("visible_top_notional", visible_top_notional),
        ("realized_volatility_bps", realized_volatility_bps),
        ("realized_volatility_bps_per_second", realized_volatility_bps_per_second),
        ("decision_latency_ms", decision_latency_ms),
        ("expected_horizon_seconds", expected_horizon_seconds),
    ):
        if val is None or not math.isfinite(val):
            raise ValueError(f"{name} must be a finite number, got {val!r}")

    exit_type = (expected_exit_order_type or EXPECTED_EXIT_ORDER_TYPE).strip().lower()
    if exit_type not in ("maker", "taker"):
        raise ValueError(f"expected_exit_order_type must be 'maker' or 'taker', got {exit_type!r}")

    entry_fee = TAKER_FEE_BPS  # entry modeled as taker in this phase (§9.4 default)
    exit_fee = MAKER_FEE_BPS if exit_type == "maker" else TAKER_FEE_BPS

    entry_spread = entry_spread_cost_bps(side, best_bid, best_ask)
    # A maker exit plan is not zero-cost either (§9.4: "do not automatically
    # set spread cost to zero for a maker plan"). Conservatively charge half
    # the taker crossing cost as a non-fill/adverse-selection placeholder
    # until a dedicated maker-fill model is wired into this module -- one
    # already exists elsewhere in this repo (maker_fill_model_v2, currently
    # a read-only offline analysis, not yet wired into live paper fills --
    # see docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md §9 gap table) and should
    # be integrated here rather than duplicated.
    exit_spread = entry_spread if exit_type == "taker" else entry_spread * 0.5

    entry_slip = slippage_estimate_bps(
        requested_notional=requested_notional,
        visible_top_notional=visible_top_notional,
        spread_bps=entry_spread,
        realized_volatility_bps=realized_volatility_bps,
    )
    exit_slip = (
        slippage_estimate_bps(
            requested_notional=requested_notional,
            visible_top_notional=visible_top_notional,
            spread_bps=exit_spread,
            realized_volatility_bps=realized_volatility_bps,
        )
        if exit_type == "taker"
        else 0.0
    )

    funding = funding_cost_bps(
        side=side,
        expected_horizon_seconds=expected_horizon_seconds,
        seconds_to_next_funding=seconds_to_next_funding,
        current_funding_rate_bps=current_funding_rate_bps,
    )
    latency = latency_cost_bps(
        decision_latency_ms=decision_latency_ms,
        realized_volatility_bps_per_second=realized_volatility_bps_per_second,
    )

    cost = CostBreakdown(
        entry_fee_bps=entry_fee,
        expected_exit_fee_bps=exit_fee,
        entry_spread_cost_bps=entry_spread,
        expected_exit_spread_cost_bps=exit_spread,
        expected_entry_slippage_bps=entry_slip,
        expected_exit_slippage_bps=exit_slip,
        expected_funding_bps=funding,
        latency_adverse_move_bps=latency,
    )
    return EdgeEvaluation(
        gross_expected_move_bps=gross_expected_move_bps,
        cost=cost,
        uncertainty_buffer_bps=uncertainty_buffer_bps,
        minimum_edge_buffer_bps=minimum_edge_buffer_bps,
        minimum_net_edge_bps=minimum_net_edge_bps,
    )


def log_effective_cost_config(log) -> None:
    """§9.3 -- log effective non-secret cost-model configuration at startup."""
    log.info(
        "[COST_MODEL_CONFIG] maker_fee_bps=%.2f taker_fee_bps=%.2f "
        "funding_buffer_bps=%.2f latency_buffer_floor_bps=%.2f "
        "slippage_floor_bps=%.2f uncertainty_buffer_bps=%.2f "
        "minimum_edge_buffer_bps=%.2f minimum_net_edge_bps=%.2f "
        "expected_exit_order_type=%s",
        MAKER_FEE_BPS,
        TAKER_FEE_BPS,
        FUNDING_BUFFER_BPS,
        LATENCY_BUFFER_FLOOR_BPS,
        SLIPPAGE_FLOOR_BPS,
        UNCERTAINTY_BUFFER_BPS,
        MINIMUM_EDGE_BUFFER_BPS,
        MINIMUM_NET_EDGE_BPS,
        EXPECTED_EXIT_ORDER_TYPE,
    )
