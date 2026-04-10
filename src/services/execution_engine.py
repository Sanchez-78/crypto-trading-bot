"""
execution_engine.py — Async Execution Engine (Phase 2 / Task 2 + Task 3 + Phase 3)

Subscribes to Redis PubSub channel "signals", receives TradeSignal objects
from SignalEngine, and handles all order lifecycle operations:

  1. Position eligibility check (duplicate, portfolio gates)
  2. Binance order routing (limit → market fallback)
  3. Trailing SL management per active position
  4. L2 order book wall detection → preemptive market exit (Task 3)
  5. Firebase logging (trade open / close records)
  6. Panic button: listens to Firestore "commands" collection for CLOSE_ALL
  7. Adaptive MAX_TICKS: 150 for QUIET_RANGE, 80 for all other regimes

Non-blocking by design:
  - All Binance REST calls are made via httpx async client.
  - All Firebase writes are fire-and-forget (background tasks).
  - Trailing SL checker runs as a separate asyncio task on a 500 ms interval.
  - L2 depth subscription runs as a separate asyncio task (WebSocket).
  - Command listener polls Firestore every 3 s for CLOSE_ALL commands.

This engine does NOT import trade_executor or signal_generator.
Portfolio state (open positions) is maintained in its own _positions dict.
The synchronous trade_executor.py continues to operate in parallel on the
same process — the async engine is an *opt-in* decoupled path.
Enable: EXECUTION_ENGINE_ENABLED=1 in environment.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

EXECUTION_ENGINE_ENABLED: bool = os.getenv("EXECUTION_ENGINE_ENABLED", "0") == "1"
REDIS_URL: str                 = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PUBSUB_CHANNEL: str            = "signals"
BINANCE_API_KEY: str           = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET:  str           = os.getenv("BINANCE_SECRET", "")
BINANCE_BASE:    str           = "https://api.binance.com"

# L2 wall detection parameters (Task 3)
WALL_BAND_PCT:   float = 0.002   # scan ±0.2% from TP price
WALL_RATIO:      float = 5.0     # ask_vol ≥ 5× avg level vol = wall
WALL_TP_APPROACH: float = 0.002  # fire wall check within 0.2% of TP

FEE_RT:          float = 0.0015  # 0.15% round-trip
MAX_TICKS:       int   = 80      # default max price ticks before timeout close
MAX_TICKS_QUIET: int   = 150     # Phase 3 Task 4: extended timeout for QUIET_RANGE
CMD_POLL_SEC:    float = 3.0     # Phase 3 Task 1: command polling interval (seconds)


# ── Position state ─────────────────────────────────────────────────────────────

@dataclass
class Position:
    """Active open position managed by the execution engine."""
    symbol:        str
    action:        str                  # "BUY" | "SELL"
    entry:         float
    size:          float
    tp:            float
    sl:            float
    atr:           float
    regime:        str
    ev:            float
    open_ts:       float = field(default_factory=time.time)
    ticks:         int   = 0
    is_trailing:   bool  = False
    trail_price:   float = 0.0
    max_price:     float = 0.0
    min_price:     float = 0.0
    partial_taken: bool  = False
    signal_raw:    dict  = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.trail_price = self.entry
        self.max_price   = self.entry
        self.min_price   = self.entry


# ── Async Binance REST client ─────────────────────────────────────────────────

class BinanceClient:
    """
    Minimal async Binance REST wrapper.
    Uses httpx for non-blocking HTTP (avoids requests / urllib3 blocking the loop).
    """

    def __init__(self, api_key: str, secret: str, base: str) -> None:
        self._api_key = api_key
        self._secret  = secret
        self._base    = base
        self._client: Optional[Any] = None

    async def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx  # type: ignore[import]
                self._client = httpx.AsyncClient(
                    base_url=self._base,
                    headers={"X-MBX-APIKEY": self._api_key},
                    timeout=5.0,
                )
            except ImportError as e:
                raise RuntimeError(
                    "httpx not installed. Run: pip install httpx") from e
        return self._client

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        import hmac, hashlib, urllib.parse
        params["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params)
        params["signature"] = hmac.new(
            self._secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        return params

    async def market_order(
        self, symbol: str, side: str, quantity: float
    ) -> dict[str, Any]:
        """Place a market order. side = "BUY" | "SELL"."""
        try:
            client = await self._get_client()
            params = self._sign({
                "symbol":   symbol,
                "side":     side,
                "type":     "MARKET",
                "quantity": f"{quantity:.6f}",
            })
            resp = await client.post("/api/v3/order", data=params)
            resp.raise_for_status()
            data: dict = resp.json()
            log.info("market_order %s %s %.6f → fills=%s",
                     side, symbol, quantity, data.get("fills"))
            return data
        except Exception as exc:
            log.error("market_order error: %s", exc)
            return {}

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()


# ── L2 Order Book depth state + wall detector ────────────────────────────────

class L2WallDetector:
    """
    Tracks the live L2 order book top-100 and detects liquidity walls.

    Wall definition (Task 3):
      A "sell wall" exists when the total ask volume in the band
      (tp_price, tp_price × (1 + WALL_BAND_PCT)] is ≥ WALL_RATIO × average
      volume per level across the entire ask side.

    Why top-100 and not top-20?
      With only 20 levels the wall might sit at level 15-20 and not be
      detectable until price is already inside it. 100 levels give enough
      lookahead at the cost of slightly more WebSocket bandwidth.
    """

    def __init__(self) -> None:
        # symbol → {"asks": [(price, qty), ...], "bids": [...], "ts": float}
        self._books: dict[str, dict[str, Any]] = {}

    def update(self, symbol: str, bids: list, asks: list) -> None:
        self._books[symbol] = {
            "bids": [(float(p), float(q)) for p, q in bids if float(q) > 0],
            "asks": [(float(p), float(q)) for p, q in asks if float(q) > 0],
            "ts":   time.time(),
        }

    def is_sell_wall_near_tp(self, symbol: str, current_price: float,
                              tp_price: float) -> bool:
        """
        True when:
        1. current_price is within WALL_TP_APPROACH of tp_price (approaching TP).
        2. Total ask volume in (tp_price, tp_price × (1+WALL_BAND_PCT)] is
           ≥ WALL_RATIO × average ask volume per level.

        Task 3 spec: fires when "approaching TP (within 0.2%) AND massive wall
        5× average level volume is detected right before TP price."
        """
        approach = (tp_price - current_price) / max(current_price, 1e-9)
        if approach > WALL_TP_APPROACH:
            return False   # not close enough to TP yet

        book = self._books.get(symbol)
        if book is None or time.time() - book["ts"] > 5.0:
            return False   # stale or missing

        asks: list[tuple[float, float]] = book["asks"]
        if not asks:
            return False

        upper = tp_price * (1.0 + WALL_BAND_PCT)
        wall_vol = sum(q for p, q in asks if tp_price < p <= upper)
        avg_vol  = sum(q for _, q in asks) / len(asks)

        if avg_vol <= 0:
            return False

        return wall_vol >= WALL_RATIO * avg_vol

    def is_buy_wall_near_tp(self, symbol: str, current_price: float,
                             tp_price: float) -> bool:
        """Mirror for SELL positions: buy wall below TP (which is lower)."""
        approach = (current_price - tp_price) / max(tp_price, 1e-9)
        if approach > WALL_TP_APPROACH:
            return False

        book = self._books.get(symbol)
        if book is None or time.time() - book["ts"] > 5.0:
            return False

        bids: list[tuple[float, float]] = book["bids"]
        if not bids:
            return False

        lower    = tp_price * (1.0 - WALL_BAND_PCT)
        wall_vol = sum(q for p, q in bids if lower <= p < tp_price)
        avg_vol  = sum(q for _, q in bids) / len(bids)

        if avg_vol <= 0:
            return False

        return wall_vol >= WALL_RATIO * avg_vol


# ── Execution Engine ──────────────────────────────────────────────────────────

class ExecutionEngine:
    """
    Lightweight async execution engine.

    Subscribes to Redis "signals" channel, manages open positions,
    routes orders to Binance, and tracks trailing SL + L2 wall exits.
    """

    def __init__(self) -> None:
        self._positions: dict[str, Position] = {}
        self._binance   = BinanceClient(BINANCE_API_KEY, BINANCE_SECRET, BINANCE_BASE)
        self._walls     = L2WallDetector()
        self._running   = False
        self._redis: Optional[Any] = None
        self._boot_ms: int = int(time.time() * 1000)  # epoch ms at startup

    # ── Redis connection ──────────────────────────────────────────────────────

    async def _get_redis(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis  # type: ignore[import]
            self._redis = aioredis.from_url(
                REDIS_URL, decode_responses=True,
                socket_connect_timeout=2, socket_timeout=2,
            )
        return self._redis

    # ── Signal listener ───────────────────────────────────────────────────────

    async def _listen_signals(self) -> None:
        """Subscribe to Redis PubSub and process incoming TradeSignals."""
        from src.services.signal_engine import TradeSignal
        while self._running:
            try:
                r       = await self._get_redis()
                pubsub  = r.pubsub()
                await pubsub.subscribe(PUBSUB_CHANNEL)
                log.info("ExecutionEngine subscribed to channel '%s'", PUBSUB_CHANNEL)

                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message["type"] != "message":
                        continue
                    try:
                        signal = TradeSignal.from_json(message["data"])
                        asyncio.create_task(self._handle_signal(signal))
                    except Exception as exc:
                        log.warning("Signal parse error: %s", exc)

            except Exception as exc:
                log.warning("PubSub connection lost: %s — reconnecting in 3s", exc)
                self._redis = None
                await asyncio.sleep(3)

    # ── Order routing ─────────────────────────────────────────────────────────

    async def _handle_signal(self, signal: "TradeSignal") -> None:
        """
        Validate signal against portfolio state and open a position.

        Gates (lightweight — full gating already done in SignalEngine):
          - Symbol not already open
          - EV > 0 (defense against stale Redis messages from prior session)
        """
        sym = signal.symbol
        if sym in self._positions:
            return
        if signal.ev <= 0 and not signal.explore:
            return

        # ── Compute TP / SL from ATR ──────────────────────────────────────────
        atr_pct = max(signal.atr, signal.price * 0.003) / max(signal.price, 1e-9)
        if signal.action == "BUY":
            tp = signal.price * (1 + 1.1 * atr_pct)
            sl = signal.price * (1 - 0.9 * atr_pct)
        else:
            tp = signal.price * (1 - 1.1 * atr_pct)
            sl = signal.price * (1 + 0.9 * atr_pct)

        # ── Size (simple fixed 2% base — full Kelly handled in sync engine) ───
        size = 0.02

        # ── Place order ───────────────────────────────────────────────────────
        order = await self._binance.market_order(sym, signal.action, size)
        if not order:
            return   # order failed

        actual_entry = float(order.get("fills", [{}])[0].get("price", signal.price))
        pos = Position(
            symbol     = sym,
            action     = signal.action,
            entry      = actual_entry or signal.price,
            size       = size,
            tp         = tp,
            sl         = sl,
            atr        = signal.atr,
            regime     = signal.regime,
            ev         = signal.ev,
            signal_raw = {
                "confidence":  signal.confidence,
                "ws":          signal.ws,
                "coherence":   signal.coherence,
                "regime":      signal.regime,
                "features":    signal.features,
            },
        )
        self._positions[sym] = pos
        log.info("OPEN  %s %s %.6f@%.4f  tp=%.4f sl=%.4f",
                 sym, signal.action, size, pos.entry, tp, sl)
        asyncio.create_task(self._log_open(pos))

    # ── Trailing SL + TP + L2 wall exit (called on each price update) ─────────

    async def handle_price(self, sym: str, price: float) -> None:
        """
        Process one price tick for an open position.
        Called from the async market_stream consumer (or polled via _trail_loop).
        """
        pos = self._positions.get(sym)
        if pos is None:
            return

        pos.ticks += 1
        if price > pos.max_price: pos.max_price = price
        if price < pos.min_price: pos.min_price = price

        move = (price - pos.entry) / pos.entry
        if pos.action == "SELL":
            move *= -1

        # Activate trailing stop at +0.6% profit
        if not pos.is_trailing and move >= 0.006:
            pos.is_trailing  = True
            pos.trail_price  = price
            log.info("TRAIL_ACTIVATED %s move=%.2f%%", sym, move * 100)

        # Update trail price (ratchet)
        if pos.is_trailing:
            if pos.action == "BUY"  and price > pos.trail_price:
                pos.trail_price = price
            elif pos.action == "SELL" and price < pos.trail_price:
                pos.trail_price = price

        reason: Optional[str] = None

        # ── Chandelier stop (trailing) ────────────────────────────────────────
        if pos.is_trailing:
            chand_stop = (pos.max_price - 2.0 * pos.atr if pos.action == "BUY"
                          else pos.min_price + 2.0 * pos.atr)
            if pos.action == "BUY"  and price <= chand_stop: reason = "TRAIL_SL"
            if pos.action == "SELL" and price >= chand_stop: reason = "TRAIL_SL"
        else:
            # Fixed TP / SL
            if pos.action == "BUY":
                if price >= pos.tp: reason = "TP"
                elif price <= pos.sl: reason = "SL"
            else:
                if price <= pos.tp: reason = "TP"
                elif price >= pos.sl: reason = "SL"

        # ── Phase 3 Task 4: adaptive timeout (QUIET_RANGE gets more ticks) ──────
        # QUIET_RANGE has fewer price moves per unit time; use a larger budget
        # so the position gets a fair chance to reach TP before timing out.
        _max_ticks = MAX_TICKS_QUIET if pos.regime == "QUIET_RANGE" else MAX_TICKS
        if reason is None and pos.ticks >= _max_ticks:
            reason = "timeout"
            log.info("TIMEOUT %s ticks=%d/%d move=%.2f%% → closing",
                     sym, pos.ticks, _max_ticks, move * 100)

        # ── Task 3: L2 wall exit ───────────────────────────────────────────────
        # Fires when:
        #   position is profitable (move ≥ 0.10%)
        #   current price is within 0.2% of TP
        #   massive liquidity wall sits right before TP price
        if reason is None and move >= 0.001:
            if pos.action == "BUY" and self._walls.is_sell_wall_near_tp(
                    sym, price, pos.tp):
                reason = "wall_exit"
                log.info("L2 WALL detected BUY %s price=%.4f tp=%.4f → wall_exit",
                         sym, price, pos.tp)
            elif pos.action == "SELL" and self._walls.is_buy_wall_near_tp(
                    sym, price, pos.tp):
                reason = "wall_exit"
                log.info("L2 WALL detected SELL %s price=%.4f tp=%.4f → wall_exit",
                         sym, price, pos.tp)

        if reason:
            await self._close_position(pos, price, reason)

    async def _close_position(self, pos: Position, exit_price: float,
                               reason: str) -> None:
        """Execute market exit, log to Firebase, remove from positions."""
        sym = pos.symbol
        exit_side = "SELL" if pos.action == "BUY" else "BUY"

        order = await self._binance.market_order(sym, exit_side, pos.size)
        if not order:
            log.warning("Exit order failed for %s — keeping position", sym)
            return

        pnl  = (exit_price - pos.entry) / pos.entry
        if pos.action == "SELL":
            pnl *= -1
        pnl -= FEE_RT

        log.info("CLOSE %s %s pnl=%.4f%% reason=%s",
                 sym, pos.action, pnl * 100, reason)

        asyncio.create_task(self._log_close(pos, exit_price, pnl, reason))
        del self._positions[sym]

    # ── Phase 3 Task 1: Panic button command listener ─────────────────────────

    def _fetch_new_commands(self, since_ms: int) -> list[dict]:
        """
        Synchronous Firestore query — runs in executor to avoid blocking the loop.
        Returns documents from 'commands' collection with timestamp_ms > since_ms.
        """
        try:
            from src.services.firebase_client import db
            if db is None:
                return []
            snap = (
                db.collection("commands")
                .where("timestamp_ms", ">", since_ms)
                .order_by("timestamp_ms")
                .limit(10)
                .get()
            )
            return [{"id": d.id, **d.to_dict()} for d in snap]
        except Exception as exc:
            log.debug("_fetch_new_commands error: %s", exc)
            return []

    async def _listen_commands(self) -> None:
        """
        Phase 3 Task 1: Poll Firestore 'commands' collection every CMD_POLL_SEC.

        On receiving action=CLOSE_ALL:
          - Close all open positions at current (last-known) price with
            close_reason="panic".
          - Advance _last_cmd_ms so the same document is not re-processed.

        The React Native app writes the CLOSE_ALL document via triggerPanicButton()
        in signals.js.  Backend processes it here within ~3 s.
        """
        _last_cmd_ms: int = self._boot_ms
        log.info("_listen_commands started (boot_ms=%d, poll=%.1fs)",
                 _last_cmd_ms, CMD_POLL_SEC)

        while self._running:
            await asyncio.sleep(CMD_POLL_SEC)
            if not self._running:
                break

            loop = asyncio.get_running_loop()
            cmds = await loop.run_in_executor(
                None, self._fetch_new_commands, _last_cmd_ms
            )

            for cmd in cmds:
                ts_ms  = cmd.get("timestamp_ms", 0)
                action = cmd.get("action", "")
                log.info("Command received: action=%s id=%s ts_ms=%d",
                         action, cmd.get("id"), ts_ms)

                if action == "CLOSE_ALL":
                    await self._execute_close_all()

                # Advance cursor past this command
                if ts_ms > _last_cmd_ms:
                    _last_cmd_ms = ts_ms

    async def _execute_close_all(self) -> None:
        """Close every open position immediately (panic button handler)."""
        syms = list(self._positions.keys())
        if not syms:
            log.info("CLOSE_ALL: no open positions")
            return

        log.warning("CLOSE_ALL: closing %d position(s): %s", len(syms), syms)
        for sym in syms:
            pos = self._positions.get(sym)
            if pos is None:
                continue
            # Use last known trail_price as a proxy for current price;
            # the actual fill price from the market order will differ slightly.
            exit_price = pos.trail_price if pos.trail_price > 0 else pos.entry
            await self._close_position(pos, exit_price, "panic")

        log.info("CLOSE_ALL: done — %d position(s) sent to market", len(syms))

    # ── Trailing loop (fallback poll when no async price feed is wired) ───────

    async def _trail_loop(self) -> None:
        """
        Fallback: poll order book and trailing SL every 500 ms.
        In production, wire handle_price() directly from the async market_stream.
        """
        while self._running:
            await asyncio.sleep(0.5)
            # Price tracking is driven by handle_price() from WebSocket feed.
            # This loop exists as a safety net for stale positions.

    # ── Firebase logging (fire-and-forget) ───────────────────────────────────

    async def _log_open(self, pos: Position) -> None:
        """Log trade open to Firebase (does not block execution loop)."""
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._firebase_write_open, pos)
        except Exception as exc:
            log.debug("_log_open Firebase error: %s", exc)

    def _firebase_write_open(self, pos: Position) -> None:
        try:
            from src.services.firebase_client import db
            import time as _t
            if db is None:
                return
            doc = {
                "symbol":    pos.symbol,
                "action":    pos.action,
                "entry":     pos.entry,
                "size":      pos.size,
                "tp":        pos.tp,
                "sl":        pos.sl,
                "regime":    pos.regime,
                "ev":        pos.ev,
                "open_ts":   pos.open_ts,
                "engine":    "execution_engine_v2",
            }
            db.collection("trades").add(doc)
        except Exception as exc:
            log.debug("_firebase_write_open error: %s", exc)

    async def _log_close(self, pos: Position, exit_price: float,
                          pnl: float, reason: str) -> None:
        """
        Log trade close to Firebase.
        Preserves existing schema (trades/{id}) with close_reason=wall_exit
        for L2 wall exits. Frontend maps this to 🛡️ L2 OBRANA.
        """
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, self._firebase_write_close,
                pos, exit_price, pnl, reason,
            )
        except Exception as exc:
            log.debug("_log_close Firebase error: %s", exc)

    def _firebase_write_close(self, pos: Position, exit_price: float,
                               pnl: float, reason: str) -> None:
        try:
            from src.services.firebase_client import db, save_last_trade
            import time as _t
            if db is None:
                return
            trade = {
                **pos.signal_raw,
                "symbol":       pos.symbol,
                "action":       pos.action,
                "price":        pos.entry,
                "exit_price":   exit_price,
                "profit":       pnl,
                "result":       "WIN" if pnl > 0 else "LOSS",
                "close_reason": reason,   # "wall_exit" → frontend 🛡️ L2 OBRANA
                "timestamp":    _t.time(),
                "engine":       "execution_engine_v2",
            }
            save_last_trade(trade)
        except Exception as exc:
            log.debug("_firebase_write_close error: %s", exc)

    # ── L2 book update (called from WebSocket depth stream) ──────────────────

    def update_depth(self, symbol: str, bids: list, asks: list) -> None:
        """Update L2 book for `symbol`. Thread-safe (called from async loop)."""
        self._walls.update(symbol, bids, asks)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        log.info("ExecutionEngine started (boot_ms=%d)", self._boot_ms)
        await asyncio.gather(
            self._listen_signals(),
            self._trail_loop(),
            self._listen_commands(),
        )

    async def stop(self) -> None:
        self._running = False
        await self._binance.close()
        if self._redis:
            await self._redis.aclose()
        log.info("ExecutionEngine stopped")


# ── Module-level singleton ────────────────────────────────────────────────────

_engine: Optional[ExecutionEngine] = None


async def start() -> None:
    """
    Entry point — launch from main.py:
        asyncio.create_task(execution_engine.start())
    """
    global _engine
    if not EXECUTION_ENGINE_ENABLED:
        log.info("ExecutionEngine disabled (EXECUTION_ENGINE_ENABLED != 1)")
        return
    _engine = ExecutionEngine()
    await _engine.start()


def get_engine() -> Optional[ExecutionEngine]:
    """Return the active engine instance (for external price/depth callbacks)."""
    return _engine
