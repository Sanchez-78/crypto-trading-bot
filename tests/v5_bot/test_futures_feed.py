"""Integration tests for Binance USDⓈ-M Futures feed and accounting."""

import pytest
from datetime import datetime
from src.v5_bot.market.binance_usdm_feed import BinanceUSDMFeed, BookTickerUpdate, AggTradeUpdate
from src.v5_bot.market.local_book import LocalBookManager
from src.v5_bot.execution.accounting import TradeAccounting, FillRecord
from src.v5_bot.execution.fees import FeeCalculator
from src.v5_bot.execution.funding import FundingCalculator
from src.v5_bot.util.datetime_utils import utc_now


class TestBookTickerUpdate:
    """Tests for BookTickerUpdate dataclass."""

    def test_midpoint(self):
        """Test midpoint calculation."""
        tick = BookTickerUpdate(
            symbol="BTCUSDT",
            bid=40000.0,
            bid_qty=1.0,
            ask=40010.0,
            ask_qty=1.0,
            transaction_time=1000,
            received_time=utc_now().timestamp(),
        )
        assert tick.midpoint() == 40005.0

    def test_spread_bps(self):
        """Test spread in basis points."""
        tick = BookTickerUpdate(
            symbol="BTCUSDT",
            bid=40000.0,
            bid_qty=1.0,
            ask=40010.0,
            ask_qty=1.0,
            transaction_time=1000,
            received_time=utc_now().timestamp(),
        )
        spread_bps = tick.spread_bps()
        # (40010 - 40000) / 40005 * 10000 = 10 / 40005 * 10000 ≈ 2.5 bps
        assert abs(spread_bps - 2.5) < 0.01

    def test_is_stale(self):
        """Test staleness check."""
        now = utc_now().timestamp()
        tick = BookTickerUpdate(
            symbol="BTCUSDT",
            bid=40000.0,
            bid_qty=1.0,
            ask=40010.0,
            ask_qty=1.0,
            transaction_time=1000,
            received_time=now - 10.0,  # 10 seconds old
        )
        assert tick.is_stale(max_age_s=5.0)
        assert not tick.is_stale(max_age_s=15.0)


class TestAggTradeUpdate:
    """Tests for AggTradeUpdate dataclass."""

    def test_age_calculation(self):
        """Test age calculation."""
        now = utc_now().timestamp()
        trade = AggTradeUpdate(
            symbol="BTCUSDT",
            agg_trade_id=123,
            price=40000.0,
            qty=1.0,
            first_trade_id=100,
            last_trade_id=110,
            timestamp=1000,
            is_buyer_maker=True,
            received_time=now - 2.0,  # 2 seconds old
        )
        age = trade.age_s()
        assert abs(age - 2.0) < 0.1


class TestLocalBookManager:
    """Tests for in-memory order book."""

    def test_update_and_retrieve_book(self):
        """Test updating and retrieving book."""
        mgr = LocalBookManager()
        mgr.update_book(
            symbol="BTCUSDT",
            bid=40000.0,
            bid_qty=1.0,
            ask=40010.0,
            ask_qty=1.0,
            transaction_time=1000,
            received_time=utc_now().timestamp(),
        )

        book = mgr.get_book("BTCUSDT")
        assert book is not None
        assert book.best_bid() == 40000.0
        assert book.best_ask() == 40010.0

    def test_get_price_for_order(self):
        """Test getting market price for order execution."""
        mgr = LocalBookManager()
        mgr.update_book(
            symbol="BTCUSDT",
            bid=40000.0,
            bid_qty=1.0,
            ask=40010.0,
            ask_qty=1.0,
            transaction_time=1000,
            received_time=utc_now().timestamp(),
        )

        # Buy order uses ask price
        buy_price = mgr.get_price_for_order("BTCUSDT", "BUY")
        assert buy_price == 40010.0

        # Sell order uses bid price
        sell_price = mgr.get_price_for_order("BTCUSDT", "SELL")
        assert sell_price == 40000.0

    def test_all_symbols_healthy(self):
        """Test checking health of all symbols."""
        mgr = LocalBookManager()

        # Add books for two symbols
        now = utc_now().timestamp()
        mgr.update_book(
            symbol="BTCUSDT",
            bid=40000.0,
            bid_qty=1.0,
            ask=40010.0,
            ask_qty=1.0,
            transaction_time=1000,
            received_time=now,
        )
        mgr.update_book(
            symbol="ETHUSDT",
            bid=2500.0,
            bid_qty=10.0,
            ask=2505.0,
            ask_qty=10.0,
            transaction_time=1000,
            received_time=now,
        )

        # All symbols healthy
        assert mgr.get_all_symbols_healthy(["BTCUSDT", "ETHUSDT"])

        # Missing symbol not healthy
        assert not mgr.get_all_symbols_healthy(["BTCUSDT", "BNBUSDT"])


class TestFeeCalculator:
    """Tests for fee calculations."""

    def test_entry_fee(self):
        """Test entry fee calculation."""
        calc = FeeCalculator(taker_rate=0.0005)
        fee = calc.calc_entry_fee(notional_usd=10000.0, is_taker=True)
        assert abs(fee - 5.0) < 0.01  # 10000 * 0.0005 = 5

    def test_round_trip_fee_bps(self):
        """Test round-trip fee in basis points."""
        calc = FeeCalculator(taker_rate=0.0005)
        entry = 10000.0  # 10 BTC at 40000
        exit_val = 10000.0
        fee_bps = calc.calc_round_trip_fee_bps(entry, exit_val)
        # Entry fee: 10000 * 0.0005 = 5
        # Exit fee: 10000 * 0.0005 = 5
        # Total: 10, as % of entry: 10/10000 * 10000 = 10 bps
        assert abs(fee_bps - 10.0) < 0.1


class TestFundingCalculator:
    """Tests for funding calculations."""

    def test_funding_cost_8h(self):
        """Test 8-hour funding cost."""
        calc = FundingCalculator(funding_rate_bps=10)  # 10 units of 0.01% = 0.10% = 0.001 decimal
        cost = calc.calc_funding_cost_8h(notional_usd=10000.0, is_long=True)
        # 10000 * (10 / 10000) = 10000 * 0.001 = 10.0
        assert abs(cost - 10.0) < 0.01

    def test_funding_cost_duration(self):
        """Test funding cost for arbitrary duration."""
        calc = FundingCalculator(funding_rate_bps=10)
        cost = calc.calc_funding_cost_for_duration(
            notional_usd=10000.0,
            hold_seconds=28800,  # 8 hours
            is_long=True,
        )
        # Should be same as 8h cost: 10000 * 0.001 = 10.0
        assert abs(cost - 10.0) < 0.01

    def test_short_funding_reversal(self):
        """Test that short positions have reversed funding cost."""
        calc = FundingCalculator(funding_rate_bps=10)
        long_cost = calc.calc_funding_cost_8h(10000.0, is_long=True)
        short_cost = calc.calc_funding_cost_8h(10000.0, is_long=False)
        # Short cost should be negative of long cost (receives instead of pays)
        # long_cost = 10.0, short_cost = -10.0
        assert abs(short_cost - (-long_cost)) < 0.01


class TestTradeAccounting:
    """Tests for complete trade accounting."""

    def test_complete_buy_trade(self):
        """Test full accounting for a buy trade."""
        trade = TradeAccounting(
            trade_id="trade_1",
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

        result = trade.calc_pnl()

        # Gross PnL: (40100 - 40000) * 1 = 100
        assert abs(trade.gross_pnl_usd - 100.0) < 0.01

        # Entry fee: 40000 * 0.0005 = 20
        # Exit fee: 40100 * 0.0005 = 20.05
        # Total fees: ~40
        assert trade.entry_fee_usd > 0
        assert trade.exit_fee_usd > 0

        # Net PnL: gross - fees - funding
        assert trade.net_pnl_usd < trade.gross_pnl_usd

    def test_complete_sell_trade(self):
        """Test accounting for a short/sell trade."""
        trade = TradeAccounting(
            trade_id="trade_2",
            symbol="ETHUSDT",
            entry_side="SELL",
        )

        entry_fill = FillRecord(
            symbol="ETHUSDT",
            side="SELL",
            qty=10.0,
            price=2500.0,
            timestamp=1000,
            received_time=utc_now().timestamp(),
        )
        exit_fill = FillRecord(
            symbol="ETHUSDT",
            side="BUY",
            qty=10.0,
            price=2450.0,
            timestamp=2000,
            received_time=utc_now().timestamp(),
        )

        trade.set_entry_fill(entry_fill)
        trade.set_exit_fill(exit_fill)

        result = trade.calc_pnl()

        # Gross PnL: (2500 - 2450) * 10 = 500
        assert abs(trade.gross_pnl_usd - 500.0) < 0.01

    def test_incomplete_trade_no_calc(self):
        """Test that incomplete trade returns empty result."""
        trade = TradeAccounting(
            trade_id="trade_3",
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
        trade.set_entry_fill(entry_fill)

        # No exit fill yet
        result = trade.calc_pnl()
        assert result == {}
        assert not trade.accounting_valid

    def test_trade_to_dict(self):
        """Test exporting trade as dict."""
        trade = TradeAccounting(
            trade_id="trade_4",
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

        d = trade.to_dict()
        assert d["trade_id"] == "trade_4"
        assert d["symbol"] == "BTCUSDT"
        assert d["is_complete"]
        assert d["accounting_valid"]


class TestFeedIntegration:
    """Integration tests combining feed, book, and accounting."""

    def test_book_ticker_to_fill_workflow(self):
        """Test workflow from bookTicker event to fill and accounting."""
        # Create book manager
        mgr = LocalBookManager()

        # Process bookTicker event
        now = utc_now().timestamp()
        mgr.update_book(
            symbol="BTCUSDT",
            bid=40000.0,
            bid_qty=1.0,
            ask=40010.0,
            ask_qty=1.0,
            transaction_time=int(now * 1000),
            received_time=now,
        )

        # Get fill price for BUY order
        buy_price = mgr.get_price_for_order("BTCUSDT", "BUY")
        assert buy_price == 40010.0

        # Create entry fill at that price
        entry_fill = FillRecord(
            symbol="BTCUSDT",
            side="BUY",
            qty=1.0,
            price=buy_price,
            timestamp=int(now * 1000),
            received_time=now,
        )

        # Later, process exit
        now_exit = now + 3600  # 1 hour later
        mgr.update_book(
            symbol="BTCUSDT",
            bid=40100.0,
            bid_qty=1.0,
            ask=40110.0,
            ask_qty=1.0,
            transaction_time=int(now_exit * 1000),
            received_time=now_exit,
        )

        sell_price = mgr.get_price_for_order("BTCUSDT", "SELL")
        assert sell_price == 40100.0

        exit_fill = FillRecord(
            symbol="BTCUSDT",
            side="SELL",
            qty=1.0,
            price=sell_price,
            timestamp=int(now_exit * 1000),
            received_time=now_exit,
        )

        # Create accounting record
        trade = TradeAccounting(
            trade_id="feed_integration_test_1",
            symbol="BTCUSDT",
            entry_side="BUY",
        )
        trade.set_entry_fill(entry_fill)
        trade.set_exit_fill(exit_fill)
        trade.calc_pnl()

        # Verify accounting is complete
        assert trade.is_complete
        assert trade.accounting_valid
        # Gross should be positive (bought at 40010, sold at 40100)
        # Note: slippage cost entry 10 bps
        assert trade.gross_pnl_usd > 0
