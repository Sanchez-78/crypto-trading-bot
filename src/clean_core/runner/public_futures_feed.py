"""Protocol for Futures public feed sources (live or simulated)."""

from typing import Protocol, Optional
from dataclasses import dataclass


@dataclass
class MarketSnapshot:
    """Snapshot of market state at a single timestamp."""
    symbol: str
    timestamp_utc: str
    price: float
    bid: float
    ask: float


@dataclass
class Trade:
    """Single market trade event."""
    symbol: str
    timestamp_utc: str
    price: float
    qty: float
    side: str  # "buy" or "sell"


class PublicFuturesFeed(Protocol):
    """
    Protocol for consuming Binance USDⓈ-M Futures public market data.

    Implementations may be deterministic (SimulatedFuturesFeed) or live (BinanceUsdmPublicFeed).
    """

    def initialize(self, symbol: str) -> None:
        """Initialize feed for a given symbol."""
        ...

    def get_snapshot(self) -> Optional[MarketSnapshot]:
        """Get current market snapshot, or None if not available."""
        ...

    def get_next_trade(self) -> Optional[Trade]:
        """Get next trade from feed, or None if no more data/live timeout."""
        ...

    def close(self) -> None:
        """Close feed resources."""
        ...
