"""PnL, fill, and accounting calculations for USDⓈ-M Futures trades."""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime

from .fees import FeeCalculator
from .funding import FundingCalculator
from ..util.datetime_utils import utc_now


@dataclass
class FillRecord:
    """Single fill (entry or exit) record."""
    symbol: str
    side: str  # BUY or SELL
    qty: float  # Asset quantity
    price: float  # Fill price in USD
    timestamp: int  # milliseconds
    received_time: float  # local epoch seconds
    venue: str = "BINANCE_USDM_FUTURES"  # Execution venue

    @property
    def notional_usd(self) -> float:
        """Notional value of fill."""
        return self.qty * self.price


@dataclass
class TradeAccounting:
    """Complete accounting for one round-trip trade."""
    trade_id: str
    symbol: str
    entry_side: str  # BUY or SELL (trade direction)
    entry_fill: Optional[FillRecord] = None
    exit_fill: Optional[FillRecord] = None

    # Costs (positive = cost to us)
    entry_fee_usd: float = 0.0
    exit_fee_usd: float = 0.0
    spread_cost_entry_usd: float = 0.0  # Slippage from book mid to fill
    spread_cost_exit_usd: float = 0.0
    funding_cost_usd: float = 0.0  # Perpetual funding cost during hold
    total_costs_usd: float = 0.0

    # PnL (before and after costs)
    gross_pnl_usd: float = 0.0
    gross_pnl_pct: float = 0.0
    net_pnl_usd: float = 0.0
    net_pnl_pct: float = 0.0

    # State
    is_complete: bool = False  # Both entry and exit filled
    accounting_valid: bool = False  # All costs calculated and valid
    completed_at: Optional[float] = None  # epoch seconds

    def set_entry_fill(self, fill: FillRecord) -> None:
        """Record entry fill."""
        self.entry_fill = fill

    def set_exit_fill(self, fill: FillRecord) -> None:
        """Record exit fill."""
        self.exit_fill = fill
        self.is_complete = True

    def calc_pnl(self, fee_calc: Optional[FeeCalculator] = None,
                 funding_calc: Optional[FundingCalculator] = None) -> Dict[str, float]:
        """
        Calculate all PnL and costs.

        Args:
            fee_calc: FeeCalculator instance
            funding_calc: FundingCalculator instance

        Returns:
            Dict with all accounting values (also stored in self)
        """
        if not self.is_complete or not self.entry_fill or not self.exit_fill:
            return {}

        fee_calc = fee_calc or FeeCalculator()
        funding_calc = funding_calc or FundingCalculator()

        # Entry notional
        entry_notional = self.entry_fill.notional_usd
        exit_notional = self.exit_fill.notional_usd

        # Fees (both sides are takers)
        self.entry_fee_usd = fee_calc.calc_entry_fee(entry_notional, is_taker=True)
        self.exit_fee_usd = fee_calc.calc_exit_fee(exit_notional, is_taker=True)

        # Funding cost during hold
        if self.entry_fill.timestamp > 0 and self.exit_fill.timestamp > 0:
            hold_ms = self.exit_fill.timestamp - self.entry_fill.timestamp
            hold_s = hold_ms / 1000
            is_long = self.entry_side.upper() == "BUY"
            self.funding_cost_usd = funding_calc.calc_funding_cost_for_duration(
                entry_notional, hold_s, is_long=is_long
            )

        # Gross PnL (before costs)
        if self.entry_side.upper() == "BUY":
            # Bought at entry_price, sold at exit_price
            # PnL = (exit_price - entry_price) * qty
            self.gross_pnl_usd = (self.exit_fill.price - self.entry_fill.price) * self.entry_fill.qty
        else:
            # Sold at entry_price, bought back at exit_price
            # PnL = (entry_price - exit_price) * qty
            self.gross_pnl_usd = (self.entry_fill.price - self.exit_fill.price) * self.entry_fill.qty

        if entry_notional != 0:
            self.gross_pnl_pct = (self.gross_pnl_usd / entry_notional) * 100

        # Total costs
        self.total_costs_usd = self.entry_fee_usd + self.exit_fee_usd + self.funding_cost_usd

        # Net PnL (after all costs)
        self.net_pnl_usd = self.gross_pnl_usd - self.total_costs_usd
        if entry_notional != 0:
            self.net_pnl_pct = (self.net_pnl_usd / entry_notional) * 100

        self.accounting_valid = True
        self.completed_at = utc_now().timestamp()

        return {
            "gross_pnl_usd": self.gross_pnl_usd,
            "gross_pnl_pct": self.gross_pnl_pct,
            "entry_fee_usd": self.entry_fee_usd,
            "exit_fee_usd": self.exit_fee_usd,
            "funding_cost_usd": self.funding_cost_usd,
            "total_costs_usd": self.total_costs_usd,
            "net_pnl_usd": self.net_pnl_usd,
            "net_pnl_pct": self.net_pnl_pct,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Export accounting as dict."""
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "entry_side": self.entry_side,
            "entry_price": self.entry_fill.price if self.entry_fill else None,
            "exit_price": self.exit_fill.price if self.exit_fill else None,
            "qty": self.entry_fill.qty if self.entry_fill else None,
            "entry_notional_usd": self.entry_fill.notional_usd if self.entry_fill else None,
            "gross_pnl_usd": self.gross_pnl_usd,
            "gross_pnl_pct": self.gross_pnl_pct,
            "entry_fee_usd": self.entry_fee_usd,
            "exit_fee_usd": self.exit_fee_usd,
            "funding_cost_usd": self.funding_cost_usd,
            "total_costs_usd": self.total_costs_usd,
            "net_pnl_usd": self.net_pnl_usd,
            "net_pnl_pct": self.net_pnl_pct,
            "is_complete": self.is_complete,
            "accounting_valid": self.accounting_valid,
        }
