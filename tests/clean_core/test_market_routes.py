"""Tests for Binance USDⓈ-M market routes (tests 1-4)."""

import pytest
from src.clean_core.market.binance_usdm_routes import BinanceUsdmRoutes
from src.clean_core.domain import ExecutionTruthClass, MarketObservationRole


class TestBinanceUsdmRoutes:
    """Test suite for BinanceUsdmRoutes."""

    def test_1_depth_stream_route_generation(self, routes):
        """Test 1: Generate depth stream route with correct URL and identity."""
        url, identity = routes.depth_stream("BTCUSDT", update_speed_ms=100)

        assert "wss://fstream.binance.com" in url
        assert "btcusdt@depth@100ms" in url
        assert identity.venue == "binance_usdm"
        assert identity.instrument == "BTCUSDT"
        assert identity.price_source == "public_book"
        assert (
            identity.execution_truth_class
            == ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED
        )
        assert identity.rpi_visibility is False

    def test_2_book_ticker_stream_route(self, routes):
        """Test 2: Generate bookTicker stream route."""
        url, identity = routes.book_ticker_stream("ETHUSDT")

        assert "wss://fstream.binance.com" in url
        assert "ethusdt@bookTicker" in url
        assert identity.instrument == "ETHUSDT"
        assert identity.price_source == "public_book"

    def test_3_mark_price_stream_telemetry_only(self, routes):
        """Test 3: Generate markPrice stream (telemetry only, not execution basis)."""
        url, identity = routes.mark_price_stream("BTCUSDT", update_speed_ms=1000)

        assert "btcusdt@markPrice@1000ms" in url
        assert identity.price_source == "mark_telemetry"
        assert identity.execution_truth_class is None  # Telemetry, not execution truth
        assert identity.observation_role == MarketObservationRole.MARK_FUNDING_TELEMETRY
        assert identity.rpi_visibility is False

    def test_4_agg_trade_stream_route(self, routes):
        """Test 4: Generate aggregated trade stream route."""
        url, identity = routes.agg_trade_stream("XRPUSDT")

        assert "xrpusdt@aggTrade" in url
        assert identity.instrument == "XRPUSDT"
        assert identity.price_source == "public_book"
        assert (
            identity.execution_truth_class
            == ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED
        )
