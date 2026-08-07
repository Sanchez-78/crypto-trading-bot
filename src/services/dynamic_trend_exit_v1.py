"""Phase P1.0 -- dynamic_trend_exit_v1 (Evidence-First Strategy Expansion v2,
Sec 12).

"The existing system historically produced excessive TIMEOUT exits. The new
exit logic must treat timeout as a last-resort safety cap, not the primary
business rule." (Sec 12 header) -- directly relevant to this session's own
earlier forensic finding (docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md and the
day's WR-collapse investigation): 100% TIMEOUT exits observed 2026-08-06/07,
and ~23% of trades breaching a TP/SL band without the band firing. This
module does not touch that live bug (it lives in paper_trade_executor.py's
existing exit evaluation, out of P1.0's scope of "new evidence-only exit
logic for the new strategy pipeline") -- but is designed the way Sec 12
demands specifically so this new pipeline does not reproduce that failure
mode.

Pure, deterministic exit-hierarchy evaluator. Never opens or closes a
position itself -- returns an ExitDecision for a caller (P0.8+ paper
execution glue, not yet wired to any live loop in this phase, exactly like
the other P0.8/P0.9 modules) to act on.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from src.services.order_flow_features import FlowEvaluation
from src.services.strategy_trend_cost_aware_v1 import TrendFeatures

EXIT_PROFILE = "dynamic_trend_exit_v1"

# Reason taxonomy (Sec 12.10) -- stable, machine-readable.
HARD_STOP_STRUCTURAL = "HARD_STOP_STRUCTURAL"
HARD_STOP_VOLATILITY = "HARD_STOP_VOLATILITY"
RISK_LIMIT_EXIT = "RISK_LIMIT_EXIT"
DATA_INTEGRITY_EXIT = "DATA_INTEGRITY_EXIT"
FLOW_REVERSAL_EXIT = "FLOW_REVERSAL_EXIT"
TREND_INVALIDATED = "TREND_INVALIDATED"
REGIME_INVALIDATED = "REGIME_INVALIDATED"
EDGE_DECAY_EXIT = "EDGE_DECAY_EXIT"
TRAILING_STOP_EXIT = "TRAILING_STOP_EXIT"
DYNAMIC_TARGET_EXIT = "DYNAMIC_TARGET_EXIT"
MAX_HOLD_SAFETY_EXIT = "MAX_HOLD_SAFETY_EXIT"
MANUAL_CONTROLLED_STOP = "MANUAL_CONTROLLED_STOP"

# Sec 12.10: "If old dashboards expect TIMEOUT, map it explicitly without
# losing the detailed reason." Old readers see this; new evidence keeps the
# specific code above.
LEGACY_TIMEOUT_LABEL = "TIMEOUT"
_LEGACY_MAP = {MAX_HOLD_SAFETY_EXIT: LEGACY_TIMEOUT_LABEL}


def legacy_exit_label(reason_code: str) -> str:
    return _LEGACY_MAP.get(reason_code, reason_code)


TRAILING_ACTIVATION_ATR_MULTIPLE = 1.5
TRAILING_DISTANCE_ATR_MULTIPLE = 1.0
EDGE_DECAY_EXIT_THRESHOLD_BPS = 0.0
MIN_HOLDING_SECONDS_BEFORE_EDGE_DECAY_EXIT = 30
STRUCTURAL_PERSISTENCE_FLOOR = 0.35


@dataclass(frozen=True)
class ExitDecision:
    reason_code: str
    legacy_label: str
    trigger_price: Optional[float]
    new_stop_price: Optional[float]  # non-None only for TRAILING_STOP_EXIT-adjacent "update stop" signals
    detail: str


@dataclass(frozen=True)
class ExitEvaluationInput:
    side: str
    entry_price: float
    current_price: float
    initial_stop_price: float
    current_stop_price: float
    target_reference_price: Optional[float]
    entry_time_ms: int
    now_ms: int
    max_hold_seconds: int
    atr_bps: float
    mfe_bps: float  # signed favorable-direction bps, side-aware, non-negative by definition
    regime: str
    trend_features: Optional[TrendFeatures] = None
    flow_evaluation: Optional[FlowEvaluation] = None
    remaining_net_edge_bps: Optional[float] = None
    data_integrity_ok: bool = True
    min_holding_seconds: int = 0
    allowed_regimes: Optional[frozenset] = None

    def __post_init__(self) -> None:
        side_u = str(self.side or "").upper()
        if side_u not in ("BUY", "SELL", "LONG", "SHORT"):
            raise ValueError(f"unknown side: {self.side!r}")
        for name in ("entry_price", "current_price", "initial_stop_price", "current_stop_price"):
            v = getattr(self, name)
            if v is None or not math.isfinite(v) or v <= 0:
                raise ValueError(f"{name} must be a positive finite number, got {v!r}")
        if self.now_ms < self.entry_time_ms:
            raise ValueError("now_ms must be >= entry_time_ms")

    @property
    def is_long(self) -> bool:
        return str(self.side or "").upper() in ("BUY", "LONG")

    @property
    def holding_seconds(self) -> float:
        return (self.now_ms - self.entry_time_ms) / 1000.0


def _stop_breached(inp: ExitEvaluationInput) -> bool:
    if inp.is_long:
        return inp.current_price <= inp.current_stop_price
    return inp.current_price >= inp.current_stop_price


def _target_reached(inp: ExitEvaluationInput) -> bool:
    if inp.target_reference_price is None:
        return False
    if inp.is_long:
        return inp.current_price >= inp.target_reference_price
    return inp.current_price <= inp.target_reference_price


def compute_trailing_stop(inp: ExitEvaluationInput) -> Optional[float]:
    """Sec 12.7 -- trailing activates only after MFE clears an ATR multiple,
    and the stop only ever tightens (never loosens): for long,
    new_stop >= old_stop; for short, new_stop <= old_stop."""
    activation_bps = TRAILING_ACTIVATION_ATR_MULTIPLE * inp.atr_bps
    if inp.mfe_bps < activation_bps or inp.atr_bps <= 0:
        return None
    distance = TRAILING_DISTANCE_ATR_MULTIPLE * inp.atr_bps / 10_000.0 * inp.entry_price
    if inp.is_long:
        candidate = inp.current_price - distance
        return max(candidate, inp.current_stop_price)  # never loosens
    candidate = inp.current_price + distance
    return min(candidate, inp.current_stop_price)  # never loosens


def _structural_trend_failed(inp: ExitEvaluationInput) -> bool:
    """Sec 12.5 -- uses the SAME feature representation as entry (Sec 12.5:
    'Use the same or compatible market representation as entry'), not a
    different ad-hoc tick-level check."""
    if inp.trend_features is None:
        return False
    f = inp.trend_features
    if inp.is_long:
        if f.slow_slope_bps_per_minute < 0:
            return True
    else:
        if f.slow_slope_bps_per_minute > 0:
            return True
    if f.trend_persistence_ratio < STRUCTURAL_PERSISTENCE_FLOOR:
        return True
    return False


def _regime_invalidated(inp: ExitEvaluationInput) -> bool:
    if inp.allowed_regimes is None:
        return False
    return inp.regime not in inp.allowed_regimes


def _opposite_flow(inp: ExitEvaluationInput) -> bool:
    """Sec 12.6 -- opposite flow triggers a protective exit here (this
    module's simplified single-hierarchy model folds "reduced holding
    horizon" / "tighter trailing stop" into an outright protective exit
    rather than a partial adjustment, since no position-mutation API for
    partial adjustments exists in this phase). Sec 12.6: 'An exit signal
    must not automatically become an opposite entry signal' -- this
    function, and this whole module, never constructs a new StrategySignal;
    it only ever returns an ExitDecision for the position already open."""
    if inp.flow_evaluation is None:
        return False
    from src.services.order_flow_features import FLOW_CONFLICT_LONG, FLOW_CONFLICT_SHORT
    if inp.is_long:
        return inp.flow_evaluation.reason_code == FLOW_CONFLICT_LONG
    return inp.flow_evaluation.reason_code == FLOW_CONFLICT_SHORT


def evaluate_exit(inp: ExitEvaluationInput) -> Optional[ExitDecision]:
    """Sec 12.1 -- evaluates the exit hierarchy in the documented, fixed
    order and returns the FIRST decision that fires, or None if the
    position should remain open. Deterministic: same input always produces
    the same decision (or lack of one)."""

    # 1. Emergency / data-integrity exit.
    if not inp.data_integrity_ok:
        return ExitDecision(
            DATA_INTEGRITY_EXIT, legacy_exit_label(DATA_INTEGRITY_EXIT),
            trigger_price=inp.current_price, new_stop_price=None,
            detail="data_integrity_ok=False",
        )

    # 2. Hard stop / invalidation.
    if _stop_breached(inp):
        code = HARD_STOP_VOLATILITY if inp.current_stop_price == inp.initial_stop_price else HARD_STOP_STRUCTURAL
        return ExitDecision(
            code, legacy_exit_label(code), trigger_price=inp.current_stop_price,
            new_stop_price=None, detail=f"price {inp.current_price} breached stop {inp.current_stop_price}",
        )

    # 3. Risk-limit exit -- no central risk guard exists yet (same honest
    # gap disclosed in signal_router.py / docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md).
    # This function has nothing to check here in this phase; a future phase
    # wiring a real risk guard adds the check at this exact position in the
    # hierarchy, not elsewhere.

    # 4. Strong opposite-flow exit.
    if _opposite_flow(inp):
        return ExitDecision(
            FLOW_REVERSAL_EXIT, legacy_exit_label(FLOW_REVERSAL_EXIT),
            trigger_price=inp.current_price, new_stop_price=None,
            detail=f"flow_evaluation.reason_code={inp.flow_evaluation.reason_code if inp.flow_evaluation else None}",
        )

    # 5. Structural trend failure.
    if inp.min_holding_seconds <= inp.holding_seconds and _structural_trend_failed(inp):
        return ExitDecision(
            TREND_INVALIDATED, legacy_exit_label(TREND_INVALIDATED),
            trigger_price=inp.current_price, new_stop_price=None,
            detail="slow trend slope reversed or persistence collapsed",
        )
    if _regime_invalidated(inp):
        return ExitDecision(
            REGIME_INVALIDATED, legacy_exit_label(REGIME_INVALIDATED),
            trigger_price=inp.current_price, new_stop_price=None,
            detail=f"regime={inp.regime} no longer in allowed set",
        )

    # 6. Edge-decay exit -- only after minimum holding time (Sec 12.4).
    if (
        inp.holding_seconds >= MIN_HOLDING_SECONDS_BEFORE_EDGE_DECAY_EXIT
        and inp.remaining_net_edge_bps is not None
        and inp.remaining_net_edge_bps <= EDGE_DECAY_EXIT_THRESHOLD_BPS
    ):
        return ExitDecision(
            EDGE_DECAY_EXIT, legacy_exit_label(EDGE_DECAY_EXIT),
            trigger_price=inp.current_price, new_stop_price=None,
            detail=f"remaining_net_edge_bps={inp.remaining_net_edge_bps:.2f}",
        )

    # 7. Profit protection / trailing exit -- this level UPDATES the stop
    # (an ExitDecision with new_stop_price set, trigger_price=None) rather
    # than closing the position; it is still evaluated in this hierarchy
    # slot because it's where Sec 12.1 places it, but it does not terminate
    # the position by itself.
    new_stop = compute_trailing_stop(inp)
    if new_stop is not None and new_stop != inp.current_stop_price:
        return ExitDecision(
            TRAILING_STOP_EXIT, legacy_exit_label(TRAILING_STOP_EXIT),
            trigger_price=None, new_stop_price=new_stop,
            detail=f"trail stop {inp.current_stop_price} -> {new_stop}",
        )

    # 8. Target-based exit.
    if _target_reached(inp):
        return ExitDecision(
            DYNAMIC_TARGET_EXIT, legacy_exit_label(DYNAMIC_TARGET_EXIT),
            trigger_price=inp.target_reference_price, new_stop_price=None,
            detail=f"price {inp.current_price} reached target {inp.target_reference_price}",
        )

    # 9. Maximum-holding safety timeout -- last resort, per this module's
    # own header docstring and Sec 12.9: "rare compared with semantic exits."
    if inp.holding_seconds >= inp.max_hold_seconds:
        return ExitDecision(
            MAX_HOLD_SAFETY_EXIT, legacy_exit_label(MAX_HOLD_SAFETY_EXIT),
            trigger_price=inp.current_price, new_stop_price=None,
            detail=f"holding_seconds={inp.holding_seconds:.0f} >= max_hold_seconds={inp.max_hold_seconds}",
        )

    return None
