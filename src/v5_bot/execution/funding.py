"""Perpetual funding rate and cost calculations for USDⓈ-M Futures."""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta


@dataclass
class FundingSnapshot:
    """Funding rate at a point in time."""
    symbol: str
    funding_rate: float  # e.g., 0.0001 for 0.01%
    next_funding_time: int  # milliseconds until next funding
    timestamp: int  # milliseconds (when snapshot taken from Binance)


class FundingCalculator:
    """Estimates funding costs for holding perpetual positions."""

    # Average funding rates (BTC/ETH typically 0.01-0.05% per 8-hour period)
    DEFAULT_FUNDING_RATE_BPS = 10  # 0.01% per 8 hours (funding_rate_bps in 0.01% units, so 10 = 0.01%)
    DEFAULT_FUNDING_INTERVAL_HOURS = 8  # Binance standard 8-hour funding

    def __init__(self, funding_rate_bps: Optional[float] = None,
                 funding_interval_hours: Optional[float] = None,
                 provenance: str = "PAPER_ESTIMATED"):
        """
        Initialize funding calculator.

        Args:
            funding_rate_bps: Expected funding rate in basis points per interval.
                             If None, uses DEFAULT (10 bps).
            funding_interval_hours: Funding payment interval in hours.
                                   If None, uses DEFAULT (8 hours, Binance standard).
            provenance: "PAPER_ESTIMATED" (conservative assumption) or
                       "BINANCE_PUBLIC_CONFIG" (from Binance API).
        """
        self.funding_rate_bps = funding_rate_bps or self.DEFAULT_FUNDING_RATE_BPS
        self.funding_interval_hours = funding_interval_hours or self.DEFAULT_FUNDING_INTERVAL_HOURS
        self.provenance = provenance

    def calc_funding_cost_8h(self, notional_usd: float, is_long: bool = True) -> float:
        """
        Calculate funding cost for holding 8 hours.

        Args:
            notional_usd: Position size in USD
            is_long: True if long (negative funding = cost), False if short (positive = cost)

        Returns:
            Funding cost in USD (positive = cost to position holder)
        """
        rate = self.funding_rate_bps / 10000  # Convert to decimal (funding_rate_bps is in 0.01% units; 10 bps = 0.01% = 0.0001)
        if is_long:
            # Long positions pay funding when rate is positive
            return notional_usd * rate
        else:
            # Short positions receive funding when rate is positive
            # Reverse the sign for short positions
            return -notional_usd * rate

    def calc_funding_cost_for_duration(self, notional_usd: float, hold_seconds: float,
                                       is_long: bool = True) -> float:
        """
        Estimate funding cost for arbitrary duration.

        Assumes funding paid 3x per day (8-hour intervals).

        Args:
            notional_usd: Position size in USD
            hold_seconds: Duration to hold in seconds
            is_long: True if long

        Returns:
            Estimated funding cost in USD
        """
        hours = hold_seconds / 3600
        periods = hours / 8  # Each period is 8 hours
        return self.calc_funding_cost_8h(notional_usd, is_long=is_long) * periods

    def calc_funding_cost_bps_per_hour(self, is_long: bool = True) -> float:
        """
        Express funding cost in basis points per hour.

        Args:
            is_long: True if long

        Returns:
            Basis points per hour
        """
        # 8-hour funding = self.funding_rate_bps
        # 1 hour = funding_rate_bps / 8
        per_hour = self.funding_rate_bps / 8
        if not is_long:
            per_hour = -per_hour
        return per_hour

    def get_funding_rate(self) -> float:
        """Get current configured funding rate in basis points per 8h."""
        return self.funding_rate_bps

    def set_funding_rate(self, funding_rate_bps: float) -> None:
        """Update funding rate (e.g., after fetching from Binance)."""
        self.funding_rate_bps = funding_rate_bps
