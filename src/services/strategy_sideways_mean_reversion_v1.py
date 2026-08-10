"""Phase P1.2 -- sideways_mean_reversion_v1 (Evidence-First Strategy Expansion
v2, §14).

Evidence-only strategy: fade extension away from a rolling mean, restricted
to a hard SIDEWAYS regime (§14.1: "Do not allow 'weak trend' to automatically
mean sideways" -- this module rejects everything except the exact SIDEWAYS
classification, not merely a low-trend-strength trend). Same posture as
strategy_trend_cost_aware_v1.py (§10, P0.8) and strategy_volatility_breakout_v1.py
(§13, P1.1): produces StrategySignal candidates via generate_candidates() for
the central router to evaluate; never calls open_paper_position or any entry
primitive; contains no promotion logic (§10.9's rule, identically applied).

Deliberately does NOT import from strategy_trend_cost_aware_v1.py or
strategy_volatility_breakout_v1.py despite overlapping concepts (slope,
range expansion) -- each strategy module owns its own feature computation so
a change to one strategy's internals can never silently change another's
admission behavior (§13.7's "never mix evidence" principle extended to code
coupling, not just segment keys).

mean_reversion_exit_v1 (EXIT_PROFILE) is NOT built in this phase -- deferred,
same disclosed gap as strategy_volatility_breakout_v1.py's
dynamic_breakout_exit_v1. Nothing calls generate_candidates() from the live
decision loop yet (confirmed non-wired, matching every P0.8+ module).

§14.5 "Prohibited behavior" (martingale, doubling down, unbounded DCA,
averaging into adverse movement, increasing size after a loss, grid
recovery, holding until price eventually returns): structurally impossible
here by construction -- this module has no position-sizing logic, no
knowledge of prior losses, and no loop that emits more than one signal per
symbol/side per call. See tests/test_strategy_sideways_mean_reversion_v1_bypass.py.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence

from src.services import cost_model
from src.services import feature_extractor as fx
from src.services.strategy_contracts import StrategySignal
from src.services.strategy_registry import StrategyRegistration

STRATEGY_ID = "sideways_mean_reversion"
STRATEGY_VERSION = "1"
LEARNING_SOURCE = "sideways_mean_reversion_v1"
EXIT_PROFILE = "mean_reversion_exit_v1"
FEATURE_SCHEMA_VERSION = "sideways_mean_reversion_v1_features_1"

ZSCORE_LOOKBACK = 30
SLOPE_LOOKBACK = 20
# Needs enough history for the slow EMA to converge before its slope is
# measured (see _slow_slope_bps_per_minute), not just ZSCORE_LOOKBACK +
# SLOPE_LOOKBACK's raw minimum.
MIN_CANDLES = 90

# §14.1 hard regime restriction -- SIDEWAYS only, never VOLATILE or a trend
# regime (unlike volatility_breakout_v1, which also allows VOLATILE).
ALLOWED_REGIMES = frozenset({"SIDEWAYS"})

MIN_REGIME_CONFIDENCE = 0.5
MIN_ABS_ZSCORE = 1.5  # §14.3 entry threshold
MAX_ABS_SLOPE_BPS_PER_MIN = 0.15  # §14.1 "trend slopes near zero"
MAX_RANGE_EXPANSION_RATIO = 1.3  # §14.1 "no confirmed volatility expansion" / "no breakout in progress"
MAX_SPREAD_BPS = 15.0
MIN_ATR_BPS = 2.0
MAX_ATR_BPS = 500.0
MEAN_REVERSION_DISCOUNT = 0.6  # conservative: do not assume a full return to the mean
ATR_STOP_MULTIPLIER = 1.2


@dataclass(frozen=True)
class MeanReversionFeatures:
    """§14.2/§14.3 raw feature bundle. Kept separate from StrategySignal so a
    candidate's diagnostic values survive independent of whether it becomes
    an admitted signal (§10.7's candidate-vs-signal separation, reused
    identically across every P0.8+ strategy module)."""

    mean_reference_price: float
    price_zscore: float
    distance_from_mean_bps: float
    slow_slope_bps_per_minute: float
    range_expansion_ratio: float
    atr_bps: float


def _rolling_mean_reference(candles: Sequence[Mapping], lookback: int) -> float:
    """§14.2 -- volume-weighted mean over the trailing `lookback` completed
    bars (excludes the current bar, so the reference the current price is
    measured against is not itself inflated by that price)."""
    window = candles[-(lookback + 1):-1] if len(candles) >= lookback + 1 else candles[:-1]
    if not window:
        return float(candles[-1]["close"])
    total_vol = sum(float(c.get("volume", 0.0)) for c in window)
    if total_vol <= 0:
        return sum(float(c["close"]) for c in window) / len(window)
    return sum(float(c["close"]) * float(c.get("volume", 0.0)) for c in window) / total_vol


def _price_zscore(candles: Sequence[Mapping], lookback: int) -> float:
    """§14.3 -- standard-score of the current close against the trailing
    closed-bar distribution (excludes the current bar from the population,
    same no-lookahead discipline as _rolling_mean_reference)."""
    window = candles[-(lookback + 1):-1] if len(candles) >= lookback + 1 else candles[:-1]
    closes = [float(c["close"]) for c in window]
    if len(closes) < 3:
        return 0.0
    mean = statistics.fmean(closes)
    stdev = statistics.pstdev(closes)
    if stdev <= 0:
        return 0.0
    return (float(candles[-1]["close"]) - mean) / stdev


def _slow_slope_bps_per_minute(candles: Sequence[Mapping], lookback: int) -> float:
    """Rate of change of a slow EMA over `lookback` completed bars,
    normalized to bps-per-minute -- deliberately a local, independent
    computation rather than importing strategy_trend_cost_aware_v1's private
    helper (module-boundary isolation, see module docstring).

    The EMA is computed over the FULL completed-bar history available (not
    just a `lookback`-sized slice) so it is properly converged before the
    slope is measured over the trailing `lookback` points -- an EMA seeded
    from only ~lookback bars is still mostly transient and reports spurious
    slope from ordinary noise, which would make the §14.1 near-zero-slope
    gate unusably fragile."""
    window = candles[:-1]
    closes = [float(c["close"]) for c in window]
    if len(closes) < lookback + 2:
        return 0.0
    import numpy as np
    ema = fx._ema_arr(np.array(closes), 20)
    n = min(lookback, len(ema) - 1)
    if n < 1:
        return 0.0
    open_times = [int(c["open_time"]) for c in window]
    dt_ms = open_times[-1] - open_times[-1 - n]
    if dt_ms <= 0:
        return 0.0
    dt_minutes = dt_ms / 60_000.0
    prev = ema[-1 - n]
    if prev == 0:
        return 0.0
    change_bps = (ema[-1] - prev) / abs(prev) * 10_000.0
    return change_bps / dt_minutes


def compute_mean_reversion_features(candles: Sequence[Mapping]) -> MeanReversionFeatures:
    """§14.2/§14.3 -- compute the full mean-reversion feature bundle from
    completed candles only. Raises ValueError if fewer than MIN_CANDLES are
    available (fail closed on insufficient warmup, §2.5)."""
    if len(candles) < MIN_CANDLES:
        raise ValueError(f"compute_mean_reversion_features needs >= {MIN_CANDLES} candles, got {len(candles)}")

    mean_ref = _rolling_mean_reference(candles, ZSCORE_LOOKBACK)
    zscore = _price_zscore(candles, ZSCORE_LOOKBACK)
    close = float(candles[-1]["close"])
    distance_bps = ((close - mean_ref) / mean_ref * 10_000.0) if mean_ref > 0 else 0.0
    slope = _slow_slope_bps_per_minute(candles, SLOPE_LOOKBACK)

    recent_window = candles[-(ZSCORE_LOOKBACK + 1):-1] if len(candles) >= ZSCORE_LOOKBACK + 1 else candles[:-1]
    avg_range = (
        sum(float(c["high"]) - float(c["low"]) for c in recent_window) / len(recent_window)
        if recent_window else 0.0
    )
    current_range = float(candles[-1]["high"]) - float(candles[-1]["low"])
    range_expansion_ratio = (current_range / avg_range) if avg_range > 0 else 1.0

    vol_feats = fx.vol(list(candles))
    atr_bps = (vol_feats["atr"] / close * 10_000.0) if close > 0 else 0.0

    return MeanReversionFeatures(
        mean_reference_price=mean_ref,
        price_zscore=zscore,
        distance_from_mean_bps=distance_bps,
        slow_slope_bps_per_minute=slope,
        range_expansion_ratio=range_expansion_ratio,
        atr_bps=atr_bps,
    )


def long_candidate(
    *,
    features: MeanReversionFeatures,
    regime: str,
    regime_confidence: float,
    spread_bps: float,
    min_regime_confidence: float = MIN_REGIME_CONFIDENCE,
) -> Optional[str]:
    """§14.1/§14.3 -- returns None if the long (buy-the-dip) criteria are
    met, or a rejection-reason string."""
    if regime not in ALLOWED_REGIMES:
        return f"regime_not_allowed_for_mean_reversion:{regime}"
    if regime_confidence < min_regime_confidence:
        return f"regime_confidence_too_low:{regime_confidence:.2f}"
    if abs(features.slow_slope_bps_per_minute) > MAX_ABS_SLOPE_BPS_PER_MIN:
        return f"trend_slope_not_near_zero:{features.slow_slope_bps_per_minute:.3f}"
    if features.range_expansion_ratio > MAX_RANGE_EXPANSION_RATIO:
        return f"breakout_in_progress:{features.range_expansion_ratio:.2f}"
    if features.price_zscore > -MIN_ABS_ZSCORE:
        return f"zscore_not_extended_below_mean:{features.price_zscore:.2f}"
    if spread_bps > MAX_SPREAD_BPS:
        return f"spread_too_wide:{spread_bps:.2f}"
    if features.atr_bps < MIN_ATR_BPS:
        return f"volatility_below_unusable_floor:{features.atr_bps:.2f}"
    if features.atr_bps > MAX_ATR_BPS:
        return f"volatility_above_panic_ceiling:{features.atr_bps:.2f}"
    return None


def short_candidate(
    *,
    features: MeanReversionFeatures,
    regime: str,
    regime_confidence: float,
    spread_bps: float,
    min_regime_confidence: float = MIN_REGIME_CONFIDENCE,
) -> Optional[str]:
    """§14.3 'Potential short setup mirrors the logic' -- uses the same
    zscore/slope/range-expansion features on their own terms (not a sign
    flip of the long check's field names, which is trivially true here
    since both directions read the same shared zscore field but gate it
    with opposite-sign thresholds -- see the dedicated non-flip test)."""
    if regime not in ALLOWED_REGIMES:
        return f"regime_not_allowed_for_mean_reversion:{regime}"
    if regime_confidence < min_regime_confidence:
        return f"regime_confidence_too_low:{regime_confidence:.2f}"
    if abs(features.slow_slope_bps_per_minute) > MAX_ABS_SLOPE_BPS_PER_MIN:
        return f"trend_slope_not_near_zero:{features.slow_slope_bps_per_minute:.3f}"
    if features.range_expansion_ratio > MAX_RANGE_EXPANSION_RATIO:
        return f"breakout_in_progress:{features.range_expansion_ratio:.2f}"
    if features.price_zscore < MIN_ABS_ZSCORE:
        return f"zscore_not_extended_above_mean:{features.price_zscore:.2f}"
    if spread_bps > MAX_SPREAD_BPS:
        return f"spread_too_wide:{spread_bps:.2f}"
    if features.atr_bps < MIN_ATR_BPS:
        return f"volatility_below_unusable_floor:{features.atr_bps:.2f}"
    if features.atr_bps > MAX_ATR_BPS:
        return f"volatility_above_panic_ceiling:{features.atr_bps:.2f}"
    return None


def _expected_move_bps(features: MeanReversionFeatures) -> tuple:
    """§14's expected-move: conservative fraction of the distance back to
    the mean, capped by an ATR-based projection -- same min-of-two cold-start
    pattern as trend_cost_aware_v1.§10.5 and volatility_breakout_v1.§13."""
    mean_touch_projection_bps = abs(features.distance_from_mean_bps) * MEAN_REVERSION_DISCOUNT
    atr_projection_bps = features.atr_bps * 1.5
    gross = min(mean_touch_projection_bps, atr_projection_bps)
    return gross, True


def _confidence(features: MeanReversionFeatures, regime_confidence: float, data_quality: float) -> float:
    """Diagnostic composite, clamped to [0,1] -- never a substitute for the
    net-edge admission decision (same structural enforcement as every other
    P0.8+ strategy: confidence is not a cost_model input)."""
    extension_strength = min(1.0, abs(features.price_zscore) / (MIN_ABS_ZSCORE * 2))
    flatness = 1.0 - min(1.0, abs(features.slow_slope_bps_per_minute) / max(MAX_ABS_SLOPE_BPS_PER_MIN, 1e-9))
    c = (
        0.35 * extension_strength
        + 0.25 * flatness
        + 0.20 * max(0.0, min(1.0, regime_confidence))
        + 0.20 * max(0.0, min(1.0, data_quality))
    )
    return max(0.0, min(1.0, c))


def build_registration() -> StrategyRegistration:
    """§16.3 registration -- evidence_only=True (§2.4): no promotion logic
    exists here or anywhere in this module."""
    return StrategyRegistration(
        strategy_id=STRATEGY_ID,
        current_version=STRATEGY_VERSION,
        enabled=True,
        evidence_only=True,
        allowed_symbols=frozenset(),
        allowed_regimes=ALLOWED_REGIMES,
        allowed_sides=frozenset({"BUY", "SELL"}),
        exit_profile=EXIT_PROFILE,
        minimum_warmup_seconds=0,
        required_feature_schema_version=FEATURE_SCHEMA_VERSION,
    )


def generate_candidates(
    *,
    candles: Sequence[Mapping],
    symbol: str,
    regime: str,
    regime_confidence: float,
    best_bid: float,
    best_ask: float,
    signal_id_factory,
    now_ms: int,
    expected_horizon_seconds: int = 300,
    data_quality: float = 1.0,
) -> List[StrategySignal]:
    """§14's top-level candidate generator, structured identically to
    strategy_trend_cost_aware_v1.generate_candidates() and
    strategy_volatility_breakout_v1.generate_candidates() -- see either
    docstring for the shared determinism/bypass-safety guarantees this
    function makes identically. One call emits at most one signal per side,
    and never emits a signal that references a prior loss, a prior fill, or
    any accumulated exposure (§14.5 -- structurally no such inputs exist in
    this function's signature)."""
    if best_ask < best_bid or best_bid <= 0:
        return []
    spread_bps = (best_ask - best_bid) / ((best_ask + best_bid) / 2.0) * 10_000.0

    try:
        features = compute_mean_reversion_features(candles)
    except ValueError:
        return []

    reference_price = float(candles[-1]["close"])
    latest_open_time_ms = int(candles[-1]["open_time"])
    signals: List[StrategySignal] = []

    for side, gate_fn in (("BUY", long_candidate), ("SELL", short_candidate)):
        rejection = gate_fn(
            features=features, regime=regime, regime_confidence=regime_confidence,
            spread_bps=spread_bps,
        )
        if rejection is not None:
            continue

        gross_move_bps, is_cold_start = _expected_move_bps(features)
        if gross_move_bps <= 0:
            continue

        try:
            edge = cost_model.evaluate_edge(
                side=side,
                gross_expected_move_bps=gross_move_bps,
                best_bid=best_bid,
                best_ask=best_ask,
                requested_notional=25.0,
                visible_top_notional=1000.0,
                realized_volatility_bps=features.atr_bps,
                realized_volatility_bps_per_second=features.atr_bps * 10_000.0 / 3_600_000.0,
                decision_latency_ms=50.0,
                expected_horizon_seconds=float(expected_horizon_seconds),
            )
        except ValueError:
            continue

        # §14.3's setup criteria include the distance clearing costs and
        # uncertainty; router still independently recomputes and re-checks
        # this (identical split to every other P0.8+ strategy).
        if not edge.admitted:
            continue

        confidence = _confidence(features, regime_confidence, data_quality)
        atr_stop_distance = max(features.atr_bps, MIN_ATR_BPS) / 10_000.0 * reference_price

        if side == "BUY":
            invalidation = reference_price - atr_stop_distance * ATR_STOP_MULTIPLIER
            stop = invalidation
            # §14.4 primary exit: mean touch.
            target = features.mean_reference_price
        else:
            invalidation = reference_price + atr_stop_distance * ATR_STOP_MULTIPLIER
            stop = invalidation
            target = features.mean_reference_price

        signal_id = signal_id_factory(symbol, side, regime, latest_open_time_ms)

        signals.append(StrategySignal(
            signal_id=signal_id,
            strategy_id=STRATEGY_ID,
            strategy_version=STRATEGY_VERSION,
            symbol=symbol,
            side=side,
            regime=regime,
            learning_source=LEARNING_SOURCE,
            generated_event_time_ms=latest_open_time_ms,
            generated_processing_time_ms=now_ms,
            market_data_event_time_ms=latest_open_time_ms,
            feature_snapshot_time_ms=latest_open_time_ms,
            expected_horizon_seconds=expected_horizon_seconds,
            reference_price=reference_price,
            gross_expected_move_bps=gross_move_bps,
            expected_cost_bps=edge.all_in_cost_bps,
            uncertainty_buffer_bps=edge.uncertainty_buffer_bps,
            net_expected_edge_bps=edge.net_expected_edge_bps,
            confidence=confidence,
            invalidation_price=invalidation,
            initial_stop_price=stop,
            target_reference_price=target,
            exit_profile=EXIT_PROFILE,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            feature_snapshot={
                "mean_reference_price": features.mean_reference_price,
                "price_zscore": features.price_zscore,
                "distance_from_mean_bps": features.distance_from_mean_bps,
                "slow_slope_bps_per_minute": features.slow_slope_bps_per_minute,
                "range_expansion_ratio": features.range_expansion_ratio,
                "atr_bps": features.atr_bps,
                "cold_start": is_cold_start,
            },
            reason_codes=("MEAN_REVERSION_CANDIDATE_ADMITTED",),
            evidence_only=True,
        ))

    return signals
