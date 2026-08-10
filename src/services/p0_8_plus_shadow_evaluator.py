"""Shadow evaluator for the P0.8+ pipeline (Evidence-First Strategy
Expansion v2, Gate G7 -- first live-data-touching phase of this program).

STRUCTURALLY CANNOT open a position: this module never imports
open_paper_position, trade_executor, or any entry primitive (verified by
tests/test_p0_8_plus_shadow_evaluator_bypass.py). Its only output is a
CandidateEvaluation record per (symbol, strategy, side) that a caller may
log or inspect -- nothing here mutates trading state.

Why evaluation-only, not the full open-a-position wiring
_workspace/18_live_wiring_plan.md originally scoped: reconnaissance this
same session found two real gaps that make a genuine open decision
premature, disclosed rather than papered over:

  1. UPDATE 2026-08-10 (same session, later): a real live bid/ask feed is
     now available via live_quote_cache_v1.py, a thin event_bus subscriber
     on market_stream.py's existing "price_tick" publication -- resolved,
     not just approximated, per CLAUDE.md's "always use the standard
     event_bus" rule. This module now uses the real quote whenever one is
     fresh (QUOTE_MAX_AGE_S) and cost_model's spread-cost/slippage terms
     are computed from it; it falls back to the candle-close-based
     synthetic approximation (SYNTHETIC_SPREAD_BPS) only when no live
     quote exists yet (e.g. immediately at process startup, before the
     WebSocket feed's first tick for that symbol arrives, or in a process
     where market_stream.py never started -- such as this module's own
     test suite). Every CandidateEvaluation records which source was used
     (`quote_source`, "live" or "synthetic") so evidence collected while
     falling back is distinguishable, not silently blended with real-quote
     evidence.
  2. regime_classifier_v1.py (built this same session) is a new,
     minimally-validated classifier, not yet cross-checked against real
     time-series behavior. Still open.

Given both, this phase stops at "evaluate and log what the pipeline WOULD
do" -- §11.7 Pattern A's shadow-counterfactual spirit, extended from just
OFI to the whole pipeline. Wiring the actual open_paper_position() call is
explicitly deferred to a follow-up, separately reviewed phase once (1) a
majority of evidence is collected against `quote_source="live"` rather than
falling back to synthetic, and (2) shadow-mode evidence exists to
sanity-check the regime classifier and admission rate against reality.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from src.services import candle_cache_v1
from src.services import live_quote_cache_v1
from src.services import regime_classifier_v1
from src.services import signal_router
from src.services import strategy_contracts as sc
from src.services import strategy_sideways_mean_reversion_v1 as mean_reversion_strategy
from src.services import strategy_trend_cost_aware_v1 as trend_strategy
from src.services import strategy_volatility_breakout_v1 as breakout_strategy
from src.services.strategy_registry import StrategyRegistry, get_default_registry

log = logging.getLogger(__name__)

# §15A.2 spirit: a real long fill crosses the ask, a real short fill
# crosses the bid -- this synthetic approximation applies the same
# convention around the last close so downstream cost math stays
# directionally correct even though the magnitude is not a real quote.
SYNTHETIC_SPREAD_BPS = float(os.getenv("PAPER_P0_8_PLUS_SYNTHETIC_SPREAD_BPS", "3.0"))

# signal_router.py's DEFAULT_MAX_DATA_AGE_MS (5_000ms) is sized for a true
# live tick feed, where market_data_event_time_ms is the age of the last
# bookTicker/aggTrade event. This module stamps market_data_event_time_ms
# from the fetched candle's own open_time (each strategy's
# `latest_open_time_ms`) -- for a 1m REST-polled candle, the in-progress
# bar's open_time can legitimately be up to ~60s old by the time it's
# evaluated, which is *correct* data, not stale data, for this source.
# Found via independent audit (trading-safety-agent, 2026-08-10): with the
# router's tight default, ~92% of ticks were rejected as
# REJECT_STALE_MARKET_DATA purely from this clock-phase mismatch, not from
# any strategy or risk decision -- making the shadow evidence collected
# meaningless (it would mostly show "stale", not real admission behavior).
# 90s covers a full candle interval plus fetch/processing latency with
# margin, while still catching a genuinely stuck/frozen candle cache
# (candle_cache_v1's own refresh_seconds=60 default would otherwise serve
# progressively staler data past this point on a persistent fetch failure).
SHADOW_MAX_DATA_AGE_MS = int(os.getenv("PAPER_P0_8_PLUS_MAX_DATA_AGE_MS", "90000"))

# How old a cached live quote (live_quote_cache_v1) may be and still be
# trusted over the synthetic candle-close approximation. market_stream.py
# publishes on every WebSocket update -- for a liquid symbol that is
# sub-second; 30s is generous margin for a quiet moment while still much
# tighter than the candle-based fallback's own inherent staleness.
QUOTE_MAX_AGE_S = float(os.getenv("PAPER_P0_8_PLUS_QUOTE_MAX_AGE_S", "30.0"))

_STRATEGY_MODULES = (trend_strategy, breakout_strategy, mean_reversion_strategy)

_DEFAULT_SYMBOLS: Tuple[str, ...] = ("ETHUSDT", "ADAUSDT", "SOLUSDT")


def _env_symbols() -> Tuple[str, ...]:
    raw = os.getenv("PAPER_P0_8_PLUS_SYMBOLS", "")
    symbols = tuple(s.strip().upper() for s in raw.split(",") if s.strip())
    return symbols if symbols else _DEFAULT_SYMBOLS


@dataclass(frozen=True)
class CandidateEvaluation:
    symbol: str
    strategy_id: str
    side: str
    regime: str
    regime_confidence: float
    signal: sc.StrategySignal
    evaluation: sc.SignalEvaluation
    quote_source: str  # "live" or "synthetic" -- see module docstring point 1


_registered_symbols: Optional[frozenset] = None


def ensure_registered(symbols: Sequence[str], *, registry: Optional[StrategyRegistry] = None) -> None:
    """Idempotent: registers (or re-registers, if the allowed-symbol set
    changed) each strategy's build_registration() with allowed_symbols
    populated from deployment config -- exactly the "populated by the
    caller/deployment config, not hardcoded" hook every strategy module's
    build_registration() docstring already calls out."""
    global _registered_symbols
    reg = registry if registry is not None else get_default_registry()
    symbol_set = frozenset(symbols)
    if registry is None and _registered_symbols == symbol_set:
        return  # already registered with this exact symbol set on the default registry
    for mod in _STRATEGY_MODULES:
        registration = mod.build_registration()
        registration = dataclasses.replace(registration, allowed_symbols=symbol_set)
        reg.unregister(registration.strategy_id)
        reg.register(registration)
    if registry is None:
        _registered_symbols = symbol_set


def _signal_id_factory(symbol: str, side: str, regime: str, ts: int) -> str:
    return f"p0_8_plus_shadow:{symbol}:{side}:{regime}:{ts}"


def _synthetic_best_bid_ask(candles: Sequence[Mapping]) -> Tuple[float, float]:
    close = float(candles[-1]["close"])
    half_spread = close * (SYNTHETIC_SPREAD_BPS / 2.0) / 10_000.0
    return close - half_spread, close + half_spread


def _resolve_best_bid_ask(
    symbol: str,
    candles: Sequence[Mapping],
    *,
    get_quote_fn: Optional[Callable[..., Optional[live_quote_cache_v1.LastQuote]]] = None,
) -> Tuple[float, float, str]:
    """Prefer a real live quote (live_quote_cache_v1); fall back to the
    candle-close synthetic approximation only when none is fresh enough.
    Returns (best_bid, best_ask, quote_source)."""
    get_quote = get_quote_fn if get_quote_fn is not None else live_quote_cache_v1.get_last_quote
    try:
        quote = get_quote(symbol, max_age_s=QUOTE_MAX_AGE_S)
    except Exception as exc:
        log.warning("[P0_8_PLUS_SHADOW] live quote lookup failed for %s: %r", symbol, exc)
        quote = None
    if quote is not None:
        return quote.bid, quote.ask, "live"
    best_bid, best_ask = _synthetic_best_bid_ask(candles)
    return best_bid, best_ask, "synthetic"


def evaluate_symbol(
    symbol: str,
    *,
    cache: Optional[candle_cache_v1.CandleCache] = None,
    registry: Optional[StrategyRegistry] = None,
    risk_guard_fn: Optional[Callable] = None,
    get_quote_fn: Optional[Callable[..., Optional[live_quote_cache_v1.LastQuote]]] = None,
    now_ms: Optional[int] = None,
) -> List[CandidateEvaluation]:
    """Fetch candles for `symbol`, classify regime, generate candidates from
    every registered P0.8+ strategy, and evaluate each through
    signal_router.evaluate_signal_for_paper_entry(). Never opens a position
    (module docstring) -- returns the evaluations for the caller to
    log/inspect. A strategy or router exception for one candidate is caught
    and logged, not allowed to abort the whole symbol's tick (§8.1 spirit:
    "Do not crash the main loop because of one malformed event.")."""
    cache = cache if cache is not None else candle_cache_v1.get_default_cache()
    candles = cache.get_candles(symbol)
    if len(candles) < regime_classifier_v1.MIN_CANDLES:
        return []

    regime, regime_confidence = regime_classifier_v1.classify_regime(candles)
    best_bid, best_ask, quote_source = _resolve_best_bid_ask(symbol, candles, get_quote_fn=get_quote_fn)
    now_ms_val = now_ms if now_ms is not None else int(time.time() * 1000)

    results: List[CandidateEvaluation] = []
    for mod in _STRATEGY_MODULES:
        try:
            signals = mod.generate_candidates(
                candles=candles,
                symbol=symbol,
                regime=regime,
                regime_confidence=regime_confidence,
                best_bid=best_bid,
                best_ask=best_ask,
                signal_id_factory=_signal_id_factory,
                now_ms=now_ms_val,
            )
        except Exception as exc:
            log.warning("[P0_8_PLUS_SHADOW] %s.generate_candidates failed for %s: %r", mod.__name__, symbol, exc)
            continue
        for signal in signals:
            try:
                evaluation = signal_router.evaluate_signal_for_paper_entry(
                    signal,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    requested_notional=25.0,
                    visible_top_notional=1000.0,
                    realized_volatility_bps=10.0,
                    realized_volatility_bps_per_second=0.1,
                    decision_latency_ms=50.0,
                    now_ms=now_ms_val,
                    max_data_age_ms=SHADOW_MAX_DATA_AGE_MS,
                    registry=registry,
                    risk_guard_fn=risk_guard_fn,
                )
            except Exception as exc:
                log.warning("[P0_8_PLUS_SHADOW] router evaluation failed for %s/%s: %r", symbol, mod.STRATEGY_ID, exc)
                continue
            results.append(CandidateEvaluation(
                symbol=symbol, strategy_id=mod.STRATEGY_ID, side=signal.side,
                regime=regime, regime_confidence=regime_confidence,
                signal=signal, evaluation=evaluation, quote_source=quote_source,
            ))
    return results


def run_shadow_tick(
    symbols: Optional[Sequence[str]] = None,
    *,
    cache: Optional[candle_cache_v1.CandleCache] = None,
) -> List[CandidateEvaluation]:
    """One shadow-evaluation pass over `symbols` (default: deployment
    config via PAPER_P0_8_PLUS_SYMBOLS env, else _DEFAULT_SYMBOLS). Logs a
    summary line per candidate evaluated. Never opens a position (module
    docstring). Safe to call on any cadence -- the candle cache internally
    rate-limits the underlying REST fetches regardless of call frequency."""
    live_quote_cache_v1.ensure_subscribed()
    syms = tuple(symbols) if symbols is not None else _env_symbols()
    ensure_registered(syms)
    all_results: List[CandidateEvaluation] = []
    for symbol in syms:
        results = evaluate_symbol(symbol, cache=cache)
        all_results.extend(results)
        for r in results:
            log.info(
                "[P0_8_PLUS_SHADOW] %s %s %s regime=%s(%.2f) quote=%s admitted=%s code=%s net_edge=%.2fbps",
                r.symbol, r.strategy_id, r.side, r.regime, r.regime_confidence, r.quote_source,
                r.evaluation.admitted, r.evaluation.decision_code, r.evaluation.net_expected_edge_bps,
            )
    if not all_results:
        log.info("[P0_8_PLUS_SHADOW] tick complete: 0 candidates across %d symbol(s)", len(syms))
    return all_results


def start_shadow_monitoring_thread(
    interval_s: float = 60.0,
    symbols: Optional[Sequence[str]] = None,
) -> Optional[threading.Thread]:
    """Start a daemon background thread that calls run_shadow_tick() every
    `interval_s` seconds -- same pattern as
    emergency_health_monitor.start_monitoring_thread() (a daemon thread on
    a fixed interval, no external event loop needed), and the same
    try/except-per-call discipline as evaluate_symbol() itself: one failed
    tick logs and retries next interval, it never kills the thread (§8.1
    spirit: don't crash the main loop over one bad cycle -- extended here
    to "don't crash the monitoring thread over one bad tick").

    Gated by PAPER_P0_8_PLUS_SHADOW_ENABLED (default 'true'). Safe to leave
    on by default: this thread never reaches the paper-entry primitive or
    any other entry primitive (module docstring, bypass-tested), makes no Firestore
    calls, and its only network activity is the same bounded, rate-limited
    REST candle fetch candle_cache_v1.py already rate-limits internally
    regardless of how often this thread ticks. Set to 'false'/'0'/'no'/'off'
    to disable without a code change (e.g. via the systemd overlay).

    Returns the Thread if started, or None if disabled.
    """
    enabled = os.getenv("PAPER_P0_8_PLUS_SHADOW_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")
    if not enabled:
        log.info("[P0_8_PLUS_SHADOW] monitoring thread disabled via PAPER_P0_8_PLUS_SHADOW_ENABLED")
        return None

    def _loop() -> None:
        while True:
            try:
                run_shadow_tick(symbols=symbols)
            except Exception as exc:  # never let one bad tick kill the thread
                log.warning("[P0_8_PLUS_SHADOW] tick failed: %r", exc)
            time.sleep(interval_s)

    t = threading.Thread(target=_loop, name="p0-8-plus-shadow-evaluator", daemon=True)
    t.start()
    log.info("[P0_8_PLUS_SHADOW] monitoring thread started (interval=%.0fs, symbols=%s)",
              interval_s, list(symbols) if symbols is not None else list(_env_symbols()))
    return t
