"""Recorded/mocked Binance Futures feed for testing live feed behavior."""

from typing import List, Dict, Any, Optional
import time
from .public_futures_feed import PublicFuturesFeed, MarketSnapshot, Trade


class RecordedBinanceFeed:
    """
    Mocked feed that replays Binance-like bookTicker and aggTrade events.

    Used for testing live feed parser without connecting to real WebSocket.
    """

    def __init__(self, depth_snapshots: List[Dict[str, Any]], trades: List[Dict[str, Any]]):
        """
        Args:
            depth_snapshots: List of {"timestamp": ms, "bid": price, "ask": price} dicts
            trades: List of {"timestamp": ms, "price": float, "qty": float, "side": "buy"/"sell"} dicts
        """
        self.depth_snapshots = depth_snapshots
        self.trades = trades
        self.symbol = None
        self.depth_index = 0
        self.trade_index = 0
        self.current_depth = None

    def initialize(self, symbol: str) -> None:
        """Initialize feed for symbol."""
        self.symbol = symbol
        self.depth_index = 0
        self.trade_index = 0
        if self.depth_snapshots:
            self.current_depth = self.depth_snapshots[0].copy()

    def get_snapshot(self) -> Optional[MarketSnapshot]:
        """Return current depth snapshot."""
        if not self.symbol or not self.current_depth:
            return None
        return MarketSnapshot(
            symbol=self.symbol,
            timestamp_utc=f"2026-05-26T12:{int(self.depth_index):02d}:00Z",
            price=(self.current_depth.get("bid", 0) + self.current_depth.get("ask", 0)) / 2,
            bid=self.current_depth.get("bid", 0),
            ask=self.current_depth.get("ask", 0),
        )

    def get_next_trade(self) -> Optional[Trade]:
        """Get next trade from recorded sequence."""
        if self.trade_index >= len(self.trades):
            return None

        trade_data = self.trades[self.trade_index]
        self.trade_index += 1

        # Also update depth snapshots in chronological order
        if self.depth_index < len(self.depth_snapshots) - 1:
            self.depth_index += 1
            self.current_depth = self.depth_snapshots[self.depth_index].copy()

        return Trade(
            symbol=self.symbol,
            timestamp_utc=f"2026-05-26T12:{int(self.trade_index):02d}:00Z",
            price=trade_data.get("price", 0),
            qty=trade_data.get("qty", 1.0),
            side=trade_data.get("side", "buy"),
        )

    def close(self) -> None:
        """No-op for recorded feed."""
        pass
