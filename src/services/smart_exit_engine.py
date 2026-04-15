"""
Smart Exit Engine — Active profit-taking + loss-cutting (NOT timeout-dependent).

Replaces timeout-dominated exit logic with:
1. Partial take-profit at 50% of TP target
2. Early stop-loss at 60% of SL limit
3. Trailing adaptive stop
4. Stagnation exit (no movement for extended period)

Exit decisions are ACTIVE, not time-based.
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


@dataclass
class Position:
    """Active trading position."""

    symbol: str
    entry_price: float
    tp: float
    sl: float
    pnl_pct: float  # Current P&L as percentage
    age_seconds: int  # How long position has been open
    timestamp_opened: datetime
    direction: str  # "LONG" or "SHORT"
    original_sl: float  # Original stop loss for comparisons

    @property
    def age_minutes(self) -> float:
        """Position age in minutes."""
        return self.age_seconds / 60.0


class SmartExitEngine:
    """
    Intelligent position exit engine.
    
    Evaluates active profit-taking, loss-cutting, and stagnation conditions.
    """

    def __init__(
        self,
        partial_tp_threshold: float = 0.5,  # 50% of TP = partial take-profit
        early_stop_threshold: float = 0.6,  # 60% of SL = early stop
        trailing_stop_pnl_pct: float = 0.5,  # Trail stop at 50% of current PnL
        stagnation_age_minutes: int = 30,  # Exit if stagnant for 30 mins
        stagnation_min_pnl: float = 0.0001,  # If |PnL| < this, it's stagnant
    ):
        self.partial_tp_threshold = partial_tp_threshold
        self.early_stop_threshold = early_stop_threshold
        self.trailing_stop_pnl_pct = trailing_stop_pnl_pct
        self.stagnation_age_minutes = stagnation_age_minutes
        self.stagnation_min_pnl = stagnation_min_pnl

    def evaluate(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Evaluate position for exit conditions.
        
        Returns:
        {
            "exit_type": "PARTIAL_TP" | "EARLY_STOP" | "TRAILING_STOP" | "STAGNATION_EXIT",
            "price": exit_price,
            "reason": description,
            "exit_pnl_pct": expected_pnl,
            "confidence": 0.0-1.0
        }
        or None if no exit condition met.
        """

        # Check 1: Partial Take Profit
        partial_tp_result = self._check_partial_tp(position)
        if partial_tp_result:
            return partial_tp_result

        # Check 2: Early Stop Loss
        early_stop_result = self._check_early_stop(position)
        if early_stop_result:
            return early_stop_result

        # Check 3: Trailing Adaptive Stop
        trailing_result = self._check_trailing_stop(position)
        if trailing_result:
            return trailing_result

        # Check 4: Stagnation Exit
        stagnation_result = self._check_stagnation(position)
        if stagnation_result:
            return stagnation_result

        return None

    def _check_partial_tp(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Take profit at 50% of TP target (early partial profit).
        """
        if position.pnl_pct <= 0:
            return None

        # Calculate what 50% of the TP move is
        tp_distance = position.tp - position.entry_price
        partial_target = position.entry_price + tp_distance * self.partial_tp_threshold

        if (
            position.direction == "LONG"
            and position.pnl_pct >= self.partial_tp_threshold * (position.tp - position.entry_price) / position.entry_price
        ):
            return {
                "exit_type": "PARTIAL_TP",
                "price": partial_target,
                "reason": f"Partial take profit at {self.partial_tp_threshold*100:.0f}% of TP",
                "exit_pnl_pct": position.pnl_pct * 0.5,
                "confidence": 0.85,
            }

        return None

    def _check_early_stop(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Cut losers at 60% of stop loss distance.
        """
        if position.pnl_pct >= 0:
            return None

        # Calculate what 60% of the SL move is
        sl_distance = abs(position.entry_price - position.sl)
        early_stop_price = position.entry_price - sl_distance * self.early_stop_threshold

        if (
            position.direction == "LONG"
            and position.pnl_pct <= -(self.early_stop_threshold * (position.entry_price - position.sl) / position.entry_price)
        ):
            return {
                "exit_type": "EARLY_STOP",
                "price": early_stop_price,
                "reason": f"Early stop loss at {self.early_stop_threshold*100:.0f}% of SL",
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.9,
            }

        return None

    def _check_trailing_stop(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Trailing stop: if in profit, tighten stop to 50% of current PnL.
        """
        if position.pnl_pct <= 0:
            return None

        # Trailing stop only activates if in profit
        trailing_level = position.entry_price + (position.pnl_pct * position.entry_price * self.trailing_stop_pnl_pct)

        # Only exit if price taps trailing stop (this is passive check — actual exit depends on next tick)
        if position.direction == "LONG" and position.entry_price < trailing_level:
            return {
                "exit_type": "TRAILING_STOP",
                "price": trailing_level,
                "reason": f"Trailing stop triggered at {self.trailing_stop_pnl_pct*100:.0f}% of profit",
                "exit_pnl_pct": position.pnl_pct * self.trailing_stop_pnl_pct,
                "confidence": 0.75,
            }

        return None

    def _check_stagnation(self, position: Position) -> Optional[Dict[str, Any]]:
        """
        Exit if position stagnant (no meaningful price movement) for extended period.
        """
        if position.age_minutes < self.stagnation_age_minutes:
            return None

        # If P&L is very small (stagnant), exit
        if abs(position.pnl_pct) < self.stagnation_min_pnl:
            return {
                "exit_type": "STAGNATION_EXIT",
                "price": None,  # Exit at market
                "reason": f"Position stagnant for {position.age_minutes:.0f}m with PnL={position.pnl_pct*100:.4f}%",
                "exit_pnl_pct": position.pnl_pct,
                "confidence": 0.8,
            }

        return None


# Global instance
smart_exit = SmartExitEngine(
    partial_tp_threshold=0.5,
    early_stop_threshold=0.6,
    trailing_stop_pnl_pct=0.5,
    stagnation_age_minutes=30,
    stagnation_min_pnl=0.0001,
)


def evaluate_position_exit(
    symbol: str,
    entry_price: float,
    tp: float,
    sl: float,
    current_price: float,
    age_seconds: int,
    direction: str = "LONG",
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to evaluate if position should exit.
    """
    pnl_pct = (current_price - entry_price) / entry_price if direction == "LONG" else (entry_price - current_price) / entry_price

    position = Position(
        symbol=symbol,
        entry_price=entry_price,
        tp=tp,
        sl=sl,
        pnl_pct=pnl_pct,
        age_seconds=age_seconds,
        timestamp_opened=datetime.now() - timedelta(seconds=age_seconds),
        direction=direction,
        original_sl=sl,
    )

    return smart_exit.evaluate(position)
