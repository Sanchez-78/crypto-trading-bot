"""Deterministic simulated Futures feed for testing and validation."""

from typing import Optional, List, Dict, Any
from .public_futures_feed import PublicFuturesFeed, MarketSnapshot, Trade


class SimulatedFuturesFeed:
    """
    In-memory simulated feed for deterministic PAPER testing.

    Replays pre-configured snapshot + trades sequence.
    """

    def __init__(self, snapshot_data: Dict[str, Any], trades_data: List[Dict[str, Any]]):
        """
        Args:
            snapshot_data: Initial market snapshot dict with time, price, bid, ask
            trades_data: List of trade dicts with time, price (qty=1 by default)
        """
        self.snapshot_data = snapshot_data
        self.trades_data = trades_data
        self.trade_index = 0
        self.symbol = None

    def initialize(self, symbol: str) -> None:
        """Initialize feed for symbol."""
        self.symbol = symbol
        self.trade_index = 0

    def get_snapshot(self) -> Optional[MarketSnapshot]:
        """Return initial market snapshot."""
        if not self.symbol or not self.snapshot_data:
            return None
        return MarketSnapshot(
            symbol=self.symbol,
            timestamp_utc=self.snapshot_data.get("time"),
            price=self.snapshot_data.get("price"),
            bid=self.snapshot_data.get("bid"),
            ask=self.snapshot_data.get("ask"),
        )

    def get_next_trade(self) -> Optional[Trade]:
        """Return next trade from pre-loaded sequence."""
        if self.trade_index >= len(self.trades_data):
            return None
        trade_data = self.trades_data[self.trade_index]
        self.trade_index += 1
        return Trade(
            symbol=self.symbol,
            timestamp_utc=trade_data.get("time"),
            price=trade_data.get("price"),
            qty=trade_data.get("qty", 1.0),
            side=trade_data.get("side", "buy"),
        )

    def close(self) -> None:
        """No resources to close in simulated feed."""
        pass
