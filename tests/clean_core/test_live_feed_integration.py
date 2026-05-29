"""Tests for Binance USDⓈ-M live feed integration and recorded feed mocking."""

import pytest
import time
from src.clean_core.runner.binance_usdm_public_feed import BinanceUsdmPublicFeed
from src.clean_core.runner.recorded_futures_feed import RecordedBinanceFeed
from src.clean_core.runner.forward_paper_runner import ForwardPaperRunner


class TestRecordedBinanceFeed:
    """Test recorded feed for realistic Binance data replay."""

    def test_27_recorded_feed_initialization(self):
        """Test 27: RecordedBinanceFeed initializes with snapshot."""
        depth = [
            {"timestamp": 1000, "bid": 50000.0, "ask": 50001.0},
            {"timestamp": 2000, "bid": 50010.0, "ask": 50011.0},
        ]
        trades = [
            {"price": 50005.0, "qty": 1.0, "side": "buy"},
            {"price": 50015.0, "qty": 2.0, "side": "sell"},
        ]

        feed = RecordedBinanceFeed(depth, trades)
        feed.initialize("BTCUSDT")

        snapshot = feed.get_snapshot()
        assert snapshot is not None
        assert snapshot.symbol == "BTCUSDT"
        assert snapshot.bid == 50000.0
        assert snapshot.ask == 50001.0

    def test_28_recorded_feed_trade_sequence(self):
        """Test 28: RecordedBinanceFeed replays trades in order."""
        depth = [
            {"timestamp": 1000, "bid": 50000.0, "ask": 50001.0},
            {"timestamp": 2000, "bid": 50010.0, "ask": 50011.0},
            {"timestamp": 3000, "bid": 50020.0, "ask": 50021.0},
        ]
        trades = [
            {"price": 50005.0, "qty": 1.0, "side": "buy"},
            {"price": 50015.0, "qty": 2.0, "side": "sell"},
            {"price": 50025.0, "qty": 0.5, "side": "buy"},
        ]

        feed = RecordedBinanceFeed(depth, trades)
        feed.initialize("BTCUSDT")

        prices = []
        while True:
            trade = feed.get_next_trade()
            if not trade:
                break
            prices.append(trade.price)

        assert len(prices) == 3
        assert prices == [50005.0, 50015.0, 50025.0]

    def test_29_recorded_feed_with_runner(self, temp_dir):
        """Test 29: RecordedBinanceFeed works with ForwardPaperRunner."""
        depth = [
            {"timestamp": 1000, "bid": 50000.0, "ask": 50000.5},
            {"timestamp": 2000, "bid": 50030.0, "ask": 50030.5},
            {"timestamp": 3000, "bid": 50060.0, "ask": 50060.5},
        ]
        trades = [
            {"price": 50050.0, "qty": 1.0, "side": "buy"},
            {"price": 50550.0, "qty": 1.0, "side": "sell"},
        ]

        feed = RecordedBinanceFeed(depth, trades)
        runner = ForwardPaperRunner(
            feed=feed,
            symbol="BTCUSDT",
            output_dir=temp_dir,
        )

        report = runner.run()

        # Should produce valid outcome with recorded data
        assert report["symbol"] == "BTCUSDT"
        assert report["status"] == "complete"


class TestBinanceUsdmPublicFeedStructure:
    """Test BinanceUsdmPublicFeed structure (without live connection)."""

    def test_30_binance_feed_initialization_structure(self):
        """Test 30: BinanceUsdmPublicFeed initializes with correct structure."""
        feed = BinanceUsdmPublicFeed(
            base_url="wss://fstream.binance.com/ws",
            timeout_seconds=30,
            max_reconnect_attempts=5,
        )

        assert feed.base_url == "wss://fstream.binance.com/ws"
        assert feed.timeout_seconds == 30
        assert feed.max_reconnect_attempts == 5
        assert feed.symbol is None
        assert not feed.connected
        assert not feed.running

    def test_31_binance_feed_no_spot_endpoints(self):
        """Test 31: BinanceUsdmPublicFeed only uses USDⓈ-M Futures endpoints."""
        feed = BinanceUsdmPublicFeed()

        # Verify base URL is Futures, not Spot
        assert "fstream" in feed.base_url  # Futures endpoint
        assert "stream.binance.com" in feed.base_url
        # Spot would use "stream.binance.com:9443/ws"
        assert "9443" not in feed.base_url

    def test_32_binance_feed_uses_public_streams_only(self):
        """Test 32: BinanceUsdmPublicFeed constructs only public stream names."""
        feed = BinanceUsdmPublicFeed()
        feed.symbol = "btcusdt"

        # Verify no user-data or private stream naming patterns
        public_streams = ["bookTicker", "aggTrade", "markPrice", "depth"]

        # The feed should construct streams like:
        # - btcusdt@bookTicker (public)
        # - btcusdt@aggTrade (public)
        # NOT:
        # - btcusdt@userData (private)
        # - btcusdt@executionReport (private)

        # Check that the class doesn't have userData or other private patterns
        source = str(feed.__class__.__dict__.keys())
        assert "userData" not in source
        assert "executionReport" not in source
        assert "order" not in source.lower()

    def test_33_binance_feed_queue_based_trade_handling(self):
        """Test 33: BinanceUsdmPublicFeed uses queue for thread-safe trade delivery."""
        feed = BinanceUsdmPublicFeed()

        # Verify it has a trade queue (not a simple list)
        from queue import Queue
        assert isinstance(feed.trade_queue, Queue)

    def test_34_binance_feed_error_handling_attributes(self):
        """Test 34: BinanceUsdmPublicFeed has timeout and reconnect handling."""
        feed = BinanceUsdmPublicFeed(timeout_seconds=15, max_reconnect_attempts=3)

        assert feed.timeout_seconds == 15
        assert feed.max_reconnect_attempts == 3
        assert hasattr(feed, "running")
        assert hasattr(feed, "connected")
        assert hasattr(feed, "depth_thread")
        assert hasattr(feed, "trade_thread")

    def test_35_binance_feed_graceful_close(self):
        """Test 35: BinanceUsdmPublicFeed has graceful close mechanism."""
        feed = BinanceUsdmPublicFeed()

        # Should be callable without error
        feed.close()

        # Should be idempotent
        feed.close()
