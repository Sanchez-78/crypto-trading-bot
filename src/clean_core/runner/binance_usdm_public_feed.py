"""Live Binance USDⓈ-M Futures public feed implementation."""

from typing import Optional, List, Dict, Any, Callable
import threading
import websocket
import json
import logging
import time
from datetime import datetime, timezone
from queue import Queue, Empty
from .public_futures_feed import PublicFuturesFeed, MarketSnapshot, Trade

logger = logging.getLogger(__name__)


class BinanceUsdmPublicFeed:
    """
    Live WebSocket feed from Binance USDⓈ-M Futures public streams.

    Connections to bookTicker stream (execution basis) and mark price stream (telemetry only).
    Uses threading for background WebSocket consumption with timeout and reconnect handling.
    """

    def __init__(
        self,
        base_url: str = "wss://fstream.binance.com/ws",
        timeout_seconds: int = 30,
        max_reconnect_attempts: int = 5,
    ):
        """
        Args:
            base_url: WebSocket base URL (Binance USDⓈ-M Futures public only)
            timeout_seconds: Timeout for WebSocket operations
            max_reconnect_attempts: Max reconnection tries before failure
        """
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_reconnect_attempts = max_reconnect_attempts
        self.symbol = None
        self.current_depth = None
        self.trade_queue = Queue()
        self.depth_thread = None
        self.trade_thread = None
        self.running = False
        self.connected = False

    def initialize(self, symbol: str) -> None:
        """
        Initialize live feed for a symbol.

        Starts background threads for bookTicker (depth) and agg trade streams.
        Blocks until initial snapshot is received or timeout.
        """
        self.symbol = symbol.lower()
        self.running = True

        # Start depth stream (bookTicker for best bid/ask)
        self.depth_thread = threading.Thread(
            target=self._run_depth_stream,
            args=(self.symbol,),
            daemon=False,
        )
        self.depth_thread.start()

        # Start trade stream (aggregated trades for execution)
        self.trade_thread = threading.Thread(
            target=self._run_trade_stream,
            args=(self.symbol,),
            daemon=False,
        )
        self.trade_thread.start()

        # Wait for initial depth snapshot with timeout
        start_time = time.time()
        while not self.current_depth and (time.time() - start_time) < self.timeout_seconds:
            time.sleep(0.1)

        if not self.current_depth:
            self.running = False
            raise TimeoutError(
                f"Failed to receive initial depth snapshot for {symbol} within {self.timeout_seconds}s"
            )

        self.connected = True
        logger.info(f"BinanceUsdmPublicFeed connected for {symbol}")

    def _run_depth_stream(self, symbol: str) -> None:
        """
        Background thread: consume bookTicker stream for best bid/ask.

        Uses routed public endpoint: /public/ws/
        Implements reconnect logic and error handling.
        """
        stream_name = f"{symbol}@bookTicker"
        ws_url = f"{self.base_url}/public/ws/{stream_name}"
        reconnect_count = 0
        first_event_received = False

        while self.running and reconnect_count < self.max_reconnect_attempts:
            try:
                logger.info(f"Connecting to depth stream: {stream_name}")
                ws = websocket.create_connection(ws_url, timeout=self.timeout_seconds)

                while self.running:
                    try:
                        msg = ws.recv()
                        if msg:
                            data = json.loads(msg)
                            # bookTicker: {"b": <bid>, "a": <ask>, "E": <timestamp>}
                            self.current_depth = {
                                "bid": float(data.get("b", 0)),
                                "ask": float(data.get("a", 0)),
                                "timestamp": int(data.get("E", 0)),
                            }
                            # Log first event received
                            if not first_event_received:
                                logger.info(
                                    f"BOOK_TICKER_EVENT_RECEIVED symbol={symbol.upper()} "
                                    f"bid={self.current_depth['bid']} ask={self.current_depth['ask']}"
                                )
                                first_event_received = True
                            reconnect_count = 0  # Reset on successful recv
                    except websocket.WebSocketTimeoutException:
                        logger.warning(f"Depth stream timeout for {symbol}")
                        break
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse depth message: {e}")
                        continue

                ws.close()
            except Exception as e:
                reconnect_count += 1
                logger.warning(
                    f"Depth stream error for {symbol} (attempt {reconnect_count}/{self.max_reconnect_attempts}): {e}"
                )
                if reconnect_count < self.max_reconnect_attempts and self.running:
                    time.sleep(2 ** reconnect_count)  # Exponential backoff

        if reconnect_count >= self.max_reconnect_attempts:
            logger.error(f"Depth stream max reconnect attempts exceeded for {symbol}")
            self.running = False

    def _run_trade_stream(self, symbol: str) -> None:
        """
        Background thread: consume aggTrade stream for trade execution.

        Uses routed market endpoint: /market/ws/
        Implements reconnect logic and error handling.
        """
        stream_name = f"{symbol}@aggTrade"
        ws_url = f"{self.base_url}/market/ws/{stream_name}"
        reconnect_count = 0
        first_event_received = False

        while self.running and reconnect_count < self.max_reconnect_attempts:
            try:
                logger.info(f"Connecting to trade stream: {stream_name}")
                ws = websocket.create_connection(ws_url, timeout=self.timeout_seconds)

                while self.running:
                    try:
                        msg = ws.recv()
                        if msg:
                            data = json.loads(msg)
                            # aggTrade: {"p": <price>, "q": <qty>, "T": <timestamp>, "m": <is_buyer_maker>}
                            trade = Trade(
                                symbol=symbol.upper(),
                                timestamp_utc=datetime.fromtimestamp(
                                    int(data.get("T", 0)) / 1000.0, tz=timezone.utc
                                ).isoformat(),
                                price=float(data.get("p", 0)),
                                qty=float(data.get("q", 0)),
                                side="sell" if data.get("m") else "buy",
                            )
                            # Log first event received
                            if not first_event_received:
                                logger.info(
                                    f"AGG_TRADE_EVENT_RECEIVED symbol={symbol.upper()} "
                                    f"price={trade.price} quantity={trade.qty}"
                                )
                                first_event_received = True
                            self.trade_queue.put(trade)
                            reconnect_count = 0  # Reset on successful recv
                    except websocket.WebSocketTimeoutException:
                        logger.debug(f"Trade stream recv timeout for {symbol}")
                        continue
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse trade message: {e}")
                        continue

                ws.close()
            except Exception as e:
                reconnect_count += 1
                logger.warning(
                    f"Trade stream error for {symbol} (attempt {reconnect_count}/{self.max_reconnect_attempts}): {e}"
                )
                if reconnect_count < self.max_reconnect_attempts and self.running:
                    time.sleep(2 ** reconnect_count)  # Exponential backoff

        if reconnect_count >= self.max_reconnect_attempts:
            logger.error(f"Trade stream max reconnect attempts exceeded for {symbol}")
            self.running = False

    def get_snapshot(self) -> Optional[MarketSnapshot]:
        """
        Get current best bid/ask as snapshot.

        Returns None if feed not connected.
        """
        if not self.symbol or not self.current_depth or not self.running:
            return None
        return MarketSnapshot(
            symbol=self.symbol.upper(),
            timestamp_utc=datetime.fromtimestamp(
                self.current_depth.get("timestamp", 0) / 1000.0, tz=timezone.utc
            ).isoformat(),
            price=(self.current_depth.get("bid", 0) + self.current_depth.get("ask", 0)) / 2,
            bid=self.current_depth.get("bid", 0),
            ask=self.current_depth.get("ask", 0),
        )

    def get_next_trade(self, timeout_seconds: float = 0.5) -> Optional[Trade]:
        """
        Get next trade from stream with short timeout.

        Returns None if no trades available or feed stopped.
        """
        if not self.running:
            return None
        try:
            return self.trade_queue.get(timeout=timeout_seconds)
        except Empty:
            return None

    def close(self) -> None:
        """Close WebSocket connections and background threads."""
        logger.info(f"Closing BinanceUsdmPublicFeed for {self.symbol}")
        self.running = False

        # Wait for threads to finish (with timeout)
        if self.depth_thread:
            self.depth_thread.join(timeout=5)
        if self.trade_thread:
            self.trade_thread.join(timeout=5)

        self.connected = False
        logger.info(f"BinanceUsdmPublicFeed closed for {self.symbol}")
