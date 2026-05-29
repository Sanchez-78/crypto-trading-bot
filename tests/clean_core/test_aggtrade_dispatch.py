"""Regression test: aggTrade event dispatch to runner."""

import pytest
from src.clean_core.runner.forward_paper_runner import ForwardPaperRunner
from src.clean_core.runner.public_futures_feed import PublicFuturesFeed, MarketSnapshot, Trade
from datetime import datetime, timezone
import tempfile
from pathlib import Path


class MockLiveAggTradeFeed(PublicFuturesFeed):
    """Mock feed that simulates live aggTrade stream with delayed first event."""

    def __init__(self, delay_first_event_sec=1.0):
        self.delay_first_event_sec = delay_first_event_sec
        self.symbol = None
        self.current_depth = None
        self.trades = []
        self.trade_index = 0
        self.initialized = False
        import time
        self.start_time = time.monotonic()

    def initialize(self, symbol: str) -> None:
        self.symbol = symbol.lower()
        self.initialized = True
        # Initial depth snapshot
        self.current_depth = {
            "symbol": self.symbol.upper(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "price": 50000.0,
            "bid": 49999.5,
            "ask": 50000.5,
        }

        # Simulated delayed aggTrade stream
        self.trades = [
            Trade(
                symbol=self.symbol.upper(),
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                price=50050.0,
                qty=0.5,
                side="buy",
            ),
            Trade(
                symbol=self.symbol.upper(),
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                price=50100.0,
                qty=0.25,
                side="sell",
            ),
            Trade(
                symbol=self.symbol.upper(),
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                price=50150.0,
                qty=1.0,
                side="buy",
            ),
        ]

    def get_snapshot(self) -> MarketSnapshot:
        if not self.current_depth:
            return None
        return MarketSnapshot(
            symbol=self.current_depth["symbol"],
            timestamp_utc=self.current_depth["timestamp_utc"],
            price=self.current_depth["price"],
            bid=self.current_depth["bid"],
            ask=self.current_depth["ask"],
        )

    def get_next_trade(self, timeout_seconds: float = 0.5) -> Trade | None:
        """Return trades with delay to simulate live stream."""
        import time

        # Check if enough time has passed for first event
        elapsed = time.monotonic() - self.start_time
        if elapsed < self.delay_first_event_sec:
            return None

        if self.trade_index < len(self.trades):
            trade = self.trades[self.trade_index]
            self.trade_index += 1
            return trade

        return None

    def close(self) -> None:
        pass


class TestAggTradeDispatch:
    """Test that aggTrade events are properly dispatched through runner."""

    def test_aggtrade_events_counted_in_bounded_session(self):
        """Verify aggTrade events increment counter in bounded live session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feed = MockLiveAggTradeFeed(delay_first_event_sec=0.1)
            runner = ForwardPaperRunner(
                feed=feed,
                symbol="BTCUSDT",
                output_dir=tmpdir,
                duration_seconds=5,  # 5 second bounded session
            )

            report = runner.run()

            # Verify event tracking
            assert report["live_session_metadata"]["agg_trade_events"] > 0, \
                "aggTrade events should be counted in bounded session"
            assert report["live_session_metadata"]["book_ticker_events"] > 0, \
                "bookTicker events should be counted"
            assert report["live_session_metadata"]["first_agg_trade_at"] is not None, \
                "first_agg_trade_at should be set when events received"

    def test_both_event_types_required_for_strategy(self):
        """Verify strategy evaluation waits for both event types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feed = MockLiveAggTradeFeed(delay_first_event_sec=0.05)
            runner = ForwardPaperRunner(
                feed=feed,
                symbol="BTCUSDT",
                output_dir=tmpdir,
                duration_seconds=3,
            )

            report = runner.run()

            # If both events present, strategy was evaluated
            book_ticker_count = report["live_session_metadata"]["book_ticker_events"]
            agg_trade_count = report["live_session_metadata"]["agg_trade_events"]

            if book_ticker_count > 0 and agg_trade_count > 0:
                # Strategy should have had a chance to run
                # (may or may not have generated a trade depending on signal)
                assert report["status"] == "complete"
            else:
                # Strategy should NOT have run if missing event type
                assert report["closed_trades_count"] == 0

    def test_delayed_aggtrade_event_still_received(self):
        """Verify session doesn't end before delayed aggTrade event arrives."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First event delayed 0.5s, but session runs for 5s
            feed = MockLiveAggTradeFeed(delay_first_event_sec=0.5)
            runner = ForwardPaperRunner(
                feed=feed,
                symbol="BTCUSDT",
                output_dir=tmpdir,
                duration_seconds=5,
            )

            report = runner.run()

            # Session should wait past the 0.5s delay and receive events
            assert report["live_session_metadata"]["agg_trade_events"] > 0, \
                "Delayed aggTrade events should be received within bounded session"

    def test_runner_does_not_exit_on_empty_queue(self):
        """Verify empty queue poll doesn't prematurely end bounded session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Feed that occasionally has no trades
            feed = MockLiveAggTradeFeed(delay_first_event_sec=2.0)
            runner = ForwardPaperRunner(
                feed=feed,
                symbol="BTCUSDT",
                output_dir=tmpdir,
                duration_seconds=3,  # Longer than delay
            )

            report = runner.run()

            # Session should run for full duration (3s)
            # and eventually receive delayed events
            assert report["status"] == "complete"
