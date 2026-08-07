"""Phase P0.8 -- trend_cost_aware_v1 (Evidence-First Strategy Expansion v2, §10).

Evidence-only trend-continuation strategy. Produces StrategySignal candidates
(via generate_candidates()) for the central router (signal_router.py) to
evaluate -- this module never calls open_paper_position or any entry
primitive, and never decides admission itself (§16 point 13, §10.9: "No
promotion logic may exist inside the strategy. Promotion must remain
central.").

Candle schema (§8, reused as-is from the real fetch path, not invented):
    {"open_time": int_ms, "open": float, "high": float, "low": float,
     "close": float, "volume": float}
Chronological order, oldest first, candles[-1] is the current/most recent
bar -- the same convention src/services/feature_extractor.py already uses
(regime()/momentum()/vol()/entry()), which this module calls into rather
than recomputing EMA/ATR/volatility a second, possibly-diverging way.

STRATEGY_ID / STRATEGY_VERSION / LEARNING_SOURCE / EXIT_PROFILE are the
literal identity this module registers under (§7.1, §10 header). Changing
feature definitions, thresholds, regime restrictions, or the expected-move
formula requires bumping STRATEGY_VERSION, not editing this one in place
(§7.1's version-reuse prohibition).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence

from src.services import cost_model
from src.services import feature_extractor as fx
from src.services.strategy_contracts import StrategySignal
from src.services.strategy_registry import StrategyRegistration, StrategyRegistry

STRATEGY_ID = "trend_cost_aware"
STRATEGY_VERSION = "1"
LEARNING_SOURCE = "trend_cost_aware_v1"
EXIT_PROFILE = "dynamic_trend_exit_v1"
FEATURE_SCHEMA_VERSION = "trend_cost_aware_v1_features_1"

MIN_CANDLES = 200  # matches feature_extractor.build()'s own EMA200 floor

ALLOWED_LONG_REGIMES = frozenset({"BULL_TREND"})
ALLOWED_SHORT_REGIMES = frozenset({"BEAR_TREND"})

# Thresholds are configuration-shaped constants, not hidden magic numbers
# (§28 "avoid magic numbers"); kept as module constants rather than env-driven
# in this phase since P0.8 is evidence-only and does not yet touch live
# behavior -- promoting these to env vars is in scope once P0.8 exits shadow
# mode, per §20's config list.
MIN_FAST_SLOPE_BPS_PER_MIN = 0.5
MIN_SLOW_SLOPE_BPS_PER_MIN = 0.1
MIN_TREND_PERSISTENCE = 0.55
MIN_REGIME_CONFIDENCE = 0.5
MAX_SPREAD_BPS = 15.0
MIN_ATR_BPS = 2.0  # unusable-floor: near-zero volatility means no tradable move
MAX_ATR_BPS = 500.0  # panic-ceiling: extreme volatility is not "trend", it's chaos
PERSISTENCE_DISCOUNT = 0.5
ATR_REGIME_MULTIPLIER = 0.8


@dataclass(frozen=True)
class TrendFeatures:
    """§10.2 raw trend feature bundle. Kept separate from StrategySignal so
    a candidate's diagnostic feature values survive independent of whether
    it becomes an admitted signal (§10.7 candidate-vs-signal separation)."""

    fast_slope_bps_per_minute: float
    slow_slope_bps_per_minute: float
    price_to_vwap_bps: float
    higher_high_score: float
    higher_low_score: float
    lower_high_score: float
    lower_low_score: float
    trend_persistence_ratio: float
    trend_strength_score: float
    atr_bps: float
    realized_volatility: float


def _slope_bps_per_minute(ema_arr, open_times_ms: Sequence[int], lookback: int) -> float:
    """Rate of change of an EMA series over `lookback` bars, normalized to
    bps-per-minute so fast/slow slopes are comparable regardless of the
    candle interval actually configured upstream."""
    n = min(lookback, len(ema_arr) - 1)
    if n < 1:
        return 0.0
    dt_ms = open_times_ms[-1] - open_times_ms[-1 - n]
    if dt_ms <= 0:
        return 0.0
    dt_minutes = dt_ms / 60_000.0
    prev = ema_arr[-1 - n]
    if prev == 0:
        return 0.0
    change_bps = (ema_arr[-1] - prev) / abs(prev) * 10_000.0
    return change_bps / dt_minutes


def _vwap_bps_offset(candles: Sequence[Mapping], lookback: int = 20) -> float:
    """price_to_vwap_bps -- offset of the current close from a volume-weighted
    average price over the trailing `lookback` bars. Returns 0.0 (neutral,
    not admitted-by-default) if volume data is degenerate rather than
    fabricating a signal from absent data (§8.7, §10.2's 'do not introduce
    future data' spirit extended to 'do not introduce fabricated data')."""
    window = candles[-lookback:] if len(candles) >= lookback else candles
    total_vol = sum(float(c.get("volume", 0.0)) for c in window)
    if total_vol <= 0:
        return 0.0
    vwap = sum(float(c["close"]) * float(c.get("volume", 0.0)) for c in window) / total_vol
    close = float(candles[-1]["close"])
    if vwap <= 0:
        return 0.0
    return (close - vwap) / vwap * 10_000.0


def _structure_scores(candles: Sequence[Mapping], lookback: int = 10) -> tuple:
    """Higher-high/higher-low/lower-high/lower-low scores (§10.2) -- fraction
    of consecutive-pair comparisons in the trailing window that confirm each
    structure type. Uses only completed historical bars (no lookahead)."""
    window = candles[-(lookback + 1):] if len(candles) >= lookback + 1 else candles
    if len(window) < 3:
        return 0.0, 0.0, 0.0, 0.0
    highs = [float(c["high"]) for c in window]
    lows = [float(c["low"]) for c in window]
    n = len(highs) - 1
    hh = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i - 1]) / n
    hl = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i - 1]) / n
    lh = sum(1 for i in range(1, len(highs)) if highs[i] < highs[i - 1]) / n
    ll = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i - 1]) / n
    return hh, hl, lh, ll


def _trend_persistence_ratio(candles: Sequence[Mapping], lookback: int = 20) -> float:
    """Fraction of the trailing `lookback` closed bars whose close-to-close
    return has the same sign as the overall window's net direction."""
    window = candles[-(lookback + 1):] if len(candles) >= lookback + 1 else candles
    closes = [float(c["close"]) for c in window]
    if len(closes) < 3:
        return 0.0
    net_direction = 1 if closes[-1] > closes[0] else -1 if closes[-1] < closes[0] else 0
    if net_direction == 0:
        return 0.0
    same_dir = 0
    total = 0
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        if d == 0:
            continue
        total += 1
        if (1 if d > 0 else -1) == net_direction:
            same_dir += 1
    return same_dir / total if total > 0 else 0.0


def compute_trend_features(candles: Sequence[Mapping]) -> TrendFeatures:
    """§10.2 -- compute the full trend feature bundle from completed candles
    only. Raises ValueError if fewer than MIN_CANDLES are available (fail
    closed on insufficient warmup, §2.5)."""
    if len(candles) < MIN_CANDLES:
        raise ValueError(f"compute_trend_features needs >= {MIN_CANDLES} candles, got {len(candles)}")

    closes = [float(c["close"]) for c in candles]
    open_times = [int(c["open_time"]) for c in candles]

    fast_ema = fx._ema_arr(__import__("numpy").array(closes), 20)
    slow_ema = fx._ema_arr(__import__("numpy").array(closes), 50)

    fast_slope = _slope_bps_per_minute(fast_ema, open_times, lookback=5)
    slow_slope = _slope_bps_per_minute(slow_ema, open_times, lookback=20)

    vwap_offset = _vwap_bps_offset(candles)
    hh, hl, lh, ll = _structure_scores(candles)
    persistence = _trend_persistence_ratio(candles)

    vol_feats = fx.vol(list(candles))
    close = closes[-1]
    atr_bps = (vol_feats["atr"] / close * 10_000.0) if close > 0 else 0.0

    # Composite strength: agreement between slope direction, structure, and
    # persistence -- diagnostic only (§10.6), never itself the admission gate.
    slope_agree = 1.0 if (fast_slope > 0) == (slow_slope > 0) and fast_slope != 0 else 0.0
    structure_score = (hh + hl) if fast_slope > 0 else (lh + ll)
    trend_strength_score = max(0.0, min(1.0, 0.4 * slope_agree + 0.3 * (structure_score / 2.0) + 0.3 * persistence))

    return TrendFeatures(
        fast_slope_bps_per_minute=fast_slope,
        slow_slope_bps_per_minute=slow_slope,
        price_to_vwap_bps=vwap_offset,
        higher_high_score=hh,
        higher_low_score=hl,
        lower_high_score=lh,
        lower_low_score=ll,
        trend_persistence_ratio=persistence,
        trend_strength_score=trend_strength_score,
        atr_bps=atr_bps,
        realized_volatility=vol_feats["vol"],
    )


def _expected_move_bps(
    features: TrendFeatures,
    side: str,
    expected_horizon_seconds: int,
) -> tuple:
    """§10.5 -- gross_expected_move_bps as the MINIMUM of a trend projection
    and an ATR-capped projection (deliberately conservative, matching the
    document's explicit example -- neither term alone, the min of both).
    Returns (gross_expected_move_bps, is_cold_start)."""
    side_u = side.upper()
    slope = features.slow_slope_bps_per_minute if side_u in ("BUY", "LONG") else -features.slow_slope_bps_per_minute
    horizon_minutes = expected_horizon_seconds / 60.0
    trend_projection_bps = max(0.0, slope) * horizon_minutes * PERSISTENCE_DISCOUNT
    atr_projection_bps = features.atr_bps * ATR_REGIME_MULTIPLIER
    # No historical-segment-quantile source is wired in this phase (Gate G0:
    # no reliable per-segment realized-move distribution was found to reuse
    # without risking a second, disagreeing statistic) -- §10.5 explicitly
    # allows a conservative cap + cold-start marking when that evidence is
    # unavailable, rather than fabricating a number.
    gross = min(trend_projection_bps, atr_projection_bps)
    return gross, True  # is_cold_start=True: always true until segment quantiles exist


def _confidence(features: TrendFeatures, regime_confidence: float, data_quality: float) -> float:
    """§10.6 -- diagnostic composite, clamped to [0,1]. Never substitutes
    for the net-edge admission decision (enforced structurally: confidence
    is not a cost_model input anywhere in signal_router.py)."""
    c = (
        0.30 * features.trend_strength_score
        + 0.25 * max(0.0, min(1.0, regime_confidence))
        + 0.20 * features.trend_persistence_ratio
        + 0.25 * max(0.0, min(1.0, data_quality))
    )
    return max(0.0, min(1.0, c))


def long_candidate(
    *,
    features: TrendFeatures,
    regime: str,
    regime_confidence: float,
    spread_bps: float,
    data_quality: float = 1.0,
) -> Optional[str]:
    """§10.3 -- returns None if the long-candidate criteria are met (no
    rejection), or a rejection-reason string. This is a pure gate check
    separate from cost (cost is evaluated centrally, not here)."""
    if regime not in ALLOWED_LONG_REGIMES:
        return f"regime_not_allowed_for_long:{regime}"
    if regime_confidence < MIN_REGIME_CONFIDENCE:
        return f"regime_confidence_too_low:{regime_confidence:.2f}"
    if features.fast_slope_bps_per_minute <= MIN_FAST_SLOPE_BPS_PER_MIN:
        return f"fast_slope_too_weak:{features.fast_slope_bps_per_minute:.3f}"
    if features.slow_slope_bps_per_minute <= MIN_SLOW_SLOPE_BPS_PER_MIN:
        return f"slow_slope_too_weak:{features.slow_slope_bps_per_minute:.3f}"
    if features.price_to_vwap_bps <= 0:
        return "price_below_trend_reference"
    if features.trend_persistence_ratio < MIN_TREND_PERSISTENCE:
        return f"persistence_too_low:{features.trend_persistence_ratio:.2f}"
    if spread_bps > MAX_SPREAD_BPS:
        return f"spread_too_wide:{spread_bps:.2f}"
    if features.atr_bps < MIN_ATR_BPS:
        return f"volatility_below_unusable_floor:{features.atr_bps:.2f}"
    if features.atr_bps > MAX_ATR_BPS:
        return f"volatility_above_panic_ceiling:{features.atr_bps:.2f}"
    return None


def short_candidate(
    *,
    features: TrendFeatures,
    regime: str,
    regime_confidence: float,
    spread_bps: float,
    data_quality: float = 1.0,
) -> Optional[str]:
    """§10.4 -- mirrors long_candidate, but NOT by naive sign-flip of every
    field (§10.4: 'Do not simply multiply every value by -1'). Structure
    scores use the dedicated lower_high/lower_low fields rather than negated
    higher_high/higher_low, and price_to_vwap uses the opposite-sign check
    on its own terms."""
    if regime not in ALLOWED_SHORT_REGIMES:
        return f"regime_not_allowed_for_short:{regime}"
    if regime_confidence < MIN_REGIME_CONFIDENCE:
        return f"regime_confidence_too_low:{regime_confidence:.2f}"
    if features.fast_slope_bps_per_minute >= -MIN_FAST_SLOPE_BPS_PER_MIN:
        return f"fast_slope_too_weak:{features.fast_slope_bps_per_minute:.3f}"
    if features.slow_slope_bps_per_minute >= -MIN_SLOW_SLOPE_BPS_PER_MIN:
        return f"slow_slope_too_weak:{features.slow_slope_bps_per_minute:.3f}"
    if features.price_to_vwap_bps >= 0:
        return "price_above_trend_reference"
    if features.trend_persistence_ratio < MIN_TREND_PERSISTENCE:
        return f"persistence_too_low:{features.trend_persistence_ratio:.2f}"
    if spread_bps > MAX_SPREAD_BPS:
        return f"spread_too_wide:{spread_bps:.2f}"
    if features.atr_bps < MIN_ATR_BPS:
        return f"volatility_below_unusable_floor:{features.atr_bps:.2f}"
    if features.atr_bps > MAX_ATR_BPS:
        return f"volatility_above_panic_ceiling:{features.atr_bps:.2f}"
    return None


def build_registration() -> StrategyRegistration:
    """§16.3 registration for this strategy -- evidence_only=True (§2.4,
    §10.9): no promotion logic exists here or anywhere in this module."""
    return StrategyRegistration(
        strategy_id=STRATEGY_ID,
        current_version=STRATEGY_VERSION,
        enabled=True,
        evidence_only=True,
        allowed_symbols=frozenset(),  # populated by the caller/deployment config, not hardcoded here
        allowed_regimes=ALLOWED_LONG_REGIMES | ALLOWED_SHORT_REGIMES,
        allowed_sides=frozenset({"BUY", "SELL"}),
        exit_profile=EXIT_PROFILE,
        minimum_warmup_seconds=0,  # warmup is expressed as MIN_CANDLES, not wall-clock time
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
    """§10.7 -- top-level candidate generator. Returns zero, one, or (in a
    conflicting-data edge case) technically up to two StrategySignal objects
    (long and short cannot both pass their gates simultaneously under this
    module's mutually-exclusive regime restriction, but the function does
    not special-case that -- it is structurally impossible given
    ALLOWED_LONG_REGIMES/ALLOWED_SHORT_REGIMES are disjoint).

    `signal_id_factory` is an injected callable (not `uuid.uuid4` called
    directly) so tests can assert determinism (§7.2: 'signal ID must be
    deterministic for the same candidate episode').

    Never opens a position. Never imports anything from the paper-entry
    surface (verified by tests/test_signal_router_bypass.py's module list
    extended to include this file, or a dedicated bypass test -- see
    tests/test_strategy_trend_cost_aware_v1_bypass.py).
    """
    if best_ask < best_bid or best_bid <= 0:
        return []
    spread_bps = (best_ask - best_bid) / ((best_ask + best_bid) / 2.0) * 10_000.0

    try:
        features = compute_trend_features(candles)
    except ValueError:
        return []  # insufficient warmup -- fail closed, not an exception to the caller

    signals: List[StrategySignal] = []
    reference_price = float(candles[-1]["close"])
    latest_open_time_ms = int(candles[-1]["open_time"])

    for side, gate_fn in (("BUY", long_candidate), ("SELL", short_candidate)):
        rejection = gate_fn(
            features=features, regime=regime, regime_confidence=regime_confidence,
            spread_bps=spread_bps, data_quality=data_quality,
        )
        if rejection is not None:
            continue

        gross_move_bps, is_cold_start = _expected_move_bps(features, side, expected_horizon_seconds)
        if gross_move_bps <= 0:
            continue

        try:
            edge = cost_model.evaluate_edge(
                side=side,
                gross_expected_move_bps=gross_move_bps,
                best_bid=best_bid,
                best_ask=best_ask,
                requested_notional=25.0,  # placeholder self-estimate; router recomputes authoritatively
                visible_top_notional=1000.0,
                realized_volatility_bps=features.atr_bps,
                realized_volatility_bps_per_second=features.realized_volatility * 10_000.0 / 60.0,
                decision_latency_ms=50.0,
                expected_horizon_seconds=float(expected_horizon_seconds),
            )
        except ValueError:
            continue

        # §10.3/§10.4's candidate criteria list explicitly includes "net
        # expected edge positive after costs" as a CANDIDATE-level gate, not
        # only something the central router checks downstream (§16). The
        # router still independently recomputes and re-checks this (never
        # trusts a strategy's self-report for the actual admission decision)
        # -- this is a genuine self-filter so a strategy in evidence-only
        # mode doesn't manufacture noisy, structurally-losing "candidates"
        # for every tick just because a trend gate passed.
        if not edge.admitted:
            continue

        confidence = _confidence(features, regime_confidence, data_quality)
        atr_stop_distance = max(features.atr_bps, MIN_ATR_BPS) / 10_000.0 * reference_price
        if side == "BUY":
            invalidation = reference_price - atr_stop_distance
            stop = invalidation
            target = reference_price + gross_move_bps / 10_000.0 * reference_price
        else:
            invalidation = reference_price + atr_stop_distance
            stop = invalidation
            target = reference_price - gross_move_bps / 10_000.0 * reference_price

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
                "fast_slope_bps_per_minute": features.fast_slope_bps_per_minute,
                "slow_slope_bps_per_minute": features.slow_slope_bps_per_minute,
                "price_to_vwap_bps": features.price_to_vwap_bps,
                "trend_persistence_ratio": features.trend_persistence_ratio,
                "trend_strength_score": features.trend_strength_score,
                "atr_bps": features.atr_bps,
                "cold_start": is_cold_start,
            },
            reason_codes=("TREND_CANDIDATE_ADMITTED",),
            evidence_only=True,  # §2.4 -- structurally always True for this strategy in this phase
        ))

    return signals
