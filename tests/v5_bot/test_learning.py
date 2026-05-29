"""Tests for V5 learning layer."""

import pytest
from datetime import datetime
from src.v5_bot.execution.accounting import TradeAccounting, FillRecord
from src.v5_bot.learning.eligibility import LearningEligibilityChecker
from src.v5_bot.learning.learner import V5Learner
from src.v5_bot.learning.policy_state import PolicyStateTracker, SegmentStats
from src.v5_bot.learning.readiness import ReadinessEvaluator, ReadinessState
from src.v5_bot.util.datetime_utils import utc_now


class TestLearningEligibilityChecker:
    """Tests for trade eligibility checking."""

    @pytest.fixture
    def checker(self):
        """Create eligibility checker."""
        return LearningEligibilityChecker()

    @pytest.fixture
    def valid_trade(self):
        """Create a valid eligible trade."""
        trade = TradeAccounting(
            trade_id="trade_valid_1",
            symbol="BTCUSDT",
            entry_side="BUY",
        )

        entry_fill = FillRecord(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            price=40000.0,
            timestamp=1000,
            received_time=utc_now().timestamp(),
            venue="BINANCE_USDM_FUTURES",
        )

        exit_fill = FillRecord(
            symbol="BTCUSDT",
            side="SELL",
            qty=1.0,
            price=40100.0,
            timestamp=2000,
            received_time=utc_now().timestamp(),
            venue="BINANCE_USDM_FUTURES",
        )

        trade.set_entry_fill(entry_fill)
        trade.set_exit_fill(exit_fill)
        trade.calc_pnl()

        return trade

    def test_eligible_trade(self, checker, valid_trade):
        """Test that valid trade passes eligibility."""
        eligible, reasons = checker.check_trade_eligible(valid_trade)
        assert eligible
        assert len(reasons) == 0

    def test_incomplete_trade(self, checker):
        """Test that incomplete trade fails."""
        trade = TradeAccounting(
            trade_id="trade_incomplete",
            symbol="BTCUSDT",
            entry_side="BUY",
        )
        # No fills yet

        eligible, reasons = checker.check_trade_eligible(trade)
        assert not eligible
        assert "incomplete_trade" in reasons

    def test_non_futures_execution(self, checker):
        """Test that non-Futures trades are rejected."""
        trade = TradeAccounting(
            trade_id="trade_spot",
            symbol="BTCUSDT",
            entry_side="BUY",
        )

        entry_fill = FillRecord(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            price=40000.0,
            timestamp=1000,
            received_time=utc_now().timestamp(),
            venue="BINANCE_SPOT",  # Not USDM_FUTURES
        )

        trade.set_entry_fill(entry_fill)
        trade.set_exit_fill(FillRecord(
            symbol="BTCUSDT",
            side="SELL",
            qty=1.0,
            price=40100.0,
            timestamp=2000,
            received_time=utc_now().timestamp(),
            venue="BINANCE_SPOT",
        ))
        trade.calc_pnl()

        eligible, reasons = checker.check_trade_eligible(trade)
        assert not eligible
        assert "non_futures_execution" in reasons

    def test_negative_pnl_rejection(self, checker):
        """Test that losing trades are rejected."""
        trade = TradeAccounting(
            trade_id="trade_loss",
            symbol="BTCUSDT",
            entry_side="BUY",
        )

        entry_fill = FillRecord(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            price=40000.0,
            timestamp=1000,
            received_time=utc_now().timestamp(),
            venue="BINANCE_USDM_FUTURES",
        )

        exit_fill = FillRecord(
            symbol="BTCUSDT",
            side="SELL",
            qty=1.0,
            price=39500.0,  # Loss
            timestamp=2000,
            received_time=utc_now().timestamp(),
            venue="BINANCE_USDM_FUTURES",
        )

        trade.set_entry_fill(entry_fill)
        trade.set_exit_fill(exit_fill)
        trade.calc_pnl()

        eligible, reasons = checker.check_trade_eligible(trade)
        assert not eligible
        assert "negative_pnl" in reasons


class TestV5Learner:
    """Tests for main learner."""

    @pytest.fixture
    def learner(self):
        """Create learner instance."""
        return V5Learner()

    @pytest.fixture
    def eligible_trade(self):
        """Create eligible trade."""
        trade = TradeAccounting(
            trade_id="trade_learn_1",
            symbol="BTCUSDT",
            entry_side="BUY",
        )

        entry_fill = FillRecord(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            price=40000.0,
            timestamp=1000,
            received_time=utc_now().timestamp(),
            venue="BINANCE_USDM_FUTURES",
        )

        exit_fill = FillRecord(
            symbol="BTCUSDT",
            side="SELL",
            qty=1.0,
            price=40100.0,
            timestamp=2000,
            received_time=utc_now().timestamp(),
            venue="BINANCE_USDM_FUTURES",
        )

        trade.set_entry_fill(entry_fill)
        trade.set_exit_fill(exit_fill)
        trade.calc_pnl()

        return trade

    def test_process_eligible_trade(self, learner, eligible_trade):
        """Test processing eligible trade."""
        was_eligible, reason = learner.process_closed_trade(
            eligible_trade,
            segment_id="momentum_up_1",
            strategy_id="baseline_momentum_01",
            regime="trending_up_normal_vol",
        )

        assert was_eligible
        assert reason == "eligible"
        assert eligible_trade.trade_id not in [t[0] for t in learner.rejected_trades]

    def test_get_segment_state(self, learner, eligible_trade):
        """Test retrieving segment state."""
        learner.process_closed_trade(
            eligible_trade,
            segment_id="momentum_up_1",
            strategy_id="baseline_momentum_01",
            regime="trending_up_normal_vol",
        )

        state = learner.get_segment_state("momentum_up_1")
        assert state is not None
        assert state["segment_id"] == "momentum_up_1"
        assert state["total_closes"] == 1

    def test_get_strategy_performance(self, learner, eligible_trade):
        """Test aggregated strategy performance."""
        learner.process_closed_trade(
            eligible_trade,
            segment_id="momentum_up_1",
            strategy_id="baseline_momentum_01",
            regime="trending_up_normal_vol",
        )

        perf = learner.get_strategy_performance("baseline_momentum_01")
        assert perf["strategy_id"] == "baseline_momentum_01"
        assert perf["total_closes"] == 1
        assert perf["total_wins"] >= 0


class TestReadinessEvaluator:
    """Tests for REAL readiness state machine."""

    @pytest.fixture
    def evaluator(self):
        """Create readiness evaluator."""
        return ReadinessEvaluator()

    def test_initializing_state(self, evaluator):
        """Test initialization state (no data)."""
        report = evaluator.evaluate(
            eligible_closes=0,
            days_of_data=0,
            expectancy_bps=0.0,
            profit_factor=1.0,
            drawdown_pct=0.0,
            accounting_complete=False,
        )

        assert report.state == ReadinessState.NOT_READY_INITIALIZING

    def test_insufficient_data_state(self, evaluator):
        """Test insufficient data state."""
        report = evaluator.evaluate(
            eligible_closes=50,  # < 300
            days_of_data=2,  # < 7
            expectancy_bps=10.0,
            profit_factor=1.2,
            drawdown_pct=2.0,
            accounting_complete=True,
        )

        assert report.state == ReadinessState.NOT_READY_INSUFFICIENT_DATA

    def test_negative_expectancy_state(self, evaluator):
        """Test negative expectancy state."""
        report = evaluator.evaluate(
            eligible_closes=300,
            days_of_data=7,
            expectancy_bps=-5.0,  # Negative
            profit_factor=1.2,
            drawdown_pct=2.0,
            accounting_complete=True,
        )

        assert report.state == ReadinessState.NOT_READY_NEGATIVE_EXPECTANCY

    def test_low_profit_factor_state(self, evaluator):
        """Test low profit factor state."""
        report = evaluator.evaluate(
            eligible_closes=300,
            days_of_data=7,
            expectancy_bps=10.0,
            profit_factor=1.0,  # < 1.20
            drawdown_pct=2.0,
            accounting_complete=True,
        )

        assert report.state == ReadinessState.NOT_READY_LOW_PROFIT_FACTOR

    def test_drawdown_exceeded_state(self, evaluator):
        """Test exceeded drawdown state."""
        report = evaluator.evaluate(
            eligible_closes=300,
            days_of_data=7,
            expectancy_bps=10.0,
            profit_factor=1.2,
            drawdown_pct=10.0,  # > 5.0%
            accounting_complete=True,
        )

        assert report.state == ReadinessState.NOT_READY_DRAWDOWN_EXCEEDED

    def test_all_gates_passed(self, evaluator):
        """Test when all gates are passed."""
        report = evaluator.evaluate(
            eligible_closes=300,
            days_of_data=7,
            expectancy_bps=15.0,
            profit_factor=1.5,
            drawdown_pct=2.0,
            accounting_complete=True,
            incidents=0,
        )

        # Should reach REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED
        assert report.state == ReadinessState.REAL_REVIEW_READY_OPERATOR_APPROVAL_REQUIRED
        assert not report.real_orders_allowed  # Still false
        assert report.paper_only  # Still true

    def test_czech_messages(self, evaluator):
        """Test Czech status messages are present."""
        report = evaluator.evaluate(
            eligible_closes=50,
            days_of_data=2,
            expectancy_bps=10.0,
            profit_factor=1.2,
            drawdown_pct=2.0,
            accounting_complete=True,
        )

        assert report.state_label_cs is not None
        assert len(report.state_label_cs) > 0
        assert "Nedostatek" in report.state_label_cs or "Inicializace" in report.state_label_cs

    def test_report_to_dict(self, evaluator):
        """Test exporting report as dict."""
        report = evaluator.evaluate(
            eligible_closes=300,
            days_of_data=7,
            expectancy_bps=15.0,
            profit_factor=1.5,
            drawdown_pct=2.0,
            accounting_complete=True,
            incidents=0,
        )

        d = report.to_dict()
        assert "state" in d
        assert "state_label_cs" in d
        assert "expectancy_bps" in d
        assert "profit_factor" in d


class TestSegmentStats:
    """Tests for segment performance tracking."""

    def test_segment_creation(self):
        """Test creating segment stats."""
        segment = SegmentStats(
            segment_id="test_seg_1",
            strategy_id="baseline_momentum_01",
            regime="trending_up",
        )

        assert segment.total_closes == 0
        assert segment.win_rate() is None

    def test_add_winning_trade(self):
        """Test adding winning trade to segment."""
        segment = SegmentStats(
            segment_id="test_seg_1",
            strategy_id="baseline_momentum_01",
            regime="trending_up",
        )

        trade = TradeAccounting(
            trade_id="trade_win",
            symbol="BTCUSDT",
            entry_side="BUY",
        )

        entry_fill = FillRecord(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            price=40000.0,
            timestamp=1000,
            received_time=utc_now().timestamp(),
        )

        exit_fill = FillRecord(
            symbol="BTCUSDT",
            side="SELL",
            qty=1.0,
            price=40100.0,
            timestamp=2000,
            received_time=utc_now().timestamp(),
        )

        trade.set_entry_fill(entry_fill)
        trade.set_exit_fill(exit_fill)
        trade.calc_pnl()

        segment.add_trade(trade)

        assert segment.total_closes == 1
        assert segment.wins == 1
        assert segment.win_rate() == 1.0
