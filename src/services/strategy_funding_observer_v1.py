"""Phase P1.3 -- funding_observer_v1 (Evidence-First Strategy Expansion v2, §15).

A non-trading OBSERVER, not a strategy in the P0.8+ sense. §15 is explicit:
"It must not open a position." This module never imports strategy_contracts.
StrategySignal, never calls signal_router or open_paper_position, and has no
generate_candidates() function -- there is no candidate to route through the
central P0 gate, because nothing here ever proposes an entry (§16's routing
requirement applies to strategies that emit StrategySignal; this module
structurally cannot, so it is intentionally NOT registered in
strategy_registry.py either -- registering it would misrepresent it as a
signal-producing strategy awaiting admission, which it is not).

§15.4 "No trading" -- explicitly out of scope for this module and this
phase: spot hedge, second exchange, transfer logic, cross-venue execution,
atomic two-leg order flow, new API keys. This module computes a diagnostic
score from caller-supplied inputs only; it does not fetch market data, hold
API credentials, or schedule itself. Nothing calls it from the live decision
loop (same confirmed non-wired posture as every other P0.8+ module).

IMPORTANT SCOPE DISTINCTION from this repository's separate, still-open
funding-carry RESEARCH thread (EXTERNAL_AUDIT_PROMPT_v9.md,
scripts/research/funding_carry_v2.py/v3.py, funding_carry_robustness.py):
that thread investigates an actual DELTA-NEUTRAL two-leg (spot + perp short)
carry trade and is explicitly gated behind an external auditor's Q1 ruling
on whether a perp-leg paper track is even in scope -- it has NOT been
authorized as of this module's authorship. This module is deliberately
narrower and does not implement that strategy: it is a single-leg,
directional-signal-free funding *observer* per this document's §15, with no
hedge leg, no perp-execution path, and no claim of being a tradable edge.
The two must not be conflated; see docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md
and EXTERNAL_AUDIT_PROMPT_v9.md for the research thread's own status.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

STRATEGY_ID = "funding_observer"
STRATEGY_VERSION = "1"
LEARNING_SOURCE = "funding_observer_v1"

FUNDING_INTERVAL_SECONDS_DEFAULT = 8 * 3600.0
HOURS_PER_DAY = 24.0
DAYS_PER_YEAR = 365.0

# §15.3 conservative buffers -- module constants for the same reason every
# other P0.8+ phase kept its thresholds as constants rather than env vars in
# this evidence-only stage (see strategy_trend_cost_aware_v1.py's identical
# note): promoting these to configuration is deferred until this module has
# a live wiring point to configure.
DEFAULT_BASIS_RISK_BUFFER_BPS = 2.0
DEFAULT_EXECUTION_RISK_BUFFER_BPS = 1.0


@dataclass(frozen=True)
class FundingObservation:
    """§15.1/§15.2/§15.3 -- one funding-opportunity observation. Every
    annualized field is explicitly labeled as a diagnostic extrapolation,
    never a guaranteed return (§15.2: "Clearly label annualization as a
    diagnostic extrapolation, not guaranteed return")."""

    symbol: str
    observed_at_ms: int

    current_funding_rate_bps: float
    predicted_funding_rate_bps: Optional[float]
    seconds_to_next_funding: Optional[float]
    funding_interval_seconds: float

    mark_price: float
    index_price: Optional[float]
    basis_bps: Optional[float]

    estimated_entry_cost_bps: float
    estimated_exit_cost_bps: float
    basis_risk_buffer_bps: float
    execution_risk_buffer_bps: float

    expected_funding_capture_bps_per_interval: float
    expected_funding_capture_bps_per_24h: float
    expected_funding_capture_annualized_pct_diagnostic_only: float

    expected_net_funding_return_bps: float

    liquidity_proxy: Optional[float]
    spread_bps: Optional[float]
    realized_volatility_bps: Optional[float]

    def __post_init__(self) -> None:
        # Fail closed on construction (§2.5), same discipline as
        # StrategySignal.__post_init__ in strategy_contracts.py.
        if not self.symbol:
            raise ValueError("FundingObservation.symbol must be non-empty")
        if self.observed_at_ms <= 0:
            raise ValueError("FundingObservation.observed_at_ms must be a positive epoch-ms")
        if self.mark_price <= 0:
            raise ValueError("FundingObservation.mark_price must be positive")
        if self.funding_interval_seconds <= 0:
            raise ValueError("FundingObservation.funding_interval_seconds must be positive")
        for name in ("current_funding_rate_bps", "estimated_entry_cost_bps",
                     "estimated_exit_cost_bps", "basis_risk_buffer_bps",
                     "execution_risk_buffer_bps",
                     "expected_funding_capture_bps_per_interval",
                     "expected_funding_capture_bps_per_24h",
                     "expected_funding_capture_annualized_pct_diagnostic_only",
                     "expected_net_funding_return_bps"):
            val = getattr(self, name)
            if val is None or not math.isfinite(val):
                raise ValueError(f"FundingObservation.{name} must be a finite number, got {val!r}")


def normalize_funding_rate(
    *,
    rate_bps_per_interval: float,
    funding_interval_seconds: float = FUNDING_INTERVAL_SECONDS_DEFAULT,
) -> tuple:
    """§15.2 -- normalize a per-interval funding rate to (per_24h,
    annualized_pct_diagnostic_only). The annualized figure is a linear
    extrapolation of the CURRENT rate held constant for a year -- it is a
    diagnostic magnitude check, never a forecast (funding rates are not
    stationary; see the funding-carry research thread's own finding that
    the edge decays and is regime-dependent)."""
    if funding_interval_seconds <= 0:
        raise ValueError("funding_interval_seconds must be positive")
    if not math.isfinite(rate_bps_per_interval):
        raise ValueError("rate_bps_per_interval must be finite")
    intervals_per_day = (HOURS_PER_DAY * 3600.0) / funding_interval_seconds
    per_24h = rate_bps_per_interval * intervals_per_day
    annualized_pct_diagnostic_only = (per_24h * DAYS_PER_YEAR) / 100.0  # bps/day -> pct/year
    return per_24h, annualized_pct_diagnostic_only


def expected_net_funding_return_bps(
    *,
    expected_funding_capture_bps: float,
    entry_cost_bps: float,
    exit_cost_bps: float,
    basis_risk_buffer_bps: float = DEFAULT_BASIS_RISK_BUFFER_BPS,
    execution_risk_buffer_bps: float = DEFAULT_EXECUTION_RISK_BUFFER_BPS,
) -> float:
    """§15.3 -- expected_net_funding_return = expected_funding_capture -
    entry_cost - exit_cost - basis_risk_buffer - execution_risk_buffer.
    Pure arithmetic; the caller supplies every term (this module does not
    invent a cost or funding model of its own -- §15.1 says "collect", not
    "estimate from scratch"; the entry/exit cost terms are expected to come
    from cost_model.py's existing §9.2 machinery when a caller wires this
    up, keeping one canonical cost model rather than a second one)."""
    for name, val in (
        ("expected_funding_capture_bps", expected_funding_capture_bps),
        ("entry_cost_bps", entry_cost_bps),
        ("exit_cost_bps", exit_cost_bps),
        ("basis_risk_buffer_bps", basis_risk_buffer_bps),
        ("execution_risk_buffer_bps", execution_risk_buffer_bps),
    ):
        if val is None or not math.isfinite(val):
            raise ValueError(f"{name} must be a finite number, got {val!r}")
    return (
        expected_funding_capture_bps
        - entry_cost_bps
        - exit_cost_bps
        - basis_risk_buffer_bps
        - execution_risk_buffer_bps
    )


def basis_bps(mark_price: float, index_price: Optional[float]) -> Optional[float]:
    """Perpetual/spot(index) basis in bps -- None (unknown, not zero) if
    index_price is unavailable rather than fabricating a value (§8.7 spirit,
    reused: absent data is not evidence of a zero basis)."""
    if index_price is None or index_price <= 0 or mark_price <= 0:
        return None
    return (mark_price - index_price) / index_price * 10_000.0


def observe_funding_opportunity(
    *,
    symbol: str,
    observed_at_ms: int,
    current_funding_rate_bps: float,
    mark_price: float,
    estimated_entry_cost_bps: float,
    estimated_exit_cost_bps: float,
    predicted_funding_rate_bps: Optional[float] = None,
    seconds_to_next_funding: Optional[float] = None,
    funding_interval_seconds: float = FUNDING_INTERVAL_SECONDS_DEFAULT,
    index_price: Optional[float] = None,
    liquidity_proxy: Optional[float] = None,
    spread_bps: Optional[float] = None,
    realized_volatility_bps: Optional[float] = None,
    basis_risk_buffer_bps: float = DEFAULT_BASIS_RISK_BUFFER_BPS,
    execution_risk_buffer_bps: float = DEFAULT_EXECUTION_RISK_BUFFER_BPS,
) -> FundingObservation:
    """§15.1-§15.3 top-level observation builder. Never opens a position,
    never imports from the paper-entry surface (verified by
    tests/test_strategy_funding_observer_v1_bypass.py, same discipline as
    every other P0.8+ module's bypass test). Uses the CURRENT funding rate
    as the capture estimate for the immediate next interval only -- §15.1
    lists "predicted or next funding rate" as a separate, distinct field
    precisely because it is not assumed equal to the current one; this
    function keeps them distinct rather than silently substituting one for
    the other."""
    per_interval = current_funding_rate_bps
    per_24h, annualized_pct = normalize_funding_rate(
        rate_bps_per_interval=per_interval,
        funding_interval_seconds=funding_interval_seconds,
    )
    net_return = expected_net_funding_return_bps(
        expected_funding_capture_bps=per_interval,
        entry_cost_bps=estimated_entry_cost_bps,
        exit_cost_bps=estimated_exit_cost_bps,
        basis_risk_buffer_bps=basis_risk_buffer_bps,
        execution_risk_buffer_bps=execution_risk_buffer_bps,
    )

    return FundingObservation(
        symbol=symbol,
        observed_at_ms=observed_at_ms,
        current_funding_rate_bps=current_funding_rate_bps,
        predicted_funding_rate_bps=predicted_funding_rate_bps,
        seconds_to_next_funding=seconds_to_next_funding,
        funding_interval_seconds=funding_interval_seconds,
        mark_price=mark_price,
        index_price=index_price,
        basis_bps=basis_bps(mark_price, index_price),
        estimated_entry_cost_bps=estimated_entry_cost_bps,
        estimated_exit_cost_bps=estimated_exit_cost_bps,
        basis_risk_buffer_bps=basis_risk_buffer_bps,
        execution_risk_buffer_bps=execution_risk_buffer_bps,
        expected_funding_capture_bps_per_interval=per_interval,
        expected_funding_capture_bps_per_24h=per_24h,
        expected_funding_capture_annualized_pct_diagnostic_only=annualized_pct,
        expected_net_funding_return_bps=net_return,
        liquidity_proxy=liquidity_proxy,
        spread_bps=spread_bps,
        realized_volatility_bps=realized_volatility_bps,
    )
