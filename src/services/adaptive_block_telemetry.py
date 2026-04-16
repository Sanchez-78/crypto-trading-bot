"""
V10.13j: Adaptive Block Telemetry — Proves V10.13i zones are working

Logs every hard-block decision showing:
  - Blocker name (OFI_TOXIC_HARD, SKIP_SCORE_HARD, FAST_FAIL_HARD)
  - Score/signal that triggered
  - Current adaptive zone config (hard_floor, soft_ceiling, zone_type)
  - Final decision (HARD reject vs SOFT penalty)
  - Reason and multiplier applied

This proves whether V10.13i is:
  - Actually configured correctly
  - Rescuing signals from hard to soft penalties
  - Adapting zones based on health/idle state
"""

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


def log_adaptive_block(
    blocker_name: str,
    symbol: str,
    score: float,
    health: float,
    idle_seconds: float,
    hard_floor: float,
    soft_ceiling: float,
    zone_type: str,
    result: str,  # "ACCEPT", "SOFT", "HARD"
    reason: Optional[str] = None,
    penalty_multiplier: float = 1.0,
) -> None:
    """
    Log adaptive block decision with telemetry.
    
    Args:
        blocker_name: Type of blocker (OFI_TOXIC_HARD, SKIP_SCORE_HARD, FAST_FAIL_HARD)
        symbol: Trading pair
        score: Signal score or metric value (0-1 scale typically)
        health: System health (0-1)
        idle_seconds: Seconds since last trade
        hard_floor: Current hard-floor threshold
        soft_ceiling: Current soft-ceiling threshold
        zone_type: Zone classification (HEALTHY, MODERATE, SEVERE, CRITICAL)
        result: Final decision (ACCEPT, SOFT, HARD)
        reason: Optional detailed reason
        penalty_multiplier: Soft-penalty multiplier (0.3-1.0)
    """
    log.info(
        f"[HBLOCK] {blocker_name:20} {symbol:8} "
        f"score={score:.3f} health={health:.2f} idle={idle_seconds:.0f}s "
        f"zone={zone_type:8} soft_zone=[{hard_floor:.3f}-{soft_ceiling:.3f}] "
        f"result={result:6} mult={penalty_multiplier:.2f}"
        f"{(' '+reason) if reason else ''}"
    )


def log_adaptive_zone_adjustment(
    zone_type: str,
    hard_floor: float,
    soft_ceiling: float,
    buffer: float,
    health: float,
    idle_seconds: float,
    reason: str,
) -> None:
    """Log when adaptive zone boundaries adjust."""
    log.warning(
        f"[ZONE_ADJUST] {zone_type:8} "
        f"hard_floor={hard_floor:.3f} soft_ceiling={soft_ceiling:.3f} buffer={buffer:.3f} "
        f"(health={health:.2f}, idle={idle_seconds:.0f}s) — {reason}"
    )


def log_pair_suppression(
    symbol: str,
    regime: str,
    wr: float,
    n: int,
    ev: float,
    size_mult: float,
    duration_s: int,
) -> None:
    """Log when a pair is suppressed due to toxicity."""
    log.warning(
        f"[PAIR_SUPPRESS] {symbol:8}/{regime:15} "
        f"WR={wr:.0%} n={n} EV={ev:+.3f} "
        f"size_mult={size_mult:.2f} (suppressed for {duration_s}s)"
    )


def log_soft_penalty_applied(
    blocker_name: str,
    symbol: str,
    reason: str,
    confidence_mult: float,
    size_mult: float,
) -> None:
    """Log when soft penalty is applied instead of hard reject."""
    log.info(
        f"[SOFT_PENALTY] {blocker_name:20} {symbol:8} "
        f"confidence_mult={confidence_mult:.2f} size_mult={size_mult:.2f} "
        f"({reason})"
    )


def log_ofi_block(
    blocker_type: str,
    symbol: str,
    action: str,
    reason: str,
    size_mult: float,
    result: str,  # "HARD" or "SOFT"
    detail: Optional[str] = None,
) -> None:
    """
    Log OFI toxicity block decision.
    
    Args:
        blocker_type: OFI_TOXIC_HARD, OFI_SOFT_SOFT_LIGHT, OFI_SOFT_SOFT_HARD
        symbol: Trading pair
        action: BUY/SELL
        reason: Why OFI is toxic (e.g., "OFI consensus 0.98 (ultra-extreme)")
        size_mult: Size multiplier applied (0.0-1.0)
        result: HARD or SOFT
        detail: Additional context
    """
    log.info(
        f"[OFI_BLOCK] {blocker_type:25} {symbol:8}/{action:4} "
        f"size_mult={size_mult:.2f} result={result:4} "
        f"{reason}"
        f"{(' — '+detail) if detail else ''}"
    )
