"""
V10.13y: Scratch Exit Repair Logic

Delays scratch exits until MFE is sufficient to cover fees.
Targets PAPER_SCRATCH_EXIT trades which currently dominate losses.

Config gates:
- PAPER_EXIT_REPAIR_ENABLED: boolean (default false)
- PAPER_SCRATCH_FEE_COVER_BPS: basis points needed before triggering scratch
"""

import os
import logging
from typing import Tuple, Dict

log = logging.getLogger(__name__)

# Configuration gates
PAPER_EXIT_REPAIR_ENABLED = os.getenv("PAPER_EXIT_REPAIR_ENABLED", "false").lower() == "true"
PAPER_SCRATCH_FEE_COVER_BPS = int(os.getenv("PAPER_SCRATCH_FEE_COVER_BPS", "20"))
PAPER_STAGNATION_SIZE_DOWN_ENABLED = os.getenv("PAPER_STAGNATION_SIZE_DOWN_ENABLED", "true").lower() == "true"


def should_exit_scratch(
    position: dict,
    hold_seconds: int = 0,
    gross_pnl: float = 0.0,
    fee_cost: float = 0.0,
    size: float = 0.0,
    mfe: float = 0.0,
) -> Tuple[bool, Dict]:
    """
    V10.13y: Decide if scratch exit should trigger now.

    With repair enabled: delay scratch until MFE covers fees or timeout expires.

    Args:
        position: Position dict with symbol, gross_pnl, etc
        hold_seconds: How long position has been open
        gross_pnl: Gross profit/loss (before fees)
        fee_cost: Fee cost in account currency
        size: Position size in USD
        mfe: Max favorable excursion

    Returns:
        (should_exit, decision_dict)
        - should_exit: boolean
        - decision_dict: {reason, hold_s, gross_pnl, fee_cost, mfe, action}
    """
    symbol = position.get("symbol", "UNKNOWN")

    # If repair disabled, use original logic (always exit on scratch signal)
    if not PAPER_EXIT_REPAIR_ENABLED:
        return True, {"reason": "scratch_signal_received", "repair_enabled": False}

    # Calculate fee coverage in basis points
    fee_coverage_bps = 0.0
    if size > 0:
        # fee_coverage_bps = (gross_pnl / (size * 0.01)) * 10000
        # Simplified: gross_pnl (in USD) to basis points of position size
        fee_coverage_bps = (abs(gross_pnl) / (size * 0.01)) * 10000 if size > 0 else 0

    # If MFE is positive but loss doesn't cover fees, wait for more movement
    if abs(gross_pnl) < fee_cost and mfe > 0:
        time_until_timeout = 300 - hold_seconds  # 5-min timeout

        if hold_seconds < 300:  # Within 5-minute window
            log.info(
                f"[SCRATCH_EXIT_DECISION] symbol={symbol} "
                f"hold_s={hold_seconds} gross_pnl={gross_pnl:.8f} fee_cost={fee_cost:.8f} "
                f"mfe={mfe:.8f} fee_coverage_bps={fee_coverage_bps:.1f} "
                f"action=DELAY_WAIT_FOR_MOVE time_until_timeout={time_until_timeout}s"
            )
            return False, {
                "reason": "fee_not_covered_wait_for_move",
                "hold_s": hold_seconds,
                "gross_pnl": gross_pnl,
                "fee_cost": fee_cost,
                "mfe": mfe,
                "fee_coverage_bps": fee_coverage_bps,
                "action": "DELAY",
            }

    # Timeout expired or MFE insufficient - proceed with scratch
    log.info(
        f"[SCRATCH_EXIT_DECISION] symbol={symbol} "
        f"hold_s={hold_seconds} gross_pnl={gross_pnl:.8f} fee_cost={fee_cost:.8f} "
        f"mfe={mfe:.8f} action=PROCEED_SCRATCH"
    )
    return True, {
        "reason": "timeout_or_mfe_insufficient",
        "hold_s": hold_seconds,
        "gross_pnl": gross_pnl,
        "action": "PROCEED",
    }


def should_exit_stagnation(
    position: dict,
    hold_seconds: int = 0,
    segment_pf: float = 0.0,
) -> Tuple[bool, Dict]:
    """
    V10.13y: Decide if stagnation exit should trigger.

    With repair enabled: size down on stagnation if segment PF is bad.

    Args:
        position: Position dict
        hold_seconds: How long open
        segment_pf: Profit factor of segment

    Returns:
        (should_exit, decision_dict)
        - should_exit: boolean
        - decision_dict: {reason, segment_pf, action}
    """
    symbol = position.get("symbol", "UNKNOWN")

    if not PAPER_STAGNATION_SIZE_DOWN_ENABLED:
        return True, {"reason": "stagnation_signal", "sizing_enabled": False}

    # If segment PF is bad, exit at full size (don't compound losses)
    if segment_pf < 0.70:
        log.info(
            f"[STAGNATION_EXIT_DECISION] symbol={symbol} "
            f"segment_pf={segment_pf:.2f} (bad) action=PROCEED_EXIT "
            f"reason=exit_bad_segment"
        )
        return True, {
            "reason": "bad_segment_exit",
            "segment_pf": segment_pf,
            "action": "PROCEED",
        }

    # Segment PF is OK, continue holding
    log.info(
        f"[STAGNATION_EXIT_DECISION] symbol={symbol} "
        f"segment_pf={segment_pf:.2f} (ok) action=CONTINUE_HOLD"
    )
    return False, {
        "reason": "segment_pf_acceptable",
        "segment_pf": segment_pf,
        "action": "HOLD",
    }


def log_repair_effect(
    symbol: str,
    exit_type: str,
    delayed: bool,
    mfe: float,
    pnl_impact: float,
) -> None:
    """
    Log the impact of exit repair on position.

    Args:
        symbol: Ticker
        exit_type: "SCRATCH" or "STAGNATION"
        delayed: Whether exit was delayed
        mfe: MFE achieved
        pnl_impact: PnL change from delay
    """
    log.info(
        f"[PAPER_EXIT_REPAIR_EFFECT] symbol={symbol} exit_type={exit_type} "
        f"delayed={delayed} mfe={mfe:.8f} pnl_impact={pnl_impact:.8f}"
    )
