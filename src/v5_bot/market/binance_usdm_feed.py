"""Binance USDⓈ-M Futures WebSocket feed integration.

Official public market data streams only:
- wss://fstream.binance.com/ws/<symbol>@bookTicker
- wss://fstream.binance.com/market/ws/<symbol>@aggTrade

No Spot URLs. No legacy providers.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, Any
import websockets
from ..util.datetime_utils import utc_now

logger = logging.getLogger(__name__)


@dataclass
class BookTickerUpdate:
    """Order book snapshot from bookTicker stream."""
    symbol: str
    bid: float
    bid_qty: float
    ask: float
    ask_qty: float
    transaction_time: int  # milliseconds since epoch
    received_time: float  # seconds since epoch (local)

    def age_s(self) -> float:
        """Age of this tick in seconds."""
        return utc_now().timestamp() - self.received_time

    def is_stale(self, max_age_s: float = 5.0) -> bool:
        """Check if tick is stale (older than max_age_s)."""
        return self.age_s() > max_age_s

    def midpoint(self) -> float:
        """Midpoint of bid/ask."""
        return (self.bid + self.ask) / 2.0

    def spread_bps(self) -> float:
        """Spread in basis points."""
        if self.midpoint() == 0:
            return 0.0
        return (self.ask - self.bid) / self.midpoint() * 10000


@dataclass
class AggTradeUpdate:
    """Aggregate trade from aggTrade stream."""
    symbol: str
    agg_trade_id: int
    price: float
    qty: float
    first_trade_id: int
    last_trade_id: int
    timestamp: int  # milliseconds
    is_buyer_maker: bool
    received_time: float  # seconds since epoch (local)

    def age_s(self) -> float:
        """Age of this trade in seconds."""
        return utc_now().timestamp() - self.received_time


class BinanceUSDMFeed:
    """Binance USDⓈ-M Futures market data feed."""

    BASE_WS_URL = "wss://fstream.binance.com"
    MARKET_WS_URL = "wss://fstream.binance.com/market/ws"

    def __init__(self):
        """Initialize feed."""
        self.book_tickers: Dict[str, BookTickerUpdate] = {}
        self.last_agg_trades: Dict[str, AggTradeUpdate] = {}
        self.book_task = None
        self.trade_task = None
        self.running = False
        self.reconnect_count = 0
        self.stale_events_rejected = 0

    async def connect(self, symbols: list[str]) -> None:
        """
        Connect to Binance Futures WebSocket streams.

        Args:
            symbols: List of symbols (e.g., ["BTCUSDT", "ETHUSDT"])
        """
        self.running = True
        self.book_task = asyncio.create_task(self._book_stream(symbols))
        self.trade_task = asyncio.create_task(self._trade_stream(symbols))
        logger.info(f"BinanceUSDMFeed connected to {len(symbols)} symbols")

    async def disconnect(self) -> None:
        """Disconnect from WebSocket streams."""
        self.running = False
        if self.book_task:
            self.book_task.cancel()
        if self.trade_task:
            self.trade_task.cancel()
        logger.info("BinanceUSDMFeed disconnected")

    async def _book_stream(self, symbols: list[str]) -> None:
        """Book ticker WebSocket stream."""
        streams = [f"{s.lower()}@bookTicker" for s in symbols]
        url = f"{self.BASE_WS_URL}/ws/{'/'.join(streams)}"
        logger.info(f"[FEED] Connecting bookTicker stream: {url}")

        while self.running:
            try:
                async with websockets.connect(url) as ws:
                    logger.info("bookTicker stream connected")
                    msg_count = 0
                    while self.running:
                        msg = await ws.recv()
                        msg_count += 1
                        if msg_count % 100 == 0:
                            logger.debug(f"[FEED] Received {msg_count} bookTicker messages")
                        data = json.loads(msg)
                        self._process_book_ticker(data)
            except Exception as e:
                self.reconnect_count += 1
                logger.warning(f"bookTicker stream error: {e}, reconnecting...")
                await asyncio.sleep(2)

    async def _trade_stream(self, symbols: list[str]) -> None:
        """Aggregate trade WebSocket stream."""
        streams = [f"{s.lower()}@aggTrade" for s in symbols]
        url = f"{self.MARKET_WS_URL}/{'/'.join(streams)}"

        while self.running:
            try:
                async with websockets.connect(url) as ws:
                    logger.info("aggTrade stream connected")
                    while self.running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        self._process_agg_trade(data)
            except Exception as e:
                self.reconnect_count += 1
                logger.warning(f"aggTrade stream error: {e}, reconnecting...")
                await asyncio.sleep(2)

    def _process_book_ticker(self, data: Dict[str, Any]) -> None:
        """Process book ticker update."""
        try:
            tick = BookTickerUpdate(
                symbol=data["s"],
                bid=float(data["b"]),
                bid_qty=float(data["B"]),
                ask=float(data["a"]),
                ask_qty=float(data["A"]),
                transaction_time=int(data["T"]),
                received_time=utc_now().timestamp(),
            )

            if tick.is_stale(max_age_s=5.0):
                self.stale_events_rejected += 1
                logger.debug(f"Rejected stale bookTicker: {tick.symbol} age={tick.age_s():.1f}s")
                return

            self.book_tickers[tick.symbol] = tick
            logger.debug(f"[FEED] {tick.symbol} bookTicker: bid={tick.bid} ask={tick.ask} spread={tick.spread_bps():.2f}bps")
        except Exception as e:
            logger.error(f"Error processing bookTicker: {e}", exc_info=True)

    def _process_agg_trade(self, data: Dict[str, Any]) -> None:
        """Process aggregate trade update."""
        try:
            trade = AggTradeUpdate(
                symbol=data["s"],
                agg_trade_id=int(data["a"]),
                price=float(data["p"]),
                qty=float(data["q"]),
                first_trade_id=int(data["f"]),
                last_trade_id=int(data["l"]),
                timestamp=int(data["T"]),
                is_buyer_maker=data["m"],
                received_time=utc_now().timestamp(),
            )

            if trade.age_s() > 5.0:
                self.stale_events_rejected += 1
                logger.debug(f"Rejected stale aggTrade: {trade.symbol}")
                return

            self.last_agg_trades[trade.symbol] = trade
        except Exception as e:
            logger.error(f"Error processing aggTrade: {e}")

    def get_book(self, symbol: str) -> Optional[BookTickerUpdate]:
        """Get latest book ticker for symbol."""
        tick = self.book_tickers.get(symbol)
        if tick and not tick.is_stale():
            return tick
        return None

    def get_last_trade(self, symbol: str) -> Optional[AggTradeUpdate]:
        """Get last aggregate trade for symbol."""
        trade = self.last_agg_trades.get(symbol)
        if trade and not trade.is_stale(max_age_s=5.0):
            return trade
        return None

    def is_feed_healthy(self, symbols: list[str], max_age_s: float = 5.0) -> bool:
        """Check if all symbols have recent data."""
        for symbol in symbols:
            tick = self.get_book(symbol)
            if not tick:
                return False
        return True

    def get_status(self) -> Dict[str, Any]:
        """Get feed health status."""
        return {
            "running": self.running,
            "symbols_with_data": len(self.book_tickers),
            "reconnect_count": self.reconnect_count,
            "stale_events_rejected": self.stale_events_rejected,
            "timestamp": utc_now().isoformat(),
        }
