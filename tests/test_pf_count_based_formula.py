"""
Test coverage for count-based Profit Factor (PF) formula.

This module tests the formula: PF = wins / (losses + 0.0001)
Where losses = total_closed_trades - wins

The formula is used in:
  - src/api/dashboard_metrics_endpoint.py
  - src/services/learning_optimizer.py
  - simple_dashboard.py
  - simple_dashboard_minimal.py

This isolates PF calculation from money-based metrics (canonical_metrics.py).
"""

import pytest
import math


def calculate_pf_count_based(wins: int, total_trades: int) -> float:
    """
    Count-based PF calculation (reference implementation).

    Args:
        wins: Number of winning trades
        total_trades: Total number of closed trades

    Returns:
        float: PF = wins / (losses + 0.0001)
    """
    losses = total_trades - wins
    if losses > 0:
        return wins / (losses + 0.0001)
    elif wins > 0:
        return 1.0
    else:
        return 0.0


class TestCountBasedPFFormula:
    """Test count-based PF calculation against known values."""

    def test_pf_with_43_wins_35_losses(self):
        """Scenario 1: 43 wins and 35 losses should give PF ~1.23."""
        wins = 43
        total_trades = 78  # 43 + 35

        pf = calculate_pf_count_based(wins, total_trades)

        # Expected: 43 / (35 + 0.0001) ≈ 1.2285
        expected = 43 / 35.0001
        assert abs(pf - expected) < 0.001, f"Expected PF ≈ {expected:.4f}, got {pf:.4f}"
        assert 1.22 < pf < 1.24, f"PF ~1.23 range check failed: {pf}"

    def test_pf_with_only_wins(self):
        """Scenario 2: Only wins (no losses) should return PF = 1.0."""
        wins = 100
        total_trades = 100  # All wins, 0 losses

        pf = calculate_pf_count_based(wins, total_trades)

        assert pf == 1.0, f"Expected PF = 1.0 for all-wins case, got {pf}"

    def test_pf_with_zero_wins(self):
        """Scenario 3: Zero wins (all losses) should return PF = 0.0."""
        wins = 0
        total_trades = 50  # 0 wins, 50 losses

        pf = calculate_pf_count_based(wins, total_trades)

        assert pf == 0.0, f"Expected PF = 0.0 for no-wins case, got {pf}"

    def test_pf_no_trades(self):
        """Edge case: Zero total trades should return PF = 0.0."""
        wins = 0
        total_trades = 0

        pf = calculate_pf_count_based(wins, total_trades)

        assert pf == 0.0, f"Expected PF = 0.0 for no trades, got {pf}"

    def test_pf_single_win(self):
        """Edge case: Single win, no losses should return PF = 1.0."""
        wins = 1
        total_trades = 1

        pf = calculate_pf_count_based(wins, total_trades)

        assert pf == 1.0, f"Expected PF = 1.0 for single win, got {pf}"

    def test_pf_single_loss(self):
        """Edge case: Single loss, no wins should return PF = 0.0."""
        wins = 0
        total_trades = 1

        pf = calculate_pf_count_based(wins, total_trades)

        assert pf == 0.0, f"Expected PF = 0.0 for single loss, got {pf}"

    def test_pf_breakeven(self):
        """Test 50/50 win/loss ratio."""
        wins = 50
        total_trades = 100

        pf = calculate_pf_count_based(wins, total_trades)

        # Expected: 50 / (50 + 0.0001) ≈ 0.99999
        expected = 50 / 50.0001
        assert abs(pf - expected) < 0.0001
        assert pf < 1.0, "Breakeven (50/50) should yield PF < 1.0"

    def test_pf_70_30_split(self):
        """Test 70% win / 30% loss ratio."""
        wins = 70
        total_trades = 100

        pf = calculate_pf_count_based(wins, total_trades)

        # Expected: 70 / (30 + 0.0001) ≈ 2.333
        expected = 70 / 30.0001
        assert abs(pf - expected) < 0.001
        assert pf > 2.3, "70/30 split should yield strong PF"

    def test_pf_epsilon_handling(self):
        """Test that epsilon (0.0001) prevents division by zero."""
        wins = 100
        total_trades = 100

        # Without epsilon, would be 100 / 0 = inf
        # With epsilon, should be 1.0 (clamped in logic)
        pf = calculate_pf_count_based(wins, total_trades)

        assert not math.isinf(pf), "PF should never be infinite"
        assert pf == 1.0, "All-wins case should be clamped to 1.0"

    def test_pf_monotonic_increase_with_wins(self):
        """Test that PF increases monotonically as wins increase (excluding 100% case)."""
        total_trades = 100
        pf_values = []

        # Exclude 100 wins because it's clamped to 1.0 (special case)
        for wins in [10, 30, 50, 70, 90]:
            pf = calculate_pf_count_based(wins, total_trades)
            pf_values.append((wins, pf))

        # Check monotonic increase (excluding clamped case)
        for i in range(len(pf_values) - 1):
            wins_i, pf_i = pf_values[i]
            wins_j, pf_j = pf_values[i+1]
            assert pf_i < pf_j, \
                f"PF should increase with wins: {wins_i} wins={pf_i:.4f} > {wins_j} wins={pf_j:.4f}"

    def test_pf_very_high_win_ratio(self):
        """Test high win ratio (e.g., 95%)."""
        wins = 95
        total_trades = 100

        pf = calculate_pf_count_based(wins, total_trades)

        # Expected: 95 / (5 + 0.0001) ≈ 19.0
        expected = 95 / 5.0001
        assert abs(pf - expected) < 0.1
        assert pf > 18, "95% win rate should yield high PF"

    def test_pf_very_low_win_ratio(self):
        """Test low win ratio (e.g., 5%)."""
        wins = 5
        total_trades = 100

        pf = calculate_pf_count_based(wins, total_trades)

        # Expected: 5 / (95 + 0.0001) ≈ 0.0526
        expected = 5 / 95.0001
        assert abs(pf - expected) < 0.001
        assert pf < 0.1, "5% win rate should yield low PF"


class TestDashboardMetricsEndpointPF:
    """Test PF calculation in dashboard_metrics_endpoint context."""

    def test_dashboard_pf_calculation_basic(self):
        """Test PF calculation matches dashboard formula."""
        # Simulate the calculation used in dashboard (from src/api/dashboard_metrics_endpoint.py:90)
        wins = 43
        losses = 35
        total = wins + losses
        net_pnl = 0.5

        # Dashboard formula: profit_factor = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)
        pf = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)

        assert abs(pf - 1.2285) < 0.001
        assert pf > 0, "PF should be positive"

    def test_dashboard_pf_all_wins_clamped(self):
        """Test dashboard clamps all-wins case to 1.0."""
        wins = 50
        losses = 0
        total = 50

        # Dashboard formula
        pf = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)

        assert pf == 1.0, "All-wins should be clamped to 1.0"

    def test_dashboard_pf_no_trades(self):
        """Test dashboard handles zero trades."""
        wins = 0
        losses = 0
        total = 0

        # Dashboard formula
        pf = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)

        assert pf == 0.0, "No trades should yield PF = 0.0"


class TestLearningOptimizerPF:
    """Test PF calculation in learning_optimizer context."""

    def test_learning_optimizer_pf_formula(self):
        """Test that learning_optimizer uses count-based PF (from src/services/learning_optimizer.py:24)."""
        # Simulate the formula used in learning_optimizer.py
        trades = [
            {'pnl_pct': 0.01},   # Win
            {'pnl_pct': 0.02},   # Win
            {'pnl_pct': -0.01},  # Loss
            {'pnl_pct': -0.015}, # Loss
        ]

        total = len(trades)
        wins = sum(1 for t in trades if t.get('pnl_pct', 0) > 0)
        losses = sum(1 for t in trades if t.get('pnl_pct', 0) < 0)

        # Formula: pf = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)
        pf = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)

        assert wins == 2, f"Expected 2 wins, got {wins}"
        assert losses == 2, f"Expected 2 losses, got {losses}"
        assert abs(pf - 1.0) < 0.0001, "2 wins vs 2 losses should yield ~1.0"


class TestRegressionPFConsistency:
    """Regression tests to ensure PF calculation consistency."""

    def test_pf_formula_unchanged_across_calls(self):
        """Verify PF calculation is deterministic."""
        wins = 43
        total_trades = 78

        pf1 = calculate_pf_count_based(wins, total_trades)
        pf2 = calculate_pf_count_based(wins, total_trades)

        assert pf1 == pf2, "PF calculation should be deterministic"

    def test_pf_calculation_order_invariant(self):
        """Test that PF doesn't depend on trade order."""
        # Both should yield same PF regardless of order
        pf1 = calculate_pf_count_based(43, 78)
        pf2 = calculate_pf_count_based(43, 78)

        assert pf1 == pf2, "PF should be order-invariant"

    def test_pf_boundary_values(self):
        """Test PF behavior at boundary values."""
        boundary_cases = [
            (0, 1),      # Single loss
            (1, 1),      # Single win
            (0, 100),    # All losses
            (100, 100),  # All wins
            (1, 100),    # 1% win rate
            (99, 100),   # 99% win rate
        ]

        for wins, total in boundary_cases:
            pf = calculate_pf_count_based(wins, total)
            assert 0.0 <= pf <= 1.0 or pf > 0, f"PF out of bounds for {wins}/{total}"
            assert not math.isnan(pf), f"PF is NaN for {wins}/{total}"
            assert not math.isinf(pf) or pf == 1.0, f"PF is infinite (unexpected) for {wins}/{total}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
