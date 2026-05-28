"""In-memory order book for USDⓈ-M Futures symbols."""

from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple
from datetime import datetime
from ..util.datetime_utils import utc_now


@dataclass
class BookLevel:
    """Single price level in order book."""
    price: float
    qty: float
    timestamp: int  # milliseconds


@dataclass
class LocalBook:
    """In-memory order book snapshot for one symbol."""
    symbol: str
    bids: List[BookLevel] = field(default_factory=list)  # descending price
    asks: List[BookLevel] = field(default_factory=list)  # ascending price
    updated_at: int = 0  # milliseconds from bookTicker
    received_at: float = 0.0  # local epoch seconds

    def best_bid(self) -> Optional[float]:
        """Best (highest) bid price."""
        return self.bids[0].price if self.bids else None

    def best_ask(self) -> Optional[float]:
        """Best (lowest) ask price."""
        return self.asks[0].price if self.asks else None

    def midpoint(self) -> Optional[float]:
        """Midpoint of best bid/ask."""
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2.0

    def spread_bps(self) -> Optional[float]:
        """Spread in basis points."""
        mid = self.midpoint()
        if mid is None or mid == 0:
            return None
        bid = self.best_bid()
        ask = self.best_ask()
        if bid is None or ask is None:
            return None
        return (ask - bid) / mid * 10000

    def is_stale(self, max_age_s: float = 5.0) -> bool:
        """Check if book is older than max_age_s."""
        if self.received_at == 0:
            return True
        age = utc_now().timestamp() - self.received_at
        return age > max_age_s


class LocalBookManager:
    """Manages in-memory order books for all symbols."""

    def __init__(self):
        self.books: Dict[str, LocalBook] = {}

    def update_book(self, symbol: str, bid: float, bid_qty: float, ask: float, ask_qty: float,
                    transaction_time: int, received_time: float) -> None:
        """Update book for symbol from bookTicker event."""
        self.books[symbol] = LocalBook(
            symbol=symbol,
            bids=[BookLevel(price=bid, qty=bid_qty, timestamp=transaction_time)],
            asks=[BookLevel(price=ask, qty=ask_qty, timestamp=transaction_time)],
            updated_at=transaction_time,
            received_at=received_time,
        )

    def get_book(self, symbol: str) -> Optional[LocalBook]:
        """Get current book for symbol."""
        return self.books.get(symbol)

    def get_snapshot(self, symbol: str) -> Optional[Dict]:
        """Get book as dict (for event logging)."""
        book = self.books.get(symbol)
        if not book:
            return None
        return {
            "symbol": book.symbol,
            "bid": book.best_bid(),
            "ask": book.best_ask(),
            "bid_qty": book.bids[0].qty if book.bids else None,
            "ask_qty": book.asks[0].qty if book.asks else None,
            "spread_bps": book.spread_bps(),
            "received_at": book.received_at,
        }

    def get_price_for_order(self, symbol: str, side: str) -> Optional[float]:
        """
        Get price at which an order would be filled (market price for that side).
        - For BUY: use best ask (we'd buy at ask)
        - For SELL: use best bid (we'd sell at bid)
        """
        book = self.books.get(symbol)
        if not book or book.is_stale():
            return None
        if side.upper() == "BUY":
            return book.best_ask()
        elif side.upper() == "SELL":
            return book.best_bid()
        return None

    def get_all_symbols_healthy(self, symbols: List[str], max_age_s: float = 5.0) -> bool:
        """Check if all symbols have fresh data."""
        for symbol in symbols:
            book = self.books.get(symbol)
            if not book or book.is_stale(max_age_s=max_age_s):
                return False
        return True

    def health_status(self) -> Dict:
        """Status of all books."""
        return {
            "symbols_with_data": len(self.books),
            "stale_symbols": sum(1 for b in self.books.values() if b.is_stale()),
            "timestamp": utc_timestamp_iso(),
        }
