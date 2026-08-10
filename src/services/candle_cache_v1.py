"""Bounded, rate-limited per-symbol candle cache for the P0.8+ pipeline
(Evidence-First Strategy Expansion v2, §8.4 'bounded buffers', §8 'no
high-frequency REST polling').

Backed by `binance_client.fetch_candles(symbol, interval)` (confirmed to
already exist and return exactly the schema every P0.8+ strategy module
expects -- see `_workspace/18_live_wiring_plan.md`), not a WebSocket
tick-to-candle aggregation pipeline (§8's full bookTicker/aggTrade/
snapshot-sequence machinery is out of scope for this MVP wiring phase --
disclosed, not silently skipped).

A single REST poll per symbol every `refresh_seconds` (default 60s,
matching the 1m candle interval) is not "high-frequency" -- same order of
magnitude as the existing one-shot `signal_generator.warmup()` call this
codebase already makes at startup. Bounded to `max_candles` per symbol so
memory cannot grow unbounded (§8.4).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Dict, List, Mapping, Optional

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = "1m"
DEFAULT_REFRESH_SECONDS = 60.0
# Generous headroom above every current P0.8+ strategy's own MIN_CANDLES
# (trend_cost_aware_v1: 200, sideways_mean_reversion_v1: 90,
# volatility_breakout_v1: 81) plus room for a future strategy needing more,
# without growing without bound.
DEFAULT_MAX_CANDLES = 260

FetchFn = Callable[[str, str], List[Mapping]]


def _make_default_fetch(fetch_limit: int) -> FetchFn:
    """Binds `fetch_limit` (how many candles to REQUEST from Binance) into
    a two-arg (symbol, interval) callable, matching the FetchFn contract
    every test in this file already relies on. Requests `fetch_limit`
    candles up front -- via binance_client.fetch_candles()'s `limit` param,
    added alongside this module -- rather than the shared
    config.CANDLE_LIMIT (100) default, which is below several P0.8+
    strategies' own MIN_CANDLES (e.g. trend_cost_aware_v1 needs 200)."""
    def _fetch(symbol: str, interval: str) -> List[Mapping]:
        from src.services import binance_client
        return binance_client.fetch_candles(symbol, interval, limit=fetch_limit)
    return _fetch


class CandleCache:
    """Thread-safe. One instance is meant to be shared process-wide (see
    `get_default_cache()`); tests construct their own with an injected
    `fetch_fn` and `now_fn` for determinism."""

    def __init__(
        self,
        *,
        fetch_fn: Optional[FetchFn] = None,
        interval: str = DEFAULT_INTERVAL,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        max_candles: int = DEFAULT_MAX_CANDLES,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        if refresh_seconds <= 0:
            raise ValueError("refresh_seconds must be positive")
        if max_candles <= 0:
            raise ValueError("max_candles must be positive")
        self._fetch_fn = fetch_fn if fetch_fn is not None else _make_default_fetch(max_candles)
        self._interval = interval
        self._refresh_seconds = refresh_seconds
        self._max_candles = max_candles
        self._now_fn = now_fn
        self._lock = threading.RLock()
        self._data: Dict[str, List[Mapping]] = {}
        self._last_attempt: Dict[str, float] = {}
        self._last_success: Dict[str, float] = {}

    def get_candles(self, symbol: str, *, force_refresh: bool = False) -> List[Mapping]:
        """Returns the cached candle window for `symbol` (oldest first,
        bounded to max_candles), refreshing from the fetch function if the
        cache is missing or stale. On fetch failure, serves the last known
        (possibly stale) data rather than raising or returning empty --
        a strategy seeing slightly-stale candles is far safer than a
        strategy crashing the caller's loop over a transient network blip;
        callers that need freshness guarantees check `last_success_age_s()`
        themselves. Never raises."""
        with self._lock:
            now = self._now_fn()
            last_attempt = self._last_attempt.get(symbol, 0.0)
            needs_refresh = force_refresh or symbol not in self._data or (now - last_attempt) >= self._refresh_seconds
            if needs_refresh:
                self._last_attempt[symbol] = now  # mark attempted even on failure -- avoids retry-hammering
                try:
                    fresh = self._fetch_fn(symbol, self._interval)
                except Exception as exc:
                    log.warning("[CANDLE_CACHE] fetch failed for %s: %r", symbol, exc)
                    fresh = None
                if fresh:
                    self._data[symbol] = list(fresh[-self._max_candles:])
                    self._last_success[symbol] = now
                elif symbol not in self._data:
                    self._data[symbol] = []
            return list(self._data.get(symbol, []))

    def last_success_age_s(self, symbol: str) -> Optional[float]:
        """Seconds since the last successful fetch for `symbol`, or None if
        never successfully fetched. Callers can use this as a freshness
        gate independent of whether stale data is being served."""
        with self._lock:
            ts = self._last_success.get(symbol)
            if ts is None:
                return None
            return self._now_fn() - ts


_default_cache: Optional[CandleCache] = None
_default_cache_lock = threading.Lock()


def get_default_cache() -> CandleCache:
    """Process-wide cache singleton, analogous to
    strategy_registry.get_default_registry()."""
    global _default_cache
    with _default_cache_lock:
        if _default_cache is None:
            _default_cache = CandleCache()
        return _default_cache
