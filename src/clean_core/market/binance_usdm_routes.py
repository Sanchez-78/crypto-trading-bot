"""Binance USDⓈ-M Futures market data routes for Clean Core RESET R1."""

from typing import Optional
from src.clean_core.domain import ExecutionTruthClass, MarketSourceIdentity
from src.clean_core.config import BINANCE_USDM_WS_BASE


class BinanceUsdmRoutes:
    """
    Encapsulates route generation for Binance USDⓈ-M Futures WebSocket streams.

    All streams use fstream.binance.com (Futures only, no Spot).
    """

    def __init__(self):
        self.base_url = BINANCE_USDM_WS_BASE
        self.route_version = "R1"

    def depth_stream(
        self, symbol: str, update_speed_ms: int = 100
    ) -> tuple[str, MarketSourceIdentity]:
        """
        Generate route for order book depth updates (100ms or 250ms).

        Args:
            symbol: e.g., "BTCUSDT"
            update_speed_ms: 100 (default) or 250

        Returns:
            (url_path, MarketSourceIdentity)
        """
        if update_speed_ms not in (100, 250):
            raise ValueError(f"update_speed_ms must be 100 or 250, got {update_speed_ms}")

        stream_name = f"{symbol.lower()}@depth@{update_speed_ms}ms"
        url_path = f"{self.base_url}/ws/{stream_name}"

        identity = MarketSourceIdentity(
            venue="binance_usdm",
            instrument=symbol.upper(),
            price_source="public_book",
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            rpi_visibility=False,
            route_version=self.route_version,
        )

        return url_path, identity

    def book_ticker_stream(self, symbol: str) -> tuple[str, MarketSourceIdentity]:
        """
        Generate route for best bid/ask (bookTicker, real-time).

        Args:
            symbol: e.g., "BTCUSDT"

        Returns:
            (url_path, MarketSourceIdentity)
        """
        stream_name = f"{symbol.lower()}@bookTicker"
        url_path = f"{self.base_url}/ws/{stream_name}"

        identity = MarketSourceIdentity(
            venue="binance_usdm",
            instrument=symbol.upper(),
            price_source="public_book",
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            rpi_visibility=False,
            route_version=self.route_version,
        )

        return url_path, identity

    def mark_price_stream(
        self, symbol: str, update_speed_ms: int = 1000
    ) -> tuple[str, MarketSourceIdentity]:
        """
        Generate route for mark price and funding rate (markPrice@1s or @3s).

        Used for funding rate tracking (telemetry only), not execution fill basis.

        Args:
            symbol: e.g., "BTCUSDT"
            update_speed_ms: 1000 (default) or 3000

        Returns:
            (url_path, MarketSourceIdentity)
        """
        if update_speed_ms not in (1000, 3000):
            raise ValueError(f"update_speed_ms must be 1000 or 3000, got {update_speed_ms}")

        stream_name = f"{symbol.lower()}@markPrice@{update_speed_ms}ms"
        url_path = f"{self.base_url}/ws/{stream_name}"

        identity = MarketSourceIdentity(
            venue="binance_usdm",
            instrument=symbol.upper(),
            price_source="public_book",
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            rpi_visibility=False,
            route_version=self.route_version,
        )

        return url_path, identity

    def agg_trade_stream(self, symbol: str) -> tuple[str, MarketSourceIdentity]:
        """
        Generate route for aggregated trades (aggTrade, real-time).

        Args:
            symbol: e.g., "BTCUSDT"

        Returns:
            (url_path, MarketSourceIdentity)
        """
        stream_name = f"{symbol.lower()}@aggTrade"
        url_path = f"{self.base_url}/ws/{stream_name}"

        identity = MarketSourceIdentity(
            venue="binance_usdm",
            instrument=symbol.upper(),
            price_source="public_book",
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            rpi_visibility=False,
            route_version=self.route_version,
        )

        return url_path, identity
