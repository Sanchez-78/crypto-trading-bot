"""
signal_engine.py — Async Signal Engine (Phase 2 / Task 2)

Consumes raw price ticks, runs all feature engineering + ML evaluation,
publishes typed TradeSignal objects to Redis PubSub channel "signals".

Completely decoupled from order execution — the signal engine has ZERO
knowledge of Binance orders, positions, or portfolio state. That concern
belongs exclusively to execution_engine.py.

Architecture
────────────
  market_stream.py  ──tick──►  signal_engine.py
                                  │  feature extraction
                                  │  EV / coherence scoring
                                  │  all gate filters
                                  ▼
                              Redis PubSub channel "signals"
                                  │
                              execution_engine.py
                                  │  order routing
                                  │  trailing SL
                                  ▼
                              Binance API + Firebase

Concurrency model:
  - The engine runs in a single asyncio event loop.
  - Per-symbol feature state is isolated (no cross-symbol locking needed).
  - Redis publish is fire-and-forget (non-blocking).
  - Backpressure: if Redis is unavailable, signals are emitted to the local
    event_bus as fallback so the synchronous execution path still works.

Integration:
  Call signal_engine.start() from main.py to launch the async loop.
  The function is a coroutine — await it or run it with asyncio.run().

  For backward compatibility, the existing synchronous on_price path in
  signal_generator.py + trade_executor.py continues to work unchanged.
  signal_engine.py is an *additional* async path, not a replacement.
  Enable by setting SIGNAL_ENGINE_ENABLED=1 in the environment.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Any, Optional

log = logging.getLogger(__name__)

SIGNAL_ENGINE_ENABLED: bool = os.getenv("SIGNAL_ENGINE_ENABLED", "0") == "1"
REDIS_URL: str              = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PUBSUB_CHANNEL: str         = "signals"
TICK_QUEUE_MAXSIZE: int     = 512   # price-tick buffer before back-pressure

# Phase 4 Task 1 — L2 gate rejection counter (process-lifetime, flushed to Redis)
_l2_rejected: int = 0


def l2_rejected_count() -> int:
    """Return the total number of signals rejected by the L2 entry gate."""
    return _l2_rejected


# ── TradeSignal dataclass ──────────────────────────────────────────────────────

@dataclass
class TradeSignal:
    """
    Immutable trade signal published from SignalEngine to ExecutionEngine.
    All fields are JSON-serialisable primitives.
    """
    symbol:         str
    action:         str          # "BUY" | "SELL"
    price:          float
    atr:            float
    regime:         str
    confidence:     float        # empirical WR from calibrator
    ev:             float        # bounded Sharpe-EV
    ws:             float        # weighted feature score
    coherence:      float        # V10.12 signal coherence
    auditor_factor: float
    explore:        bool         # epsilon-greedy exploration trade
    features:       dict[str, Any]
    timestamp:      float        # unix epoch seconds

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "TradeSignal":
        d = json.loads(raw)
        return cls(**d)


# ── Redis publisher ────────────────────────────────────────────────────────────

class RedisPublisher:
    """Async Redis PubSub publisher with lazy connection and reconnect."""

    def __init__(self, url: str, channel: str) -> None:
        self._url     = url
        self._channel = channel
        self._client: Optional[Any] = None

    async def _ensure_connected(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis  # type: ignore[import]
            self._client = aioredis.from_url(
                self._url,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
        return self._client

    async def publish(self, signal: TradeSignal) -> bool:
        """Publish one signal. Returns True on success, False on error."""
        try:
            r = await self._ensure_connected()
            await r.publish(self._channel, signal.to_json())
            return True
        except Exception as exc:
            log.warning("RedisPublisher.publish error: %s — falling back to event_bus", exc)
            self._client = None   # force reconnect on next attempt
            return False

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# ── Feature + EV evaluation (thin async wrapper over existing sync modules) ───

async def _evaluate_tick(data: dict[str, Any]) -> Optional[TradeSignal]:
    """
    Run feature extraction and EV scoring for one price tick.

    This wraps the *existing* synchronous signal_generator + realtime_decision_engine
    pipeline in an executor so it doesn't block the event loop.
    The result is a TradeSignal or None (filtered).

    The sync pipeline is called in a ThreadPoolExecutor to avoid blocking the
    async event loop during heavy numpy/pandas work.
    """
    loop = asyncio.get_running_loop()

    def _sync_evaluate() -> Optional[dict[str, Any]]:
        """
        Re-uses the existing synchronous evaluation path.
        Returns a signal dict if accepted, None if filtered.
        """
        try:
            from src.services.signal_generator import on_price as sg_on_price
            from src.services.realtime_decision_engine import evaluate_signal
            from src.services.learning_event import track_price

            sym = data.get("symbol", "")
            p   = data.get("price",  0.0)
            if not sym or p <= 0:
                return None

            track_price(sym, p)

            # signal_generator.on_price publishes via event_bus — we intercept
            # by temporarily capturing the last published signal.
            _captured: list[dict] = []

            def _capture(signal: dict) -> None:
                _captured.append(signal)

            from src.core.event_bus import _subscribers
            old_handlers = _subscribers.get("signal_created", [])[:]
            _subscribers["signal_created"] = [_capture]

            try:
                sg_on_price(data)
            finally:
                _subscribers["signal_created"] = old_handlers

            if not _captured:
                return None

            raw_sig = _captured[0]
            # Run through RDE gate (EV scoring, coherence, all guards)
            evaluated = evaluate_signal(raw_sig)
            if evaluated is None:
                return None

            # ── Phase 4 Task 1: L2 entry gate ────────────────────────────────
            # Reject signals that would run head-first into a liquidity wall
            # before reaching their TP.  Uses the shared order_book_depth
            # singleton which is fed by the depth WebSocket in market_stream.
            try:
                from src.services.order_book_depth import (
                    is_sell_wall_near_tp as _ob_sell_wall,
                    is_buy_wall_near_tp  as _ob_buy_wall,
                )
                _e_sym    = evaluated.get("symbol", "")
                _e_price  = float(evaluated.get("price", 0.0))
                _e_atr    = float(evaluated.get("atr", 0.0))
                _e_action = evaluated.get("action", "BUY")

                # Estimate TP the same way execution_engine does
                _atr_pct = max(_e_atr, _e_price * 0.003) / max(_e_price, 1e-9)
                if _e_action == "BUY":
                    _tp_est = _e_price * (1.0 + 1.1 * _atr_pct)
                    _wall   = _ob_sell_wall(_e_sym, _e_price, _tp_est)
                else:
                    _tp_est = _e_price * (1.0 - 1.1 * _atr_pct)
                    _wall   = _ob_buy_wall(_e_sym, _e_price, _tp_est)

                if _wall:
                    # Increment process-lifetime counter (non-blocking global write)
                    import src.services.signal_engine as _self_mod
                    _self_mod._l2_rejected += 1
                    log.info(
                        "REJECTED_L2_WALL %s %s price=%.4f tp_est=%.4f "
                        "(total_rejected=%d)",
                        _e_sym, _e_action, _e_price, _tp_est,
                        _self_mod._l2_rejected,
                    )
                    # Flush counter to Redis for cross-restart persistence
                    try:
                        from src.services.state_manager import increment_l2_rejected
                        increment_l2_rejected()
                    except Exception:
                        pass
                    return None

            except Exception as _gate_exc:
                log.debug("L2 gate error (non-fatal): %s", _gate_exc)

            return evaluated

        except Exception as exc:
            log.debug("_sync_evaluate error: %s", exc)
            return None

    sig_dict = await loop.run_in_executor(None, _sync_evaluate)

    if sig_dict is None:
        return None

    return TradeSignal(
        symbol         = sig_dict.get("symbol", ""),
        action         = sig_dict.get("action", "BUY"),
        price          = float(sig_dict.get("price", 0.0)),
        atr            = float(sig_dict.get("atr", 0.0)),
        regime         = sig_dict.get("regime", "RANGING"),
        confidence     = float(sig_dict.get("confidence", 0.5)),
        ev             = float(sig_dict.get("ev", 0.0)),
        ws             = float(sig_dict.get("ws", 0.5)),
        coherence      = float(sig_dict.get("coherence", 1.0)),
        auditor_factor = float(sig_dict.get("auditor_factor", 1.0)),
        explore        = bool(sig_dict.get("explore", False)),
        features       = sig_dict.get("features", {}),
        timestamp      = time.time(),
    )


# ── Main engine ────────────────────────────────────────────────────────────────

class SignalEngine:
    """
    Async signal evaluation engine.

    Lifecycle:
      engine = SignalEngine()
      await engine.start()           # blocks forever — run as a task
      await engine.enqueue_tick(data)  # called from market_stream WebSocket handler
      await engine.stop()
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=TICK_QUEUE_MAXSIZE)
        self._publisher = RedisPublisher(REDIS_URL, PUBSUB_CHANNEL)
        self._running   = False

    async def enqueue_tick(self, tick: dict[str, Any]) -> None:
        """
        Non-blocking tick ingestion. Drops ticks when queue is full
        (back-pressure) rather than blocking the WebSocket receive loop.
        """
        try:
            self._queue.put_nowait(tick)
        except asyncio.QueueFull:
            log.debug("SignalEngine: tick queue full — dropping %s",
                      tick.get("symbol"))

    async def _process_loop(self) -> None:
        """Drain tick queue, evaluate, publish."""
        while self._running:
            try:
                tick = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            signal = await _evaluate_tick(tick)

            if signal is not None:
                published = await self._publisher.publish(signal)
                if not published:
                    # Fallback: inject directly into the local event_bus so
                    # the synchronous execution path still handles the signal.
                    try:
                        from src.core.event_bus import publish as eb_publish
                        import json as _json
                        eb_publish("signal_created", _json.loads(signal.to_json()))
                    except Exception as exc:
                        log.warning("event_bus fallback error: %s", exc)

            self._queue.task_done()

    async def start(self) -> None:
        """Start the processing loop. Runs until stop() is called."""
        self._running = True
        log.info("SignalEngine started (channel=%s)", PUBSUB_CHANNEL)
        await self._process_loop()

    async def stop(self) -> None:
        self._running = False
        await self._publisher.close()
        log.info("SignalEngine stopped")


# ── Module-level singleton ────────────────────────────────────────────────────

_engine: Optional[SignalEngine] = None
_loop:   Optional[asyncio.AbstractEventLoop] = None


async def start() -> None:
    """
    Entry point — call from main.py:
        import asyncio
        from src.services.signal_engine import start as signal_engine_start
        asyncio.create_task(signal_engine_start())
    """
    global _engine, _loop
    if not SIGNAL_ENGINE_ENABLED:
        log.info("SignalEngine disabled (SIGNAL_ENGINE_ENABLED != 1)")
        return
    _loop   = asyncio.get_running_loop()
    _engine = SignalEngine()
    await _engine.start()


async def enqueue_tick(tick: dict[str, Any]) -> None:
    """Push a price tick into the engine. No-op if engine is not running."""
    if _engine is not None:
        await _engine.enqueue_tick(tick)


def push_tick(tick: dict[str, Any]) -> None:
    """
    Thread-safe sync entry point for non-async callers (e.g. WebSocket callbacks).

    Called from market_stream._on_message when SIGNAL_ENGINE_ENABLED=1.
    Uses call_soon_threadsafe to inject the tick into the asyncio event loop
    without blocking the WebSocket receive thread.
    No-op when the engine or loop is not initialised.
    """
    if _engine is not None and _loop is not None and _loop.is_running():
        try:
            _loop.call_soon_threadsafe(_engine._queue.put_nowait, tick)
        except Exception as exc:
            log.debug("push_tick error: %s", exc)
