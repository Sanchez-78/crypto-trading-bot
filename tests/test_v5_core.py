"""
V5 Production System - Comprehensive Test Suite

Tests for all core modules:
  ✅ EV computation
  ✅ Regime detection
  ✅ Calibration guard
  ✅ Genetic optimizer
  ✅ Self-healing engine
  ✅ Reward engine
  ✅ State builder
  ✅ Main system integration
"""

import pytest
import numpy as np
import logging
from typing import Dict, Any

# Core modules
from src.core.ev import compute_ev, is_positive_ev, compute_break_even_probability, safety_margin
from src.core.regime import detect_regime, analyze_multi_regime, regime_adjustment, RegimeDetector
from src.core.calibration_guard import CalibrationGuard
from src.core.genetic_optimizer import GeneticOptimizer, mutate, crossover
from src.core.reward_engine import RewardEngine
from src.core.state_builder import StateBuilder
from src.services.self_healing import EnhancedSelfHealing

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────
# EV TESTS
# ─────────────────────────────────────────────────────────────────────────

class TestEVModule:
    """Test EV normalization module."""
    
    def test_positive_ev(self):
        """Test profitable signal."""
        ev = compute_ev(0.6, 1.5, 0.01)
        assert ev > 0, "60% win, 1.5 RR should be profitable"
    
    def test_break_even(self):
        """Test break-even signal."""
        ev = compute_ev(0.5, 1.0, 0.01)
        assert abs(ev) < 0.01, "50% win, 1:1 RR should be break-even"
    
    def test_negative_ev(self):
        """Test unprofitable signal."""
        ev = compute_ev(0.45, 1.0, 0.01)
        assert ev < 0, "45% win, 1:1 RR should be unprofitable"
    
    def test_ev_gating(self):
        """Test EV gating function."""
        assert is_positive_ev(0.6, 1.5, 0.01) == True
        assert is_positive_ev(0.45, 1.0, 0.01) == False
    
    def test_break_even_probability(self):
        """Test break-even calculations."""
        be_p = compute_break_even_probability(1.0)
        assert abs(be_p - 0.5) < 0.01, "1:1 RR needs 50%"
        
        be_p = compute_break_even_probability(2.0)
        assert abs(be_p - 0.333) < 0.01, "1:2 RR needs ~33%"
    
    def test_safety_margin(self):
        """Test safety margin calculation."""
        margin = safety_margin(0.6, 1.0)
        assert abs(margin - 10.0) < 0.01, "60% vs 50% break-even = 10%"
        
        margin = safety_margin(0.45, 1.0)
        assert abs(margin - (-5.0)) < 0.01, "45% vs 50% = -5% (unprofitable)"
    
    def test_edge_cases(self):
        """Test edge cases."""
        # Invalid probability (should clamp)
        ev = compute_ev(1.5, 1.0, 0.01)  # p > 1
        assert not np.isnan(ev), "Should handle invalid p"
        
        # Zero ATR (should prevent division by zero)
        ev = compute_ev(0.6, 1.5, 0)
        assert not np.isinf(ev), "Should handle zero ATR"
        
        # Negative ATR (should clamp)
        ev = compute_ev(0.6, 1.5, -0.01)
        assert not np.isnan(ev), "Should handle negative ATR"


# ─────────────────────────────────────────────────────────────────────────
# REGIME DETECTION TESTS
# ─────────────────────────────────────────────────────────────────────────

class TestRegimeDetection:
    """Test regime detection module."""
    
    def test_trend_regime(self):
        """Test TREND regime detection."""
        regime = detect_regime(30, 0.005)
        assert regime == "TREND", "ADX > 25 should be TREND"
    
    def test_range_regime(self):
        """Test RANGE regime detection."""
        regime = detect_regime(10, 0.0001)
        assert regime == "RANGE", "ADX < 15 should be RANGE"
    
    def test_uncertain_regime(self):
        """Test UNCERTAIN regime detection."""
        regime = detect_regime(20, 0.0)
        assert regime == "UNCERTAIN", "ADX between 15-25 should be UNCERTAIN"
    
    def test_regime_multiplier(self):
        """Test EV multiplier for regimes."""
        detector = RegimeDetector()
        
        mult_trend = detector.get_multiplier("TREND")
        assert mult_trend == 1.2, "TREND should boost EV"
        
        mult_range = detector.get_multiplier("RANGE")
        assert mult_range == 0.7, "RANGE should reduce EV"
        
        mult_uncertain = detector.get_multiplier("UNCERTAIN")
        assert mult_uncertain == 0.5, "UNCERTAIN should heavily reduce EV"
    
    def test_multi_timeframe_regime(self):
        """Test multi-TF regime consensus."""
        adx_list = [30, 28, 25]
        ema_slopes = [0.005, 0.004, 0.003]
        
        consensus, confidence = analyze_multi_regime(adx_list, ema_slopes)
        assert consensus == "TREND", "Should agree on TREND"
        assert confidence >= 0.7, "Should have high confidence"
    
    def test_regime_adjustment(self):
        """Test EV adjustment based on regime."""
        base_ev = 0.3
        
        adjusted_trend = regime_adjustment(base_ev, "TREND")
        assert adjusted_trend == 0.36, "TREND: 1.2x boost"
        
        adjusted_range = regime_adjustment(base_ev, "RANGE")
        assert adjusted_range == 0.21, "RANGE: 0.7x reduction"


# ─────────────────────────────────────────────────────────────────────────
# CALIBRATION GUARD TESTS
# ─────────────────────────────────────────────────────────────────────────

class TestCalibrationGuard:
    """Test calibration guard module."""
    
    def test_good_calibration(self):
        """Test well-calibrated model."""
        guard = CalibrationGuard(min_samples=10)
        
        # Perfect calibration: predicted 60%, actual ~60%
        for _ in range(60):
            guard.update(0.6, 1)
        for _ in range(40):
            guard.update(0.6, 0)
        
        assert not guard.is_broken(), "Perfect calibration shouldn't break"
        assert guard.get_calibration_quality() > 0.9, "Should have high quality"
    
    def test_broken_calibration(self):
        """Test miscalibrated model."""
        guard = CalibrationGuard(min_samples=10)
        
        # Predicted 60%, but only 20% actually win
        for _ in range(20):
            guard.update(0.6, 1)
        for _ in range(80):
            guard.update(0.6, 0)
        
        assert guard.is_broken(), "Poor calibration should break"
        assert guard.get_calibration_quality() < 0.5, "Should have low quality"
    
    def test_reliability_multiplier(self):
        """Test EV multiplier based on calibration."""
        guard = CalibrationGuard(drift_threshold=0.15)  # Higher threshold for test
        
        # Before enough samples
        assert guard.get_reliability_multiplier() >= 0.5, "Should be conservative initially"
        
        # Add enough good data - predicted 60%, actual 60%
        for _ in range(60):
            guard.update(0.6, 1)
        for _ in range(40):
            guard.update(0.6, 0)
        
        multiplier = guard.get_reliability_multiplier()
        assert multiplier >= 0.8, "Good calibration should have high multiplier"
    
    def test_statistics(self):
        """Test calibration statistics."""
        guard = CalibrationGuard(min_samples=5)
        
        guard.update(0.6, 1)
        guard.update(0.6, 0)
        guard.update(0.6, 1)
        guard.update(0.6, 0)
        guard.update(0.6, 1)
        
        stats = guard.get_statistics()
        assert stats["samples"] == 5
        assert abs(stats["mean_predicted"] - 0.6) < 0.01
        assert abs(stats["mean_actual"] - 0.6) < 0.01


# ─────────────────────────────────────────────────────────────────────────
# GENETIC OPTIMIZER TESTS
# ─────────────────────────────────────────────────────────────────────────

class TestGeneticOptimizer:
    """Test genetic optimizer module."""
    
    def test_mutation(self):
        """Test parameter mutation."""
        optimizer = GeneticOptimizer()
        strategy = {"ema_fast": 12, "ema_slow": 26}
        
        mutant = optimizer.mutate(strategy, mutation_rate=1.0)
        
        # Should mutate at least one parameter
        changed = mutant != strategy
        assert changed, "Should mutate something"
        
        # Should stay within bounds
        assert 2 <= mutant["ema_fast"] <= 50
        assert 20 <= mutant["ema_slow"] <= 200
    
    def test_crossover(self):
        """Test strategy crossover."""
        optimizer = GeneticOptimizer()
        parent1 = {"ema_fast": 12, "ema_slow": 26}
        parent2 = {"ema_fast": 14, "ema_slow": 24}
        
        child1, child2 = optimizer.crossover(parent1, parent2)
        
        # Children should inherit from parents
        assert child1["ema_fast"] in [12, 14]
        assert child1["ema_slow"] in [26, 24]
        assert child2["ema_fast"] in [12, 14]
        assert child2["ema_slow"] in [26, 24]
    
    def test_fitness_score(self):
        """Test fitness calculation."""
        # Good strategy
        fitness_good = GeneticOptimizer.fitness_score(0.6, 0.01, 1.5, 0.05)
        assert fitness_good > 1.0, "Good strategy should have high fitness"
        
        # Bad strategy
        fitness_bad = GeneticOptimizer.fitness_score(0.4, -0.01, 0.5, 0.3)
        assert fitness_bad < 0.5, "Bad strategy should have low fitness"


# ─────────────────────────────────────────────────────────────────────────
# SELF-HEALING TESTS
# ─────────────────────────────────────────────────────────────────────────

class TestSelfHealing:
    """Test self-healing engine."""
    
    def test_loss_streak_tracking(self):
        """Test loss streak detection."""
        healer = EnhancedSelfHealing(loss_streak_threshold=3)
        
        # No losses yet
        assert healer.loss_streak == 0
        
        # Add losses
        healer.update_trade({"pnl": -0.01, "result": "LOSS"})
        assert healer.loss_streak == 1
        
        healer.update_trade({"pnl": -0.01, "result": "LOSS"})
        assert healer.loss_streak == 2
        
        healer.update_trade({"pnl": -0.01, "result": "LOSS"})
        assert healer.loss_streak == 3
        
        # Win resets streak
        healer.update_trade({"pnl": 0.01, "result": "WIN"})
        assert healer.loss_streak == 0
    
    def test_should_mutate(self):
        """Test mutation trigger."""
        healer = EnhancedSelfHealing(loss_streak_threshold=2, heal_cooldown=0)
        
        healer.update_trade({"pnl": -0.01})
        healer.update_trade({"pnl": -0.01})
        
        assert healer.should_mutate() == True, "Should trigger after 2 losses"
    
    def test_healing_application(self):
        """Test healing action application."""
        healer = EnhancedSelfHealing()
        
        # Mock auto_control object
        class MockControl:
            def __init__(self):
                self.trading_enabled = True
                self.risk_multiplier = 1.0
        
        ctrl = MockControl()
        
        # Apply critical heal
        result = healer.apply_heal("CRITICAL", ctrl)
        assert ctrl.trading_enabled == False, "Critical should pause trading"
        assert ctrl.risk_multiplier == 0.2, "Critical should reduce risk to 20%"


# ─────────────────────────────────────────────────────────────────────────
# REWARD ENGINE TESTS
# ─────────────────────────────────────────────────────────────────────────

class TestRewardEngine:
    """Test reward engine."""
    
    def test_reward_computation(self):
        """Test reward calculation."""
        engine = RewardEngine()
        
        # Profitable trade with take-profit
        trade_good = {
            "pnl": 0.01,
            "exit_reason": "tp",
            "duration_seconds": 300,
            "bars_held": 5,
        }
        reward_good = engine.compute(trade_good)
        assert reward_good > 0.01, "TP exit should reward well"
        
        # Losing trade with stop-loss
        trade_bad = {
            "pnl": -0.01,
            "exit_reason": "sl",
            "duration_seconds": 600,
            "bars_held": 10,
        }
        reward_bad = engine.compute(trade_bad)
        assert reward_bad < -0.01, "SL with loss should penalize"
    
    def test_reward_statistics(self):
        """Test reward tracking."""
        engine = RewardEngine()
        
        engine.compute({"pnl": 0.01, "exit_reason": "tp", "duration_seconds": 300, "bars_held": 5})
        engine.compute({"pnl": -0.01, "exit_reason": "sl", "duration_seconds": 300, "bars_held": 5})
        
        stats = engine.get_stats()
        assert stats["trades_rewarded"] == 2
        assert len(stats) > 0


# ─────────────────────────────────────────────────────────────────────────
# STATE BUILDER TESTS
# ─────────────────────────────────────────────────────────────────────────

class TestStateBuilder:
    """Test state builder."""
    
    def test_state_vector_shape(self):
        """Test state vector has correct shape."""
        builder = StateBuilder()
        
        market_data = {
            "rsi": 50,
            "adx": 25,
            "macd": 0.001,
            "ema_fast": 100,
            "ema_slow": 95,
            "bb_width": 0.05,
            "current_price": 100,
        }
        
        learning_state = {"health": 0.8, "ev": 0.1, "wr": 0.6}
        
        state = builder.build(market_data, learning_state)
        assert len(state) == 8, "Should have 8 features"
        assert all(0 <= s <= 1 for s in state), "All features should be normalized [0,1]"
    
    def test_state_normalization(self):
        """Test normalization ranges."""
        builder = StateBuilder()
        
        # Extreme values
        market_data = {
            "rsi": 100,  # Max RSI
            "adx": 50,   # Max ADX
            "macd": 0.05,
            "ema_fast": 100,
            "ema_slow": 90,
            "bb_width": 0.1,
            "current_price": 100,
        }
        
        state = builder.build(market_data)
        
        # All should be normalized
        assert all(np.isfinite(s) for s in state), "All values should be finite"


# ─────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS
# ─────────────────────────────────────────────────────────────────────────

class TestIntegration:
    """Integration tests for full pipeline."""
    
    def test_ev_with_calibration(self):
        """Test EV computation with calibration guard."""
        guard = CalibrationGuard(min_samples=5)
        
        # Simulate perfect calibration
        for _ in range(50):
            guard.update(0.6, 1)
        for _ in range(50):
            guard.update(0.6, 0)
        
        # Signal EV with calibration boost
        ev = compute_ev(0.6, 1.5, 0.01)
        multiplier = guard.get_reliability_multiplier()
        final_ev = ev * multiplier
        
        assert final_ev > 0, "Should have positive EV"
    
    def test_regime_with_ev(self):
        """Test regime adjustment of EV."""
        base_ev = compute_ev(0.6, 1.5, 0.01)
        
        # In trend
        adjusted = regime_adjustment(base_ev, "TREND")
        assert adjusted > base_ev, "Trend should boost EV"
        
        # In range
        adjusted = regime_adjustment(base_ev, "RANGE")
        assert adjusted < base_ev, "Range should reduce EV"


# ─────────────────────────────────────────────────────────────────────────
# PYTEST CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Run with: python -m pytest tests/test_v5_core.py -v
    pytest.main([__file__, "-v"])
