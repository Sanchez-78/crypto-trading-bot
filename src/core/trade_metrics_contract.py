"""Canonical trade-outcome + PnL-units contract (audit PR3 / P2.9 + P1.8).

Single source of truth for two things that were previously duplicated with
subtly different definitions across the executor, learning, cache and dashboard:

1. The WIN / LOSS / FLAT classification boundary.
2. The unit a PnL number is expressed in (fraction vs percentage-point vs bps
   vs USD).

CANONICAL UNIT: percentage points. A value of ``0.20`` means ``0.20 %``.
The authoritative close math (`paper_trade_executor._calculate_pnl`) already
emits ``net_pnl_pct`` / ``gross_pnl_pct`` / ``fee_pct`` / ``slippage_pct`` in
percentage points; this module does NOT change that math — it only names the
units explicitly and offers pure converters so no field is a fraction in one
place and a percentage point in another.

CANONICAL OUTCOME BOUNDARY (confirmed against paper_trade_executor.py:989-995,
NOT newly invented):

    net_pnl_pct >  +0.05   -> WIN
    net_pnl_pct <  -0.05   -> LOSS
    otherwise (incl. exactly ±0.05) -> FLAT   (deadband, applied AFTER costs)

Everything here is a pure function with no I/O and no global state.
"""
from __future__ import annotations

from enum import Enum
from typing import Sequence

# Bump only when the outcome/units *definition* changes (not on code moves).
# Persisted alongside rows so a reader knows which policy classified them.
OUTCOME_POLICY_VERSION = 1
METRICS_CONTRACT_VERSION = 1

# WIN/LOSS deadband half-width, in percentage points. Matches the long-standing
# ±0.05pp threshold in _calculate_pnl; do not change without a separate mandate.
WIN_THRESHOLD_PCT = 0.05

# Profit factor with zero losses is mathematically +inf. Return a large,
# JSON-safe finite cap instead so the value survives serialization; callers that
# need to disclose the clamp should pair this with a ``profit_factor_capped`` flag.
PROFIT_FACTOR_CAP = 999.0


class TradeOutcome(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    FLAT = "FLAT"


# ── Outcome classification ────────────────────────────────────────────────────

def classify_outcome(net_pnl_pct: float) -> TradeOutcome:
    """Classify a trade by its NET PnL in percentage points (after costs).

    Boundary values (exactly +0.05 / -0.05) are FLAT, matching the historical
    strict ``>``/``<`` comparisons in _calculate_pnl.
    """
    if net_pnl_pct > WIN_THRESHOLD_PCT:
        return TradeOutcome.WIN
    if net_pnl_pct < -WIN_THRESHOLD_PCT:
        return TradeOutcome.LOSS
    return TradeOutcome.FLAT


# ── Unit converters (canonical unit == percentage points) ─────────────────────

def pct_to_fraction(value_pct: float) -> float:
    """0.20 (pct points) -> 0.002 (fraction)."""
    return value_pct / 100.0


def fraction_to_pct(value_fraction: float) -> float:
    """0.002 (fraction) -> 0.20 (pct points)."""
    return value_fraction * 100.0


def pct_to_bps(value_pct: float) -> float:
    """0.20 (pct points) -> 20.0 (bps)."""
    return value_pct * 100.0


def bps_to_pct(value_bps: float) -> float:
    """20.0 (bps) -> 0.20 (pct points)."""
    return value_bps / 100.0


def pct_to_usd(value_pct: float, size_usd: float) -> float:
    """Convert a percentage-point PnL to USD for a given position size."""
    return pct_to_fraction(value_pct) * size_usd


# ── Aggregate metrics ─────────────────────────────────────────────────────────

def compute_profit_factor(net_pnl_values: Sequence[float]) -> float:
    """Profit factor = sum(positive net PnL) / abs(sum(negative net PnL)).

    Uses PnL *magnitudes*, never a win/loss count ratio. Contract:
      - no values, or only zeros/flats            -> 0.0
      - only positive PnL (no losses)             -> PROFIT_FACTOR_CAP
      - otherwise                                 -> gains / abs(losses)
    """
    gains = sum(v for v in net_pnl_values if v > 0)
    losses = sum(v for v in net_pnl_values if v < 0)
    if losses == 0:
        return PROFIT_FACTOR_CAP if gains > 0 else 0.0
    return gains / abs(losses)


def compute_win_rate(outcomes: Sequence[TradeOutcome | str]) -> float:
    """Win rate = WIN / (WIN + LOSS + FLAT), as a fraction in [0, 1].

    FLAT trades are kept in the denominator — this matches the existing paper
    adaptive-learning window definition, so adopting the contract does not shift
    the metric. Returns 0.0 for an empty set.
    """
    total = len(outcomes)
    if total == 0:
        return 0.0
    wins = sum(1 for o in outcomes if _as_outcome(o) is TradeOutcome.WIN)
    return wins / total


def _as_outcome(value: TradeOutcome | str) -> TradeOutcome | None:
    if isinstance(value, TradeOutcome):
        return value
    try:
        return TradeOutcome(str(value).strip().upper())
    except ValueError:
        return None
