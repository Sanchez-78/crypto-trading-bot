"""Hard cost-edge gate for entry validation."""

from dataclasses import dataclass
from typing import Dict, Any, Tuple
from ..execution.fees import FeeCalculator
from ..execution.funding import FundingCalculator


@dataclass
class CostBreakdown:
    """Breakdown of all entry costs."""
    entry_notional_usd: float
    entry_fee_usd: float  # Taker entry fee
    exit_fee_usd: float  # Estimated exit fee (same notional assumed)
    funding_cost_8h_usd: float  # Estimated funding for 8-hour hold
    spread_cost_bps: float  # Slippage from mid to fill
    total_cost_bps: float  # All costs as basis points

    def to_dict(self) -> Dict[str, Any]:
        """Export as dict."""
        return {
            "entry_notional_usd": self.entry_notional_usd,
            "entry_fee_usd": self.entry_fee_usd,
            "exit_fee_usd": self.exit_fee_usd,
            "funding_cost_8h_usd": self.funding_cost_8h_usd,
            "spread_cost_bps": self.spread_cost_bps,
            "total_cost_bps": self.total_cost_bps,
        }


class CostEdgeGate:
    """Hard gate enforcing expected move > all costs for entry."""

    def __init__(self, fee_calc: FeeCalculator = None, funding_calc: FundingCalculator = None,
                 safety_margin_bps: float = 5.0):
        """
        Initialize cost-edge gate.

        Args:
            fee_calc: FeeCalculator instance
            funding_calc: FundingCalculator instance
            safety_margin_bps: Additional margin buffer (5 bps default)
        """
        self.fee_calc = fee_calc or FeeCalculator(taker_rate=0.0005)
        self.funding_calc = funding_calc or FundingCalculator(funding_rate_bps=10)
        self.safety_margin_bps = safety_margin_bps

    def calc_cost_breakdown(self, entry_price: float, bid: float, ask: float,
                            entry_qty: float, is_long: bool = True) -> CostBreakdown:
        """
        Calculate detailed cost breakdown for entry.

        Args:
            entry_price: Price at which we will execute
            bid: Current bid price
            ask: Current ask price
            entry_qty: Quantity we will buy/sell
            is_long: True if long, False if short

        Returns:
            CostBreakdown with all costs calculated
        """
        entry_notional = entry_price * entry_qty

        # Fee costs (both entry and exit, assuming same notional)
        entry_fee = self.fee_calc.calc_entry_fee(entry_notional, is_taker=True)
        exit_fee = self.fee_calc.calc_exit_fee(entry_notional, is_taker=True)

        # Funding cost (estimated for 8-hour hold)
        funding_cost_8h = self.funding_calc.calc_funding_cost_8h(entry_notional, is_long=is_long)

        # Spread cost (slippage from mid to fill)
        mid = (bid + ask) / 2
        if is_long:
            # We buy at ask, slippage is ask - mid
            spread_cost = (ask - mid) / mid * 10000
        else:
            # We sell at bid, slippage is mid - bid
            spread_cost = (mid - bid) / mid * 10000

        # Total cost in basis points
        total_cost_bps = (
            (entry_fee + exit_fee + funding_cost_8h) / entry_notional * 10000
            + spread_cost
        )

        return CostBreakdown(
            entry_notional_usd=entry_notional,
            entry_fee_usd=entry_fee,
            exit_fee_usd=exit_fee,
            funding_cost_8h_usd=funding_cost_8h,
            spread_cost_bps=spread_cost,
            total_cost_bps=total_cost_bps,
        )

    def check_entry_allowed(self, expected_move_bps: float, cost_breakdown: CostBreakdown,
                            reason_prefix: str = "") -> Tuple[bool, str]:
        """
        Check if entry passes cost-edge gate.

        Args:
            expected_move_bps: Expected price move (in basis points)
            cost_breakdown: Calculated cost breakdown
            reason_prefix: Prefix for reason string

        Returns:
            (allowed: bool, reason: str)
        """
        required_edge_bps = cost_breakdown.total_cost_bps + self.safety_margin_bps

        if expected_move_bps <= 0:
            return False, f"{reason_prefix}negative_expectancy ({expected_move_bps:.1f} bps)"

        if expected_move_bps < required_edge_bps:
            return False, (
                f"{reason_prefix}insufficient_edge: "
                f"expected={expected_move_bps:.1f} bps < required={required_edge_bps:.1f} bps"
            )

        return True, f"{reason_prefix}edge_valid ({expected_move_bps:.1f} > {required_edge_bps:.1f} bps)"

    def get_minimum_expected_move_bps(self, cost_breakdown: CostBreakdown) -> float:
        """Get minimum expected move needed to pass gate."""
        return cost_breakdown.total_cost_bps + self.safety_margin_bps

    def set_safety_margin(self, margin_bps: float) -> None:
        """Update safety margin."""
        self.safety_margin_bps = margin_bps
