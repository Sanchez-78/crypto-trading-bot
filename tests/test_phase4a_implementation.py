"""Phase 4A Implementation Tests — Paper Learning/Trading Feedback

Tests for:
1. Learning eligibility (include losers)
2. PolicySelector learning feedback integration
3. Cost-edge margin diagnostics
4. Unit correctness (basis points, fee calculations)
"""

import pytest
import logging
from typing import List
from unittest.mock import Mock

logging.basicConfig(level=logging.DEBUG)


# ============================================================================
# SECTION 3: Learning Eligibility Tests
# ============================================================================

class TestLearningEligibilityIncludesLosers:
    """Test that losing trades contribute to segment learning."""

    def test_losing_trade_passes_eligibility(self):
        """Losing trades pass eligibility (net_pnl >= 0 gate removed)."""
        from src.v5_bot.learning.eligibility import LearningEligibilityChecker

        checker = LearningEligibilityChecker()

        # Create mock losing trade
        mock_trade = Mock()
        mock_trade.is_complete = True
        mock_trade.accounting_valid = True

        # Mock fills
        mock_entry = Mock()
        mock_entry.venue = "BINANCE_USDM_FUTURES"
        mock_entry.timestamp = 1000

        mock_exit = Mock()
        mock_exit.venue = "BINANCE_USDM_FUTURES"
        mock_exit.timestamp = 2000

        mock_trade.entry_fill = mock_entry
        mock_trade.exit_fill = mock_exit
        mock_trade.entry_fee_usd = 5.0
        mock_trade.exit_fee_usd = 5.0
        mock_trade.net_pnl_usd = -10.0  # LOSING TRADE

        # Check eligibility
        eligible, failures = checker.check_trade_eligible(mock_trade)

        # Should be eligible (net_pnl >= 0 gate was removed)
        assert eligible, f"Losing trade should be eligible but failed: {failures}"
        assert "negative_pnl" not in failures

    def test_losing_trade_updates_segment_stats(self):
        """Losing trades update segment stats (wins/losses tracked separately)."""
        from src.v5_bot.learning.policy_state import SegmentStats, PolicyStateTracker

        tracker = PolicyStateTracker()

        # Create mock losing trade
        mock_trade = Mock()
        mock_trade.net_pnl_usd = -20.0  # Loss
        mock_trade.gross_pnl_usd = -15.0
        mock_trade.total_costs_usd = 5.0

        mock_fill = Mock()
        mock_fill.notional_usd = 100.0
        mock_trade.entry_fill = mock_fill

        # Add losing trade to segment
        tracker.add_eligible_trade(mock_trade, "BTCUSDT:trending_up:LONG:momentum", "momentum", "trending_up")

        # Verify segment stats updated
        segment = tracker.get_segment("BTCUSDT:trending_up:LONG:momentum")
        assert segment is not None
        assert segment.losses == 1
        assert segment.total_closes == 1
        assert segment.total_net_pnl_usd == -20.0


# ============================================================================
# SECTION 4: PolicySelector Learning Feedback Tests
# ============================================================================

class TestPolicySelectorLearningFeedback:
    """Test PolicySelector applies learning feedback as soft ranking."""

    def test_profitable_segment_ranks_above_losing_segment(self):
        """Profitable segment gets priority boost over losing segment."""
        from src.v5_bot.strategy.policy_selector import PolicySelector
        from src.v5_bot.learning.policy_state import PolicyStateTracker, SegmentStats

        # Create policy selector with tracker
        tracker = PolicyStateTracker()
        selector = PolicySelector(policy_state_tracker=tracker)

        # Create two segments: one profitable, one losing
        profit_segment = SegmentStats(
            segment_id="BTCUSDT:trending:LONG:momentum",
            strategy_id="momentum",
            regime="trending"
        )
        profit_segment.wins = 8
        profit_segment.losses = 2
        profit_segment.eligible_closes = 10
        profit_segment.profit_factor = 4.0  # 8 wins / 2 losses

        loss_segment = SegmentStats(
            segment_id="BTCUSDT:ranging:LONG:momentum",
            strategy_id="momentum",
            regime="ranging"
        )
        loss_segment.wins = 3
        loss_segment.losses = 7
        loss_segment.eligible_closes = 10
        loss_segment.profit_factor = 0.43  # 3 wins / 7 losses

        # Register segments in tracker
        tracker.segments["BTCUSDT:trending:LONG:momentum"] = profit_segment
        tracker.segments["BTCUSDT:ranging:LONG:momentum"] = loss_segment

        # Get learning weights
        profit_weight = tracker.get_segment_learning_weight("BTCUSDT:trending:LONG:momentum")
        loss_weight = tracker.get_segment_learning_weight("BTCUSDT:ranging:LONG:momentum")

        # Profitable should have higher weight
        assert profit_weight > loss_weight
        assert profit_weight > 1.0  # Boost
        assert loss_weight < 1.0  # Penalty

    def test_undertrained_segment_remains_neutral(self):
        """Segment with <10 samples gets neutral weight (no overfit)."""
        from src.v5_bot.learning.policy_state import PolicyStateTracker, SegmentStats

        tracker = PolicyStateTracker()

        # Create undertrained segment (only 3 samples)
        undertrained = SegmentStats(
            segment_id="ETHUSDT:breakout:SHORT:vola",
            strategy_id="vola_break",
            regime="breakout"
        )
        undertrained.wins = 2
        undertrained.losses = 1
        undertrained.eligible_closes = 3
        undertrained.profit_factor = 2.0

        tracker.segments["ETHUSDT:breakout:SHORT:vola"] = undertrained

        # Should get neutral weight (min samples not reached)
        weight = tracker.get_segment_learning_weight("ETHUSDT:breakout:SHORT:vola", min_samples=10)
        assert weight == 1.0  # Neutral, no boost/penalty

    def test_missing_segment_stats_does_not_block_entry(self):
        """Missing segment stats returns neutral weight (no block)."""
        from src.v5_bot.learning.policy_state import PolicyStateTracker

        tracker = PolicyStateTracker()

        # Query non-existent segment
        weight = tracker.get_segment_learning_weight("NONEXISTENT:regime:side:policy")

        # Should return neutral weight (not None, not error)
        assert weight == 1.0


# ============================================================================
# SECTION 5: Cost-Edge Margin Diagnostics Tests
# ============================================================================

class TestCostEdgeMarginDiagnostics:
    """Test cost-edge shadow margin logging."""

    def test_shadow_margin_logged_on_reject(self):
        """Cost-edge rejection includes shadow margin info."""
        from src.v5_bot.strategy.cost_edge_gate import CostEdgeGate, CostBreakdown

        gate = CostEdgeGate(safety_margin_bps=5.0)

        # Create cost breakdown: 100 bps total
        breakdown = CostBreakdown(
            entry_notional_usd=1000.0,
            entry_fee_usd=5.0,      # 5 bps
            exit_fee_usd=5.0,       # 5 bps
            funding_cost_8h_usd=10.0,  # 10 bps
            spread_cost_bps=80.0,   # 80 bps
            total_cost_bps=100.0
        )

        # Expected move: 102 bps (just barely fails with 5 bps margin)
        # Required: 100 + 5 = 105 bps
        allowed, reason = gate.check_entry_allowed(102.0, breakdown)

        # Should reject
        assert not allowed
        # Reason should include shadow margin info
        assert "shadow:" in reason.lower() or "shadow_required" in reason
        assert "2.0" in reason or "shadow_required=102" in reason

    def test_shadow_pass_calculation_correct(self):
        """Shadow margin pass calculation is mathematically correct."""
        from src.v5_bot.strategy.cost_edge_gate import CostEdgeGate, CostBreakdown

        gate = CostEdgeGate(safety_margin_bps=5.0)

        breakdown = CostBreakdown(
            entry_notional_usd=1000.0,
            entry_fee_usd=5.0,
            exit_fee_usd=5.0,
            funding_cost_8h_usd=10.0,
            spread_cost_bps=80.0,
            total_cost_bps=100.0  # 10 bps + 80 bps spread
        )

        # Test expected move: 103 bps
        # Current: needs 105 bps (100 + 5) → REJECT
        # Shadow: needs 102 bps (100 + 2) → PASS
        allowed, reason = gate.check_entry_allowed(103.0, breakdown)

        assert not allowed
        assert "pass=True" in reason or "shadow_pass=True" in reason


# ============================================================================
# HELPER TESTS: Unit Correctness
# ============================================================================

class TestUnitCorrectness:
    """Test basis point calculations and terminology."""

    def test_basis_point_definitions(self):
        """Verify basis point unit definitions (0.05% = 5 bps, 0.02% = 2 bps, 0.10% = 10 bps)."""
        # 1 basis point = 0.01% = 0.0001 in decimal

        # 0.05% fee = 5 basis points
        fee_pct = 0.05
        fee_bps = fee_pct / 0.01
        assert fee_bps == 5.0, f"0.05% should be 5 bps, got {fee_bps}"

        # 0.02% fee = 2 basis points
        fee_pct = 0.02
        fee_bps = fee_pct / 0.01
        assert fee_bps == 2.0, f"0.02% should be 2 bps, got {fee_bps}"

        # 0.10% round-trip = 10 basis points (5 + 5)
        round_trip_pct = 0.05 + 0.05
        round_trip_bps = round_trip_pct / 0.01
        assert round_trip_bps == 10.0, f"0.10% round-trip should be 10 bps, got {round_trip_bps}"

    def test_fee_impact_on_targets(self):
        """Verify fee drag calculations."""
        # On 1.5% TP (150 bps):
        tp_bps = 150.0
        fee_bps = 10.0  # 0.10% round-trip
        net_profit_bps = tp_bps - fee_bps
        fee_ratio = fee_bps / tp_bps

        assert net_profit_bps == 140.0
        assert fee_ratio == pytest.approx(0.0667, abs=0.0001)  # 6.7%

        # On 1.0% SL (100 bps):
        sl_bps = 100.0
        total_cost_bps = sl_bps + fee_bps  # Loss + fees
        cost_ratio = fee_bps / sl_bps

        assert total_cost_bps == 110.0
        assert cost_ratio == 0.10  # 10%


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
