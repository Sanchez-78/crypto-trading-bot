"""Main learner orchestration — processes eligible trades and updates policy state."""

import logging
from typing import List, Dict, Tuple, Optional
from ..execution.accounting import TradeAccounting
from .eligibility import LearningEligibilityChecker
from .policy_state import PolicyStateTracker, SegmentStats
from ..config import LEARNING_CONFIG

logger = logging.getLogger(__name__)


class V5Learner:
    """Clean learner for V5 PAPER trading."""

    def __init__(self, config=None):
        self.config = config or LEARNING_CONFIG
        self.eligibility_checker = LearningEligibilityChecker(config)
        self.policy_tracker = PolicyStateTracker()
        self.rejected_trades: List[Tuple[str, str]] = []  # (trade_id, reason)

    def process_closed_trade(self, trade: TradeAccounting, segment_id: str,
                            strategy_id: str, regime: str) -> Tuple[bool, str]:
        """
        Process a closed trade for learning.

        Args:
            trade: Closed trade with accounting
            segment_id: Policy segment ID (e.g., "momentum_up_1")
            strategy_id: Which strategy generated entry
            regime: Market regime during trade

        Returns:
            (was_eligible, reason)
        """
        # Check eligibility
        eligible, failures = self.eligibility_checker.check_trade_eligible(trade)

        if not eligible:
            reason = self.eligibility_checker.get_rejection_reason(failures)
            self.rejected_trades.append((trade.trade_id, reason))
            logger.debug(f"Trade {trade.trade_id} rejected: {reason}")
            return False, reason

        # Add to segment tracking
        self.policy_tracker.add_eligible_trade(
            trade, segment_id, strategy_id, regime
        )

        logger.info(
            f"Trade {trade.trade_id} eligible: segment={segment_id}, "
            f"pnl_net={trade.net_pnl_pct:.2f}%"
        )

        return True, "eligible"

    def get_segment_state(self, segment_id: str) -> Optional[Dict]:
        """Get current state of a segment."""
        segment = self.policy_tracker.get_segment(segment_id)
        if not segment:
            return None
        return segment.to_dict()

    def get_strategy_performance(self, strategy_id: str) -> Dict:
        """Get aggregated performance for a strategy."""
        segments = self.policy_tracker.get_segments_for_strategy(strategy_id)

        if not segments:
            return {"strategy_id": strategy_id, "segments": []}

        total_closes = sum(s.total_closes for s in segments)
        total_wins = sum(s.wins for s in segments)
        total_net_pnl = sum(s.total_net_pnl_usd for s in segments)

        return {
            "strategy_id": strategy_id,
            "segments": [s.to_dict() for s in segments],
            "total_closes": total_closes,
            "total_wins": total_wins,
            "win_rate": total_wins / total_closes if total_closes > 0 else None,
            "total_net_pnl_usd": total_net_pnl,
            "avg_pnl_per_trade": total_net_pnl / total_closes if total_closes > 0 else None,
        }

    def get_learning_summary(self) -> Dict:
        """Get overall learning summary."""
        all_segments = list(self.policy_tracker.segments.values())
        total_closes = sum(s.total_closes for s in all_segments)
        total_eligible = sum(s.eligible_closes for s in all_segments)
        total_net_pnl = sum(s.total_net_pnl_usd for s in all_segments)
        total_rejects = len(self.rejected_trades)

        return {
            "total_closed_trades": total_closes,
            "eligible_for_learning": total_eligible,
            "ineligible_trades": total_closes - total_eligible,
            "rejected_summary": self._summarize_rejections(),
            "total_net_pnl_usd": total_net_pnl,
            "segments": self.policy_tracker.summary(),
        }

    def _summarize_rejections(self) -> Dict[str, int]:
        """Summarize rejection reasons."""
        summary = {}
        for _, reason in self.rejected_trades:
            summary[reason] = summary.get(reason, 0) + 1
        return summary
