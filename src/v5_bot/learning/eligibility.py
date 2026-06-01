"""Trade eligibility for learning — strict Futures-only accounting requirement."""

from typing import Tuple, List
from ..execution.accounting import TradeAccounting
from ..config import LEARNING_CONFIG


class LearningEligibilityChecker:
    """Determines if closed trades can be used for learning."""

    def __init__(self, config=None):
        self.config = config or LEARNING_CONFIG

    def check_trade_eligible(self, trade: TradeAccounting) -> Tuple[bool, List[str]]:
        """
        Check if trade passes all learning eligibility gates.

        Args:
            trade: Closed trade with accounting

        Returns:
            (eligible: bool, failure_reasons: List[str])
        """
        failures = []

        # Gate 1: Trade must be complete and have valid accounting
        if not trade.is_complete:
            failures.append("incomplete_trade")
        if not trade.accounting_valid:
            failures.append("accounting_invalid")

        if failures:
            return False, failures

        # Gate 2: Must have both entry and exit fills with Binance truth
        if not trade.entry_fill or not trade.exit_fill:
            failures.append("missing_fills")
        elif trade.entry_fill.venue != "BINANCE_USDM_FUTURES" or \
             trade.exit_fill.venue != "BINANCE_USDM_FUTURES":
            failures.append("non_futures_execution")

        # Gate 3: Fees must be accounted for (non-zero)
        if trade.entry_fee_usd == 0 and trade.exit_fee_usd == 0:
            failures.append("fees_not_accounted")

        # Gate 4 (REMOVED): Cost-edge requirement removed to include losing trades
        # All trades with valid accounting/venue/fees/hold contribute to learning.
        # Segment stats track wins/losses separately (no survivorship bias).
        # Learning system can learn from both winners and losers.

        # Gate 5: Must have minimum hold time (to avoid noise)
        if trade.entry_fill and trade.exit_fill:
            hold_ms = trade.exit_fill.timestamp - trade.entry_fill.timestamp
            if hold_ms < 1000:  # Less than 1 second
                failures.append("hold_too_short")

        return len(failures) == 0, failures

    def get_rejection_reason(self, failures: List[str]) -> str:
        """Convert failure list to human-readable reason."""
        if not failures:
            return "eligible"
        return "; ".join(failures)

    def calc_eligible_count(self, trades: List[TradeAccounting]) -> Tuple[int, int]:
        """
        Count eligible vs ineligible trades.

        Returns:
            (eligible_count, total_count)
        """
        eligible = 0
        for trade in trades:
            if self.check_trade_eligible(trade)[0]:
                eligible += 1
        return eligible, len(trades)
