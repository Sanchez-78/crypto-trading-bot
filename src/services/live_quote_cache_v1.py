"""Live bid/ask quote cache, subscribed to the standard event_bus
(Evidence-First Strategy Expansion v2 -- closes the "no live bid/ask feed"
gap flagged by the trading-safety-agent audit of the P0.8+ shadow
evaluator, 2026-08-10).

`market_stream.py`'s `_dispatch()` already publishes a `"price_tick"` event
with `{"symbol", "price", "obi", "bid", "ask"}` on every WebSocket update
(`src/services/market_stream.py:97-98`). Per `CLAUDE.md`'s explicit rule
("Always use standard `event_bus` for cross-component signaling"), this
module subscribes to that existing event rather than reading
`market_stream.py`'s private `_symbol_prices` dict directly or opening a
second data path (e.g. its own WebSocket connection, or polling a REST
ticker endpoint). It is a thin, bounded subscriber: keeps only the LATEST
tick per symbol, nothing else -- no history, no aggregation.

Read-only from the trading-state perspective: this module never publishes
an event and never calls any entry primitive (verified by
tests/test_live_quote_cache_v1_bypass.py).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class LastQuote:
    symbol: str
    bid: float
    ask: float
    price: float
    received_at_s: float


_lock = threading.RLock()
_last_quotes: Dict[str, LastQuote] = {}
_subscribed = False


def _on_price_tick(data) -> None:
    """event_bus "price_tick" handler. Per event_bus.py's own contract
    ("Handlers MUST be idempotent and tolerate delivery without
    _event_id" / AT-LEAST-ONCE delivery), this handler is naturally
    idempotent -- it only ever overwrites with the latest value, so a
    duplicate or out-of-order-but-still-recent redelivery is harmless.
    Never raises: event_bus.publish() catches handler exceptions and
    logs them, but a malformed payload here should not print an error
    for every tick if the feed sends something unexpected -- validated
    and silently dropped instead (§8.1 spirit: don't let one malformed
    event crash/spam over the main loop)."""
    if not isinstance(data, dict):
        return
    symbol = data.get("symbol")
    bid = data.get("bid")
    ask = data.get("ask")
    price = data.get("price")
    if not symbol or bid is None or ask is None or price is None:
        return
    try:
        bid_f, ask_f, price_f = float(bid), float(ask), float(price)
    except (TypeError, ValueError):
        return
    if bid_f <= 0 or ask_f <= 0 or ask_f < bid_f:
        return
    with _lock:
        _last_quotes[symbol] = LastQuote(
            symbol=symbol, bid=bid_f, ask=ask_f, price=price_f, received_at_s=time.time(),
        )


def ensure_subscribed() -> None:
    """Idempotent: subscribes `_on_price_tick` to the "price_tick" event
    exactly once per process, using event_bus.subscribe_once() (already
    idempotent by design -- see its own docstring) as a second layer of
    idempotency. Safe to call from every consumer's own initialization
    path; only the first call does anything."""
    global _subscribed
    with _lock:
        if _subscribed:
            return
        from src.core.event_bus import subscribe_once
        subscribe_once("price_tick", _on_price_tick)
        _subscribed = True


def get_last_quote(symbol: str, *, max_age_s: Optional[float] = None) -> Optional[LastQuote]:
    """Returns the latest known quote for `symbol`, or None if never seen
    (no ticks received yet -- e.g. at process startup before the first
    WebSocket message, or in a test process where market_stream.py was
    never started) or if `max_age_s` is given and the quote is older than
    that. Never raises."""
    with _lock:
        q = _last_quotes.get(symbol)
    if q is None:
        return None
    if max_age_s is not None and (time.time() - q.received_at_s) > max_age_s:
        return None
    return q


def known_symbols() -> frozenset:
    """Diagnostic helper: which symbols currently have a cached quote."""
    with _lock:
        return frozenset(_last_quotes.keys())
