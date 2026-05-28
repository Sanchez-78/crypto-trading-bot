"""Exit decision logic — TP/SL and other exit conditions."""

from dataclasses import dataclass
from typing import Tuple, Optional
from enum import Enum


class ExitReason(Enum):
    """Reason for trade exit."""
    TARGET_PROFIT = "target_profit"
    STOP_LOSS = "stop_loss"
    TIMEOUT = "timeout"
    MANUAL_CLOSE = "manual_close"
    LIQUIDATION = "liquidation"


@dataclass
class ExitConfig:
    """Configuration for exit behavior."""
    tp_pct: float = 1.5  # Target profit as % of entry
    sl_pct: float = 1.0  # Stop loss as % of entry
    max_hold_seconds: int = 28800  # 8 hours
    timeout_close_at_market: bool = True  # Close at market on timeout
    allow_partial_closes: bool = False


class ExitEvaluator:
    """Evaluates exit conditions for open positions."""

    def __init__(self, config: ExitConfig = None):
        self.config = config or ExitConfig()

    def check_exit(self, current_price: float, entry_price: float, side: str,
                   hold_seconds: int) -> Tuple[bool, Optional[ExitReason]]:
        """
        Check if position should exit.

        Args:
            current_price: Current market price
            entry_price: Entry execution price
            side: BUY or SELL
            hold_seconds: How long position held

        Returns:
            (should_exit: bool, reason: Optional[ExitReason])
        """
        side_upper = side.upper()

        # Check TP
        if side_upper == "BUY":
            tp_price = entry_price * (1 + self.config.tp_pct / 100)
            if current_price >= tp_price:
                return True, ExitReason.TARGET_PROFIT

            # Check SL
            sl_price = entry_price * (1 - self.config.sl_pct / 100)
            if current_price <= sl_price:
                return True, ExitReason.STOP_LOSS
        else:  # SELL
            tp_price = entry_price * (1 - self.config.tp_pct / 100)
            if current_price <= tp_price:
                return True, ExitReason.TARGET_PROFIT

            # Check SL
            sl_price = entry_price * (1 + self.config.sl_pct / 100)
            if current_price >= sl_price:
                return True, ExitReason.STOP_LOSS

        # Check timeout
        if hold_seconds >= self.config.max_hold_seconds:
            return True, ExitReason.TIMEOUT

        return False, None

    def get_exit_price(self, current_price: float, reason: ExitReason) -> float:
        """Get exit price based on exit reason."""
        if reason == ExitReason.TIMEOUT and self.config.timeout_close_at_market:
            return current_price  # Market close
        return current_price

    def calc_potential_pnl(self, entry_price: float, current_price: float,
                           side: str, qty: float) -> float:
        """Calculate current unrealized PnL."""
        if side.upper() == "BUY":
            pnl = (current_price - entry_price) * qty
        else:
            pnl = (entry_price - current_price) * qty
        return pnl

    def calc_max_favorable_excursion(self, entry_price: float, high_price: float,
                                     side: str) -> float:
        """Calculate maximum favorable excursion (MFE) in pct."""
        if side.upper() == "BUY":
            mfe = (high_price - entry_price) / entry_price * 100
        else:
            mfe = (entry_price - high_price) / entry_price * 100
        return max(0, mfe)

    def calc_max_adverse_excursion(self, entry_price: float, low_price: float,
                                    side: str) -> float:
        """Calculate maximum adverse excursion (MAE) in pct."""
        if side.upper() == "BUY":
            mae = (entry_price - low_price) / entry_price * 100
        else:
            mae = (low_price - entry_price) / entry_price * 100
        return max(0, mae)

    def update_config(self, **kwargs) -> None:
        """Update exit config dynamically."""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
