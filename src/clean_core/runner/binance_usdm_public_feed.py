"""Live Binance USDⓈ-M Futures public feed implementation."""

from typing import Optional
import websocket
import json
import logging
from datetime import datetime, timezone
from .public_futures_feed import PublicFuturesFeed, MarketSnapshot, Trade

logger = logging.getLogger(__name__)


class BinanceUsdmPublicFeed:
    """
    Live WebSocket feed from Binance USDⓈ-M Futures public streams.

    Connects to depth stream and trade stream for market data.
    """

    def __init__(self, base_url: str = "wss://fstream.binance.com/ws"):
        """
        Args:
            base_url: WebSocket base URL (default: Binance USDⓈ-M)
        """
        self.base_url = base_url
        self.symbol = None
        self.depth_ws = None
        self.trade_ws = None
        self.current_depth = None
        self.pending_trades = []

    def initialize(self, symbol: str) -> None:
        """
        Initialize live feed for a symbol.

        Connects to depth and trade streams.
        """
        self.symbol = symbol
        # In MVP, connections would be established here
        # For now, this is a placeholder (live feed requires async event loop)
        logger.info(f"BinanceUsdmPublicFeed initialized for {symbol} (live mode not yet implemented)")

    def get_snapshot(self) -> Optional[MarketSnapshot]:
        """
        Get current best bid/ask as snapshot.

        Returns None if feed not connected.
        """
        if not self.symbol or not self.current_depth:
            return None
        return MarketSnapshot(
            symbol=self.symbol,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            price=(self.current_depth.get("bid", 0) + self.current_depth.get("ask", 0)) / 2,
            bid=self.current_depth.get("bid", 0),
            ask=self.current_depth.get("ask", 0),
        )

    def get_next_trade(self) -> Optional[Trade]:
        """Get next available trade from queue, or None if none pending."""
        if not self.pending_trades:
            return None
        return self.pending_trades.pop(0)

    def close(self) -> None:
        """Close WebSocket connections."""
        if self.depth_ws:
            self.depth_ws.close()
        if self.trade_ws:
            self.trade_ws.close()
        logger.info(f"BinanceUsdmPublicFeed closed for {self.symbol}")
