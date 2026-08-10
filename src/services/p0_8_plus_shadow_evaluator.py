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

  1. No live bid/ask feed is queryable from outside market_stream.py's
     WebSocket dispatch (it publishes to event_bus internally, exposes no
     "current bid/ask for symbol X" getter). This module approximates
     best_bid/best_ask from the latest fetched candle's close plus a
     configurable synthetic half-spread (SYNTHETIC_SPREAD_BPS) -- an
     approximation, not a real order-book read. cost_model's spread-cost
     and slippage terms are only as honest as this input, so admission
     decisions computed against it must NOT be trusted for real capital
     (even paper capital) allocation yet.
  2. regime_classifier_v1.py (built this same session) is a new,
     minimally-validated classifier, not yet cross-checked against real
     time-series behavior.

Given both, this phase stops at "evaluate and log what the pipeline WOULD
do" -- §11.7 Pattern A's shadow-counterfactual spirit, extended from just
OFI to the whole pipeline. Wiring the actual open_paper_position() call is
explicitly deferred to a follow-up, separately reviewed phase once (1) a
real bid/ask source is integrated and (2) shadow-mode evidence exists to
sanity-check the regime classifier and admission rate against reality.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import time
from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from src.services import candle_cache_v1
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


def evaluate_symbol(
    symbol: str,
    *,
    cache: Optional[candle_cache_v1.CandleCache] = None,
    registry: Optional[StrategyRegistry] = None,
    risk_guard_fn: Optional[Callable] = None,
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
    best_bid, best_ask = _synthetic_best_bid_ask(candles)
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
                    registry=registry,
                    risk_guard_fn=risk_guard_fn,
                )
            except Exception as exc:
                log.warning("[P0_8_PLUS_SHADOW] router evaluation failed for %s/%s: %r", symbol, mod.STRATEGY_ID, exc)
                continue
            results.append(CandidateEvaluation(
                symbol=symbol, strategy_id=mod.STRATEGY_ID, side=signal.side,
                regime=regime, regime_confidence=regime_confidence,
                signal=signal, evaluation=evaluation,
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
    syms = tuple(symbols) if symbols is not None else _env_symbols()
    ensure_registered(syms)
    all_results: List[CandidateEvaluation] = []
    for symbol in syms:
        results = evaluate_symbol(symbol, cache=cache)
        all_results.extend(results)
        for r in results:
            log.info(
                "[P0_8_PLUS_SHADOW] %s %s %s regime=%s(%.2f) admitted=%s code=%s net_edge=%.2fbps",
                r.symbol, r.strategy_id, r.side, r.regime, r.regime_confidence,
                r.evaluation.admitted, r.evaluation.decision_code, r.evaluation.net_expected_edge_bps,
            )
    if not all_results:
        log.info("[P0_8_PLUS_SHADOW] tick complete: 0 candidates across %d symbol(s)", len(syms))
    return all_results
