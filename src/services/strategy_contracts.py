"""Central strategy data contracts — Evidence-First Strategy Expansion v2, §7.

Immutable, typed contracts for the new strategy pipeline (P0.8+). These are
NEW types, additive to the repository; nothing in the existing legacy bot is
changed by adding them. They become load-bearing once P0.8's trend strategy
and the signal router in signal_router.py start emitting/consuming them.

Numeric precision policy (§7.3): fields here use `float` for bps/ratios/
scores (acceptable after the finite-value checks this module and cost_model
enforce), but do NOT use float for prices/quantities/notional in the
execution-plan layer -- that is out of P0.7's scope (no ExecutionPlan/paper
fill changes in this phase; see docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple, Union

FeatureValue = Union[float, int, str, bool]


@dataclass(frozen=True)
class StrategySignal:
    """A candidate signal emitted by a strategy module (§7.2)."""

    signal_id: str
    strategy_id: str
    strategy_version: str

    symbol: str
    side: str
    regime: str
    learning_source: str

    generated_event_time_ms: int
    generated_processing_time_ms: int
    market_data_event_time_ms: int
    feature_snapshot_time_ms: int

    expected_horizon_seconds: int

    reference_price: float
    gross_expected_move_bps: float
    expected_cost_bps: float
    uncertainty_buffer_bps: float
    net_expected_edge_bps: float
    confidence: float

    invalidation_price: float
    initial_stop_price: float
    target_reference_price: Optional[float]
    exit_profile: str

    feature_schema_version: str
    feature_snapshot: Mapping[str, FeatureValue] = field(default_factory=dict)

    reason_codes: Tuple[str, ...] = field(default_factory=tuple)
    evidence_only: bool = True

    def __post_init__(self) -> None:
        # Fail closed on construction (§2.5) rather than deferring validation
        # entirely to the router -- a signal that cannot even be constructed
        # correctly must never reach any admission logic.
        for name in ("strategy_id", "strategy_version", "symbol", "side",
                     "regime", "learning_source", "exit_profile",
                     "feature_schema_version", "signal_id"):
            val = getattr(self, name)
            if not val or not isinstance(val, str):
                raise ValueError(f"StrategySignal.{name} must be a non-empty string, got {val!r}")

        if self.side.upper() not in ("BUY", "SELL", "LONG", "SHORT"):
            raise ValueError(f"StrategySignal.side must be BUY/SELL/LONG/SHORT, got {self.side!r}")

        for name in ("reference_price", "gross_expected_move_bps", "expected_cost_bps",
                     "uncertainty_buffer_bps", "net_expected_edge_bps", "confidence",
                     "invalidation_price", "initial_stop_price"):
            val = getattr(self, name)
            if val is None or not math.isfinite(val):
                raise ValueError(f"StrategySignal.{name} must be a finite number, got {val!r}")

        if self.target_reference_price is not None and not math.isfinite(self.target_reference_price):
            raise ValueError(f"StrategySignal.target_reference_price must be finite or None, got {self.target_reference_price!r}")

        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"StrategySignal.confidence must be in [0,1], got {self.confidence!r}")

        if self.reference_price <= 0:
            raise ValueError(f"StrategySignal.reference_price must be positive, got {self.reference_price!r}")

        if self.expected_horizon_seconds <= 0:
            raise ValueError(f"StrategySignal.expected_horizon_seconds must be positive, got {self.expected_horizon_seconds!r}")

        for name in ("generated_event_time_ms", "generated_processing_time_ms",
                     "market_data_event_time_ms", "feature_snapshot_time_ms"):
            val = getattr(self, name)
            if not isinstance(val, int) or val <= 0:
                raise ValueError(f"StrategySignal.{name} must be a positive integer epoch-ms, got {val!r}")


@dataclass(frozen=True)
class SignalEvaluation:
    """The router's immutable decision for one StrategySignal (§7.4)."""

    signal_id: str
    admitted: bool
    decision_code: str
    decision_reasons: Tuple[str, ...]

    gross_expected_move_bps: float
    expected_cost_bps: float
    uncertainty_buffer_bps: float
    net_expected_edge_bps: float

    p0_segment_key: str
    p0_strict_ev: bool
    p0_readiness_eligible: bool

    risk_allowed: bool
    risk_reason: str

    evaluated_at_ms: int


# ---------------------------------------------------------------------------
# Decision codes (§30) -- reusing the P0 gate's own existing reason strings
# where they already exist (do not create competing versions per §30.4);
# these constants exist so new callers reference a stable name instead of a
# hand-typed literal.
# ---------------------------------------------------------------------------

# Validation (§30.1)
REJECT_SIGNAL_SCHEMA = "REJECT_SIGNAL_SCHEMA"
REJECT_UNKNOWN_STRATEGY = "REJECT_UNKNOWN_STRATEGY"
REJECT_STRATEGY_DISABLED = "REJECT_STRATEGY_DISABLED"
REJECT_STALE_MARKET_DATA = "REJECT_STALE_MARKET_DATA"
REJECT_NONFINITE_VALUE = "REJECT_NONFINITE_VALUE"

# Cost (§30.2)
REJECT_COST_UNAVAILABLE = "REJECT_COST_UNAVAILABLE"
REJECT_NEGATIVE_NET_EDGE = "REJECT_NEGATIVE_NET_EDGE"
REJECT_EDGE_BELOW_BUFFER = "REJECT_EDGE_BELOW_BUFFER"

# P0 (§30.4) -- literal values match p0_segment_ev_gate.py's actual strings,
# not the prompt's assumed names; see docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md
# for the discrepancy this resolves.
P0_ADMIT_STRICT_EV = "P0_ADMIT_STRICT_EV"
P0_ADMIT_EVIDENCE_COLLECTION = "P0_ADMIT_EVIDENCE_COLLECTION"
P0_REJECT_QUARANTINED = "P0_REJECT_QUARANTINED"
P0_REJECT_NOT_IN_EVIDENCE_SCOPE = "P0_REJECT_NOT_IN_EVIDENCE_SCOPE"

# Risk (§30.5)
# REJECT_RISK_UNAVAILABLE: the risk guard itself could not be evaluated
# (raised an exception) -- an infrastructure problem, fails closed.
# REJECT_RISK_DENIED: the risk guard ran successfully and said no (daily-DD
# unsafe, quota degraded, position conflict, or real trading allowed) --
# see p0_risk_guard_v1.py (§17), wired in 2026-08-10.
REJECT_RISK_UNAVAILABLE = "REJECT_RISK_UNAVAILABLE"
REJECT_RISK_DENIED = "REJECT_RISK_DENIED"
