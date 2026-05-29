"""Tests for V5 strategy layer."""

import pytest
from src.v5_bot.strategy import (
    StrategyCandidate, StrategyType, StrategyRegime, StrategyRegistry,
    FeatureEngine, MarketFeatures,
    MomentumPolicy, MeanReversionPolicy, VolatilityBreakPolicy,
    PolicySelector,
    CostEdgeGate,
)


class TestStrategyCandidate:
    """Tests for strategy candidates."""

    def test_create_candidate(self):
        """Test creating a strategy candidate."""
        candidate = StrategyCandidate(
            strategy_id="test_01",
            name="Test Strategy",
            strategy_type=StrategyType.MOMENTUM,
            params={"threshold": 0.5},
        )
        assert candidate.strategy_id == "test_01"
        assert candidate.name == "Test Strategy"
        assert candidate.get_param("threshold") == 0.5

    def test_win_rate(self):
        """Test win rate calculation."""
        candidate = StrategyCandidate(
            strategy_id="test_02",
            name="Test",
            strategy_type=StrategyType.MOMENTUM,
        )
        candidate.wins = 7
        candidate.losses = 3
        candidate.flats = 0
        assert candidate.win_rate() == 0.7

    def test_strategy_registry(self):
        """Test strategy registry."""
        registry = StrategyRegistry()

        c1 = StrategyCandidate(
            strategy_id="s1",
            name="Strategy 1",
            strategy_type=StrategyType.MOMENTUM,
            enabled=True,
        )
        c2 = StrategyCandidate(
            strategy_id="s2",
            name="Strategy 2",
            strategy_type=StrategyType.MEAN_REVERSION,
            enabled=False,
        )

        registry.register(c1)
        registry.register(c2)

        assert registry.get("s1") == c1
        assert len(registry.get_enabled()) == 1


class TestFeatureEngine:
    """Tests for market feature extraction."""

    def test_sma_calculation(self):
        """Test SMA calculation."""
        engine = FeatureEngine("BTCUSDT")
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]

        for close in closes:
            engine.add_candle(close, close + 1, close - 1)

        sma_5 = engine.calc_sma(5)
        assert sma_5 is not None
        assert abs(sma_5 - 102.0) < 0.01

    def test_volatility_calculation(self):
        """Test volatility calculation."""
        engine = FeatureEngine("BTCUSDT")
        # Add candles with high variation
        closes = [100.0, 102.0, 98.0, 103.0, 97.0, 105.0, 95.0, 104.0]

        for close in closes:
            engine.add_candle(close, close + 2, close - 2)

        vol = engine.calc_volatility(period=7)
        assert vol is not None
        assert vol > 0

    def test_rsi_calculation(self):
        """Test RSI calculation."""
        engine = FeatureEngine("BTCUSDT")
        # Uptrend: RSI should be high
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0,
                  110.0, 111.0, 112.0, 113.0, 114.0]

        for close in closes:
            engine.add_candle(close, close + 1, close - 1)

        rsi = engine.calc_rsi(14)
        assert rsi is not None
        assert rsi > 60  # Uptrend should have high RSI

    def test_regime_classification(self):
        """Test market regime classification."""
        engine = FeatureEngine("BTCUSDT")
        # Trending upward
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0,
                  110.0, 111.0, 112.0, 113.0, 114.0, 115.0, 116.0, 117.0, 118.0, 119.0,
                  120.0, 121.0, 122.0, 123.0, 124.0]

        for close in closes:
            engine.add_candle(close, close + 1, close - 1)

        regime = engine.classify_regime()
        assert regime is not None
        assert "trending_up" in regime


class TestBaselinePolicies:
    """Tests for baseline trading strategies."""

    def test_momentum_policy(self):
        """Test momentum strategy signal."""
        policy = MomentumPolicy()

        # Create bullish features: SMA_5 > SMA_20, RSI in normal range
        features = MarketFeatures(
            symbol="BTCUSDT",
            current_price=105.0,
            bid=104.9,
            ask=105.1,
            spread_bps=1.9,
            sma_5=105.0,
            sma_20=100.0,
            rsi_14=55.0,
            regime="trending_up_normal_vol",
        )

        should_enter, reason = policy.should_enter(features)
        assert should_enter
        assert "uptrend_momentum" in reason

    def test_mean_reversion_policy(self):
        """Test mean reversion strategy signal."""
        policy = MeanReversionPolicy()

        # Create oversold feature: price << SMA, large ATR
        features = MarketFeatures(
            symbol="BTCUSDT",
            current_price=95.0,
            bid=94.9,
            ask=95.1,
            spread_bps=2.1,
            sma_20=100.0,
            atr_14=3.0,  # 3 * 2.0 = 6.0 threshold, deviation is 5, within range
            regime="ranging_normal_vol",
        )

        # With larger ATR, should exceed threshold
        features.atr_14 = 2.0  # 2 * 2.0 = 4.0 threshold, deviation is 5, exceeds
        should_enter, reason = policy.should_enter(features)
        assert should_enter
        assert "oversold_deviation" in reason

    def test_volatility_break_policy(self):
        """Test volatility breakout strategy."""
        policy = VolatilityBreakPolicy()

        # Create high volatility with breakout
        features = MarketFeatures(
            symbol="BTCUSDT",
            current_price=110.0,
            bid=109.9,
            ask=110.1,
            spread_bps=1.8,
            sma_20=100.0,
            volatility_pct=3.0,  # Above 2.0% threshold
            regime="high_volatility",
        )

        should_enter, reason = policy.should_enter(features)
        assert should_enter
        assert "breakout" in reason


class TestPolicySelector:
    """Tests for strategy selection."""

    def test_selector_initialization(self):
        """Test policy selector initialization."""
        selector = PolicySelector()
        assert len(selector.policies) == 3
        assert "baseline_momentum_01" in selector.policies

    def test_select_for_regime(self):
        """Test selecting strategies for regime."""
        selector = PolicySelector()
        trending_up = selector.select_for_regime("trending_up_normal_vol")
        assert len(trending_up) > 0
        assert any(s.strategy_id == "baseline_momentum_01" for s in trending_up)


class TestCostEdgeGate:
    """Tests for entry cost-edge enforcement."""

    def test_cost_breakdown_calculation(self):
        """Test cost breakdown calculation."""
        gate = CostEdgeGate()

        # Entry at 40010 (ask), qty 1.0 BTC, long
        cost = gate.calc_cost_breakdown(
            entry_price=40010.0,
            bid=40000.0,
            ask=40010.0,
            entry_qty=1.0,
            is_long=True,
        )

        # Entry fee: 40010 * 0.0005 = 20.005
        # Exit fee: 40010 * 0.0005 = 20.005
        # Funding 8h: ~4 (with default rate 10 bps)
        # Spread: 10 / 40005 * 10000 ≈ 2.5 bps

        assert cost.entry_notional_usd == 40010.0
        assert cost.entry_fee_usd > 0
        assert cost.total_cost_bps > 0

    def test_entry_gate_pass(self):
        """Test entry passes cost-edge gate."""
        gate = CostEdgeGate(safety_margin_bps=5.0)

        cost = gate.calc_cost_breakdown(
            entry_price=100.0,
            bid=99.5,
            ask=100.5,
            entry_qty=1.0,
            is_long=True,
        )

        # Expected move 100 bps (very large), should pass
        allowed, reason = gate.check_entry_allowed(100.0, cost)
        assert allowed

    def test_entry_gate_fail_insufficient_edge(self):
        """Test entry fails due to insufficient edge."""
        gate = CostEdgeGate(safety_margin_bps=5.0)

        cost = gate.calc_cost_breakdown(
            entry_price=100.0,
            bid=99.5,
            ask=100.5,
            entry_qty=1.0,
            is_long=True,
        )

        # Expected move 5 bps (tiny), should fail
        allowed, reason = gate.check_entry_allowed(5.0, cost)
        assert not allowed
        assert "insufficient_edge" in reason

    def test_entry_gate_fail_negative_expectancy(self):
        """Test entry fails with negative expectancy."""
        gate = CostEdgeGate()

        cost = gate.calc_cost_breakdown(
            entry_price=100.0,
            bid=99.5,
            ask=100.5,
            entry_qty=1.0,
            is_long=True,
        )

        allowed, reason = gate.check_entry_allowed(-10.0, cost)
        assert not allowed
        assert "negative_expectancy" in reason

    def test_minimum_expected_move_calculation(self):
        """Test calculating minimum required move."""
        gate = CostEdgeGate(safety_margin_bps=10.0)

        cost = gate.calc_cost_breakdown(
            entry_price=100.0,
            bid=99.5,
            ask=100.5,
            entry_qty=1.0,
            is_long=True,
        )

        min_move = gate.get_minimum_expected_move_bps(cost)
        assert min_move > 0
        assert min_move == cost.total_cost_bps + 10.0
