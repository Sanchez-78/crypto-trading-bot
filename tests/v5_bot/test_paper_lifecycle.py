"""Tests for V5 PAPER trading lifecycle."""

import pytest
from datetime import datetime
from src.v5_bot.market.local_book import LocalBookManager
from src.v5_bot.paper.paper_broker import PaperBroker, PaperPosition
from src.v5_bot.paper.exits import ExitEvaluator, ExitReason, ExitConfig
from src.v5_bot.util.datetime_utils import utc_now


class TestPaperBroker:
    """Tests for PAPER trading broker."""

    @pytest.fixture
    def broker(self):
        """Create broker with book manager."""
        book_mgr = LocalBookManager()
        # Pre-populate with data
        now = utc_now().timestamp()
        book_mgr.update_book(
            symbol="BTCUSDT",
            bid=40000.0,
            bid_qty=1.0,
            ask=40010.0,
            ask_qty=1.0,
            transaction_time=int(now * 1000),
            received_time=now,
        )
        book_mgr.update_book(
            symbol="ETHUSDT",
            bid=2500.0,
            bid_qty=10.0,
            ask=2510.0,
            ask_qty=10.0,
            transaction_time=int(now * 1000),
            received_time=now,
        )
        return PaperBroker(book_mgr)

    def test_successful_entry(self, broker):
        """Test successful entry execution."""
        trade_id, reason = broker.request_entry(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            expected_price=40005.0,
            tp_pct=1.0,
            sl_pct=0.5,
        )

        assert trade_id is not None
        assert reason is None
        assert trade_id in broker.open_positions

        position = broker.open_positions[trade_id]
        assert position.symbol == "BTCUSDT"
        assert position.side == "BUY"
        assert position.qty == 1.0

    def test_entry_excessive_slippage(self, broker):
        """Test entry rejection due to slippage."""
        trade_id, reason = broker.request_entry(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            expected_price=40000.0,  # Ask is 40010, 0.025% slippage
            tp_pct=1.0,
            sl_pct=0.5,
        )

        # Should accept (0.025% < 1%)
        assert trade_id is not None

        # Try with extreme slippage
        trade_id2, reason2 = broker.request_entry(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            expected_price=35000.0,  # Way off
            tp_pct=1.0,
            sl_pct=0.5,
        )

        assert trade_id2 is None
        assert "slippage" in reason2

    def test_entry_no_liquidity(self, broker):
        """Test entry when symbol has no liquidity."""
        trade_id, reason = broker.request_entry(
            symbol="FAKEUDT",
            side="BUY",
            qty=1.0,
            expected_price=100.0,
            tp_pct=1.0,
            sl_pct=0.5,
        )

        assert trade_id is None
        assert "no_liquidity" in reason

    def test_check_exit_target_hit(self, broker):
        """Test exit when target profit hit."""
        # First, enter
        trade_id, _ = broker.request_entry(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            expected_price=40005.0,
            tp_pct=1.0,
            sl_pct=0.5,
        )

        position = broker.open_positions[trade_id]
        # Entry at 40010, TP at 40010 * 1.01 = 40410.1

        # Price at TP
        current_time = utc_now().timestamp()
        exit_info, reason = broker.check_and_exit_position(
            trade_id, position.target_price, current_time
        )

        assert exit_info is not None
        assert reason == "tp_hit"
        assert trade_id not in broker.open_positions  # Position should be closed
        assert trade_id in broker.closed_trades

    def test_check_exit_stop_hit(self, broker):
        """Test exit when stop loss hit."""
        trade_id, _ = broker.request_entry(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            expected_price=40005.0,
            tp_pct=1.0,
            sl_pct=0.5,
        )

        position = broker.open_positions[trade_id]

        # Price at SL
        current_time = utc_now().timestamp()
        exit_info, reason = broker.check_and_exit_position(
            trade_id, position.stop_loss_price, current_time
        )

        assert exit_info is not None
        assert reason == "sl_hit"
        assert trade_id not in broker.open_positions

    def test_short_position(self, broker):
        """Test SELL/short entry and exit."""
        trade_id, _ = broker.request_entry(
            symbol="ETHUSDT",
            side="SELL",
            qty=10.0,
            expected_price=2505.0,
            tp_pct=1.0,
            sl_pct=0.5,
        )

        assert trade_id is not None
        position = broker.open_positions[trade_id]
        assert position.side == "SELL"

        # For short: TP is lower, SL is higher
        # Entry at 2500, TP at 2500 * 0.99 = 2475
        current_time = utc_now().timestamp()
        exit_info, reason = broker.check_and_exit_position(
            trade_id, position.target_price, current_time
        )

        assert exit_info is not None
        assert reason == "tp_hit"

    def test_position_timeout(self, broker):
        """Test exit due to timeout."""
        trade_id, _ = broker.request_entry(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            expected_price=40005.0,
            tp_pct=1.0,
            sl_pct=0.5,
        )

        position = broker.open_positions[trade_id]

        # Simulate 9 hours later
        current_time = position.entry_time + 32400  # 9 hours
        exit_info, reason = broker.check_and_exit_position(
            trade_id, 40500.0, current_time
        )

        assert exit_info is not None
        assert reason == "timeout"

    def test_get_daily_stats(self, broker):
        """Test daily statistics calculation with explicit manual closes."""
        # Create several trades and manually close them
        for i in range(3):
            trade_id, _ = broker.request_entry(
                symbol="BTCUSDT",
                side="BUY",
                qty=1.0,
                expected_price=40005.0,
                tp_pct=1.0,
                sl_pct=0.5,
            )

            current_time = utc_now().timestamp()
            # Explicitly use manual_close for test setup (not normal price evaluation)
            broker.manual_close_position(
                trade_id, 40100.0 + i * 50, current_time
            )

        stats = broker.get_daily_stats()
        assert stats["trades_closed"] == 3
        assert stats["total_net_pnl_usd"] > 0


class TestExitEvaluator:
    """Tests for exit decision logic."""

    def test_check_exit_target(self):
        """Test exit on target profit."""
        evaluator = ExitEvaluator()

        # BUY at 100, TP at 101.5 (1.5%)
        should_exit, reason = evaluator.check_exit(
            current_price=101.5,
            entry_price=100.0,
            side="BUY",
            hold_seconds=60,
        )

        assert should_exit
        assert reason == ExitReason.TARGET_PROFIT

    def test_check_exit_stop_loss(self):
        """Test exit on stop loss."""
        evaluator = ExitEvaluator()

        # BUY at 100, SL at 99 (1%)
        should_exit, reason = evaluator.check_exit(
            current_price=99.0,
            entry_price=100.0,
            side="BUY",
            hold_seconds=60,
        )

        assert should_exit
        assert reason == ExitReason.STOP_LOSS

    def test_check_exit_timeout(self):
        """Test exit on timeout."""
        config = ExitConfig(max_hold_seconds=3600)
        evaluator = ExitEvaluator(config)

        # Held for 2 hours (exceeds 1 hour limit)
        should_exit, reason = evaluator.check_exit(
            current_price=100.5,
            entry_price=100.0,
            side="BUY",
            hold_seconds=7200,
        )

        assert should_exit
        assert reason == ExitReason.TIMEOUT

    def test_no_exit_condition(self):
        """Test when no exit condition is met."""
        evaluator = ExitEvaluator()

        should_exit, reason = evaluator.check_exit(
            current_price=100.5,
            entry_price=100.0,
            side="BUY",
            hold_seconds=60,
        )

        assert not should_exit
        assert reason is None

    def test_calc_potential_pnl(self):
        """Test PnL calculation."""
        evaluator = ExitEvaluator()

        # BUY 1.0 at 100, current 105
        pnl = evaluator.calc_potential_pnl(
            entry_price=100.0,
            current_price=105.0,
            side="BUY",
            qty=1.0,
        )
        assert pnl == 5.0

        # SELL 1.0 at 100, current 95
        pnl = evaluator.calc_potential_pnl(
            entry_price=100.0,
            current_price=95.0,
            side="SELL",
            qty=1.0,
        )
        assert pnl == 5.0

    def test_mfe_mae(self):
        """Test maximum favorable/adverse excursion."""
        evaluator = ExitEvaluator()

        # BUY at 100, high 110, low 95
        mfe = evaluator.calc_max_favorable_excursion(100.0, 110.0, "BUY")
        mae = evaluator.calc_max_adverse_excursion(100.0, 95.0, "BUY")

        assert mfe == 10.0
        assert mae == 5.0

    def test_short_mfe_mae(self):
        """Test MFE/MAE for short positions."""
        evaluator = ExitEvaluator()

        # SELL at 100, high 105, low 90
        mfe = evaluator.calc_max_favorable_excursion(100.0, 90.0, "SELL")
        mae = evaluator.calc_max_adverse_excursion(100.0, 105.0, "SELL")

        assert mfe == 10.0
        assert mae == 5.0

    def test_update_config(self):
        """Test updating exit config."""
        evaluator = ExitEvaluator()
        assert evaluator.config.tp_pct == 1.5

        evaluator.update_config(tp_pct=2.0, sl_pct=1.5)
        assert evaluator.config.tp_pct == 2.0
        assert evaluator.config.sl_pct == 1.5
