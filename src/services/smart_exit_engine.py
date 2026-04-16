"""
Smart Exit Engine V10.13f — Active profit-taking + loss-cutting.

V10.13f fixes:
- direction: uses BUY/SELL action, NOT current move direction (was broken for losing BUY trades)
- trailing_stop: retracement from peak MFE — requires max_favorable_pnl parameter
- stagnation: reduced to 4 min (was 30 min — never fired before timeout at 5 min max)
- SCRATCH_EXIT: near-flat trades after 3 min → take the scratch instead of timeout
- SHORT direction: fully supported in all checks
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
PARTIAL_TP_THRESHOLD = 0.50    # Fire at 50% of TP move
EARLY_STOP_THRESHOLD = 0.60    # Fire at 60% of SL distance
TRAILING_MIN_PEAK    = 0.001   # Must have been >= 0.1% profitable to trail
TRAILING_RETRACE_PCT = 0.50    # Fire when retraced 50%+ from peak
STAGNATION_MIN_AGE_S = 240     # 4 min — below 5 min timeout ceiling
STAGNATION_MAX_PNL   = 0.0005  # |pnl| < 0.05% = stagnant
SCRATCH_MIN_AGE_S    = 180     # Scratch checks start after 3 min
SCRATCH_MAX_PNL      = 0.0015  # |pnl| < 0.15% = worth scratching early


@dataclass
class Position:
    symbol: str
    entry_price: float
    tp: float
    sl: float
    pnl_pct: float              # Current P&L as fraction
    age_seconds: int
    direction: str              # "LONG" (BUY) or "SHORT" (SELL) — based on action
    max_favorable_pnl: float    # Peak MFE fraction since entry

    @property
    def age_minutes(self) -> float:
        return self.age_seconds / 60.0


class SmartExitEngine:
    """
    Intelligent position exit engine. Checks in priority order:
    1. Partial TP     — 50% of TP reached
    2. Early stop     — 60% of SL reached
    3. Trailing stop  — retraced 50%+ from peak MFE
    4. Scratch        — near flat after 3 min
    5. Stagnation     — completely stuck after 4 min
    """

    def evaluate(self, position: Position) -> Optional[Dict[str, Any]]:
        return (
            self._check_partial_tp(position)
            or self._check_early_stop(position)
            or self._check_trailing_stop(position)
            or self._check_scratch(position)
            or self._check_stagnation(position)
        )

    def _check_partial_tp(self, position: Position) -> Optional[Dict[str, Any]]:
        """Take profit at 50% of TP target — both directions."""
        if position.pnl_pct <= 0:
            return None
        if position.direction == "LONG":
            tp_move = (position.tp - position.entry_price) / position.entry_price
        else:
            tp_move = (position.entry_price - position.tp) / position.entry_price
        if tp_move <= 0:
            return None
        if position.pnl_pct >= PARTIAL_TP_THRESHOLD * tp_move:
            return {
                "exit_type": "PARTIAL_TP",
                "reason": (f"Partial TP {position.pnl_pct*100:.2f}% "
                           f"(50% of {tp_move*100:.2f}% target)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.85,
            }
        return None

    def _check_early_stop(self, position: Position) -> Optional[Dict[str, Any]]:
        """Cut losers at 60% of SL distance — both directions."""
        if position.pnl_pct >= 0:
            return None
        if position.direction == "LONG":
            sl_dist = (position.entry_price - position.sl) / position.entry_price
        else:
            sl_dist = (position.sl - position.entry_price) / position.entry_price
        if sl_dist <= 0:
            return None
        if abs(position.pnl_pct) >= EARLY_STOP_THRESHOLD * sl_dist:
            return {
                "exit_type": "EARLY_STOP",
                "reason": (f"Early stop {position.pnl_pct*100:.2f}% "
                           f"(60% of SL dist {sl_dist*100:.2f}%)"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.90,
            }
        return None

    def _check_trailing_stop(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Retracement-based trailing stop.
        Requires trade to have been >= 0.1% profitable (max_favorable_pnl).
        Fires when current PnL retraces 50%+ from peak, or crosses back to 0.
        """
        if position.max_favorable_pnl < TRAILING_MIN_PEAK:
            return None  # Never meaningfully profitable — skip

        # Retraced all the way back to flat or below
        if position.pnl_pct <= 0:
            return {
                "exit_type": "TRAIL_PROFIT",
                "reason": (f"Full retrace from peak {position.max_favorable_pnl*100:.2f}% "
                           f"to {position.pnl_pct*100:.3f}%"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.85,
            }

        # Partial retrace — gave back 50%+ of peak gain
        retrace_threshold = position.max_favorable_pnl * (1.0 - TRAILING_RETRACE_PCT)
        if position.pnl_pct < retrace_threshold:
            return {
                "exit_type": "TRAIL_PROFIT",
                "reason": (f"50% retrace from peak {position.max_favorable_pnl*100:.2f}% "
                           f"→ now {position.pnl_pct*100:.2f}%"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.80,
            }
        return None

    def _check_scratch(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        V10.13f: Scratch near-flat trades after 3 min.
        Releases capital from stagnant non-directional positions without waiting for
        the full timeout. Fires when |pnl| < 0.15% after 180 seconds.
        """
        if position.age_seconds < SCRATCH_MIN_AGE_S:
            return None
        if abs(position.pnl_pct) < SCRATCH_MAX_PNL:
            return {
                "exit_type": "SCRATCH_EXIT",
                "reason": (f"Scratch: flat after {position.age_seconds}s  "
                           f"pnl={position.pnl_pct*100:.3f}%"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.70,
            }
        return None

    def _check_stagnation(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Exit completely stuck positions after 4 min.
        V10.13f: reduced from 30 min (was dead code — timeout fires at 5 min max).
        Runs after scratch — only catches trades with |pnl| >= 0.15%.
        """
        if position.age_seconds < STAGNATION_MIN_AGE_S:
            return None
        if abs(position.pnl_pct) < STAGNATION_MAX_PNL:
            return {
                "exit_type": "STAGNATION_EXIT",
                "reason": (f"Stagnant {position.age_seconds}s  "
                           f"pnl={position.pnl_pct*100:.4f}%"),
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.80,
            }
        return None


# Global instance
smart_exit = SmartExitEngine()


def evaluate_position_exit(
    symbol: str,
    entry_price: float,
    tp: float,
    sl: float,
    current_price: float,
    age_seconds: int,
    direction: str = "LONG",
    max_favorable_move: float = 0.0,
) -> Optional[Dict[str, Any]]:
    """
    Evaluate if position should exit via smart exit logic.

    direction: "LONG" for BUY action, "SHORT" for SELL action.
               Must be based on position.action, NOT on current price move.
    max_favorable_move: peak MFE fraction — (max_price - entry) / entry for BUY,
                        (entry - min_price) / entry for SELL.
    """
    if direction == "LONG":
        pnl_pct = (current_price - entry_price) / entry_price
    else:
        pnl_pct = (entry_price - current_price) / entry_price

    position = Position(
        symbol=symbol,
        entry_price=entry_price,
        tp=tp,
        sl=sl,
        pnl_pct=pnl_pct,
        age_seconds=age_seconds,
        direction=direction,
        max_favorable_pnl=max_favorable_move,
    )

    return smart_exit.evaluate(position)
