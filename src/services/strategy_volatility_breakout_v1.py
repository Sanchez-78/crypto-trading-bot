"""Phase P1.1 -- volatility_breakout_v1 (Evidence-First Strategy Expansion v2, §13).

Evidence-only strategy: capture a transition from volatility compression
into confirmed directional expansion. Same posture as strategy_trend_cost_aware_v1
(§10, P0.8) and order_flow_features (§11, P0.9) -- this module produces
StrategySignal candidates via generate_candidates() for the central router
(signal_router.py) to evaluate. It never calls open_paper_position or any
entry primitive, and never decides admission itself (§16 point 13, §10.9's
"no promotion logic" rule applies identically here -- see §13.9's implicit
inheritance of that rule, this module has no promotion logic either).

§13.7 "Never mix trend and breakout evidence under the same strategy ID":
this module is registered under a distinct STRATEGY_ID/EXIT_PROFILE from
strategy_trend_cost_aware_v1, and its regime allow-list (SIDEWAYS, VOLATILE)
is disjoint from trend's (BULL_TREND, BEAR_TREND) -- a breakout candidate can
occur during what trend calls a "trend regime" in reality, but this module
only fires from a compression-adjacent classified regime, keeping the two
evidence sources structurally separate at the segment-key level (regime is
part of the P0 segment key, §2.4).

Candle schema, chronological order, `signal_id_factory` injection, and
STRATEGY_ID/VERSION versioning discipline are identical to
strategy_trend_cost_aware_v1.py's docstring -- see that file for the shared
conventions this module reuses rather than re-explains.

dynamic_breakout_exit_v1 (the exit engine referenced by EXIT_PROFILE) is NOT
built in this phase -- deferred, same as how P0.8/P0.9 referenced
"dynamic_trend_exit_v1" before P1.0 built it. The identifier is registered
now so P0 segment keys are stable from the first evidence collected; the
engine itself is future work (see docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md).
Until it exists, no runtime component evaluates breakout exits differently
from the existing generic timeout/TP/SL path -- this module produces
candidates only and changes zero live behavior on its own (nothing calls
generate_candidates() from the live decision loop yet, matching every other
phase-P0.8+ module's confirmed non-wired status).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence

from src.services import cost_model
from src.services import feature_extractor as fx
from src.services.strategy_contracts import StrategySignal
from src.services.strategy_registry import StrategyRegistration

STRATEGY_ID = "volatility_breakout"
STRATEGY_VERSION = "1"
LEARNING_SOURCE = "volatility_breakout_v1"
EXIT_PROFILE = "dynamic_breakout_exit_v1"
FEATURE_SCHEMA_VERSION = "volatility_breakout_v1_features_1"

# Compression + Donchian lookback needs headroom for both windows plus the
# percentile-ranking history (§13.2's percentile features need a population
# to rank against, not just the current bar).
DONCHIAN_LOOKBACK = 20
COMPRESSION_HISTORY = 60
MIN_CANDLES = COMPRESSION_HISTORY + DONCHIAN_LOOKBACK + 1

# Regime restriction (§13.7): breakout fires only out of a compression-
# adjacent classified regime, never out of an already-established trend
# regime (that is trend_cost_aware_v1's territory, kept structurally
# separate). Direction (long/short) is determined by which boundary breaks,
# not by regime.
ALLOWED_REGIMES = frozenset({"SIDEWAYS", "VOLATILE"})

# §13.2/§13.5 thresholds -- module constants for the same reason P0.8 kept
# its thresholds as constants rather than env vars: this phase is
# evidence-only and does not yet touch live behavior (§20 promotion is a
# later phase).
COMPRESSION_CHANNEL_WIDTH_PERCENTILE_MAX = 0.35  # "prior compression" gate
MIN_BREAKOUT_DISTANCE_BPS = 8.0  # §13.5 false-breakout protection: minimum clearance
VOLATILITY_EXPANSION_MIN_RATIO = 1.15  # current-bar range vs trailing avg range
VOLUME_EXPANSION_MIN_RATIO = 1.3  # current-bar volume vs trailing avg volume
MAX_SPREAD_BPS = 15.0
MIN_ATR_BPS = 2.0
MAX_ATR_BPS = 500.0
ATR_STOP_MULTIPLIER = 1.5
ATR_TARGET_MULTIPLIER = 2.0
RETEST_STOP_BUFFER_FRAC = 0.0015  # 15bps cushion below/above the breakout level


@dataclass(frozen=True)
class BreakoutFeatures:
    """§13.2/§13.3 raw compression + breakout feature bundle. Kept separate
    from StrategySignal so a candidate's diagnostic values survive
    independent of whether it becomes an admitted signal (§10.7's
    candidate-vs-signal separation, reused identically here)."""

    donchian_high: float
    donchian_low: float
    channel_width_bps: float
    channel_width_percentile: float
    atr_bps: float
    atr_percentile: float
    range_expansion_ratio: float
    volume_expansion_ratio: float
    inside_bar_fraction: float
    declining_range_persistence: float


def _percentile_rank(value: float, population: Sequence[float]) -> float:
    """Fraction of `population` that is <= value. Returns 0.5 (neutral,
    not compression-by-default) if the population is degenerate -- fail
    toward "not compressed" rather than fabricating a compression signal
    from insufficient history (§8.7 spirit: do not manufacture evidence
    from absent data)."""
    if not population:
        return 0.5
    at_or_below = sum(1 for v in population if v <= value)
    return at_or_below / len(population)


def _donchian(candles: Sequence[Mapping], lookback: int) -> tuple:
    """§13.3 -- breakout level from completed historical bars only. The
    channel is computed over the `lookback` bars PRECEDING the current bar
    (candles[-1] is excluded), so the level being tested for a breakout
    cannot itself be inflated by the breakout bar's own high/low."""
    window = candles[-(lookback + 1):-1] if len(candles) >= lookback + 1 else candles[:-1]
    if not window:
        return 0.0, 0.0
    high = max(float(c["high"]) for c in window)
    low = min(float(c["low"]) for c in window)
    return high, low


def _channel_width_series(candles: Sequence[Mapping], lookback: int, history: int) -> List[float]:
    """Trailing series of Donchian channel widths (bps of each window's own
    reference price), used as the population for the percentile rank -- a
    channel is "narrow" only relative to its own recent history, not an
    absolute constant (§13.2: percentile features, not fixed thresholds)."""
    widths = []
    total_needed = lookback + history
    start = max(1, len(candles) - total_needed)
    for i in range(start, len(candles)):
        window = candles[max(0, i - lookback):i]
        if len(window) < 2:
            continue
        high = max(float(c["high"]) for c in window)
        low = min(float(c["low"]) for c in window)
        ref = float(window[-1]["close"])
        if ref > 0:
            widths.append((high - low) / ref * 10_000.0)
    return widths


def _inside_bar_fraction(candles: Sequence[Mapping], lookback: int) -> float:
    """§13.2 -- fraction of bars in the trailing window whose range sits
    entirely inside the prior bar's range (a classic compression tell)."""
    window = candles[-(lookback + 1):] if len(candles) >= lookback + 1 else candles
    if len(window) < 2:
        return 0.0
    inside = 0
    total = 0
    for i in range(1, len(window)):
        prev, cur = window[i - 1], window[i]
        total += 1
        if float(cur["high"]) <= float(prev["high"]) and float(cur["low"]) >= float(prev["low"]):
            inside += 1
    return inside / total if total > 0 else 0.0


def _declining_range_persistence(candles: Sequence[Mapping], lookback: int) -> float:
    """§13.2 -- fraction of consecutive-bar pairs in the trailing window
    where true range shrank, a second independent compression signal beyond
    the channel-width percentile."""
    window = candles[-(lookback + 1):] if len(candles) >= lookback + 1 else candles
    if len(window) < 3:
        return 0.0
    ranges = [float(c["high"]) - float(c["low"]) for c in window]
    total = len(ranges) - 1
    if total <= 0:
        return 0.0
    declining = sum(1 for i in range(1, len(ranges)) if ranges[i] < ranges[i - 1])
    return declining / total


def compute_breakout_features(candles: Sequence[Mapping]) -> BreakoutFeatures:
    """§13.2/§13.3 -- compute the full compression + breakout feature bundle
    from completed candles only. Raises ValueError if fewer than
    MIN_CANDLES are available (fail closed on insufficient warmup, §2.5)."""
    if len(candles) < MIN_CANDLES:
        raise ValueError(f"compute_breakout_features needs >= {MIN_CANDLES} candles, got {len(candles)}")

    donchian_high, donchian_low = _donchian(candles, DONCHIAN_LOOKBACK)
    ref_price = float(candles[-2]["close"]) if len(candles) >= 2 else float(candles[-1]["close"])
    channel_width_bps = ((donchian_high - donchian_low) / ref_price * 10_000.0) if ref_price > 0 else 0.0

    width_population = _channel_width_series(candles[:-1], DONCHIAN_LOOKBACK, COMPRESSION_HISTORY)
    channel_width_percentile = _percentile_rank(channel_width_bps, width_population)

    vol_feats = fx.vol(list(candles))
    close = float(candles[-1]["close"])
    atr_bps = (vol_feats["atr"] / close * 10_000.0) if close > 0 else 0.0

    atr_population = []
    for i in range(max(1, len(candles) - COMPRESSION_HISTORY), len(candles)):
        sub = candles[max(0, i - 15):i]
        if len(sub) < 5:
            continue
        vf = fx.vol(list(sub))
        c = float(sub[-1]["close"])
        if c > 0:
            atr_population.append(vf["atr"] / c * 10_000.0)
    atr_percentile = _percentile_rank(atr_bps, atr_population)

    recent_window = candles[-(DONCHIAN_LOOKBACK + 1):-1] if len(candles) >= DONCHIAN_LOOKBACK + 1 else candles[:-1]
    avg_range = (
        sum(float(c["high"]) - float(c["low"]) for c in recent_window) / len(recent_window)
        if recent_window else 0.0
    )
    current_range = float(candles[-1]["high"]) - float(candles[-1]["low"])
    range_expansion_ratio = (current_range / avg_range) if avg_range > 0 else 1.0

    avg_volume = (
        sum(float(c.get("volume", 0.0)) for c in recent_window) / len(recent_window)
        if recent_window else 0.0
    )
    current_volume = float(candles[-1].get("volume", 0.0))
    volume_expansion_ratio = (current_volume / avg_volume) if avg_volume > 0 else 1.0

    inside_bar_fraction = _inside_bar_fraction(candles[:-1], DONCHIAN_LOOKBACK)
    declining_range_persistence = _declining_range_persistence(candles[:-1], DONCHIAN_LOOKBACK)

    return BreakoutFeatures(
        donchian_high=donchian_high,
        donchian_low=donchian_low,
        channel_width_bps=channel_width_bps,
        channel_width_percentile=channel_width_percentile,
        atr_bps=atr_bps,
        atr_percentile=atr_percentile,
        range_expansion_ratio=range_expansion_ratio,
        volume_expansion_ratio=volume_expansion_ratio,
        inside_bar_fraction=inside_bar_fraction,
        declining_range_persistence=declining_range_persistence,
    )


def _is_compressed(features: BreakoutFeatures) -> bool:
    """§13.2 'prior compression' -- true if the channel is narrow relative
    to its own recent history. A single percentile signal is used as the
    primary gate; inside-bar and declining-range fractions are carried as
    diagnostics in the feature snapshot rather than additional hard gates,
    to avoid over-constraining on redundant correlated signals (§13.6:
    'do not overfit thresholds')."""
    return features.channel_width_percentile <= COMPRESSION_CHANNEL_WIDTH_PERCENTILE_MAX


def long_candidate(
    *,
    features: BreakoutFeatures,
    regime: str,
    regime_confidence: float,
    reference_price: float,
    spread_bps: float,
    min_regime_confidence: float = 0.5,
) -> Optional[str]:
    """§13.4 -- returns None if the long-breakout criteria are met, or a
    rejection-reason string. Pure gate check; cost is evaluated centrally
    by cost_model.evaluate_edge(), not here (§13.4 lists 'net expected edge
    positive after costs' but that check lives in generate_candidates(),
    matching trend_cost_aware_v1's split)."""
    if regime not in ALLOWED_REGIMES:
        return f"regime_not_allowed_for_breakout:{regime}"
    if regime_confidence < min_regime_confidence:
        return f"regime_confidence_too_low:{regime_confidence:.2f}"
    if not _is_compressed(features):
        return f"no_prior_compression:channel_pctile={features.channel_width_percentile:.2f}"
    if features.donchian_high <= 0:
        return "no_valid_breakout_level"
    breakout_distance_bps = (reference_price - features.donchian_high) / features.donchian_high * 10_000.0
    if breakout_distance_bps < MIN_BREAKOUT_DISTANCE_BPS:
        return f"breakout_distance_insufficient:{breakout_distance_bps:.2f}"
    if features.range_expansion_ratio < VOLATILITY_EXPANSION_MIN_RATIO:
        return f"volatility_not_expanding:{features.range_expansion_ratio:.2f}"
    if features.volume_expansion_ratio < VOLUME_EXPANSION_MIN_RATIO:
        return f"volume_not_expanding:{features.volume_expansion_ratio:.2f}"
    if spread_bps > MAX_SPREAD_BPS:
        return f"spread_too_wide:{spread_bps:.2f}"
    if features.atr_bps < MIN_ATR_BPS:
        return f"volatility_below_unusable_floor:{features.atr_bps:.2f}"
    if features.atr_bps > MAX_ATR_BPS:
        return f"volatility_above_panic_ceiling:{features.atr_bps:.2f}"
    return None


def short_candidate(
    *,
    features: BreakoutFeatures,
    regime: str,
    regime_confidence: float,
    reference_price: float,
    spread_bps: float,
    min_regime_confidence: float = 0.5,
) -> Optional[str]:
    """§13.4 mirrored for the downside boundary (§13.4: 'A short breakout
    mirrors the logic') -- uses donchian_low, not a sign-flip of the long
    check, since the two boundaries are independent values."""
    if regime not in ALLOWED_REGIMES:
        return f"regime_not_allowed_for_breakout:{regime}"
    if regime_confidence < min_regime_confidence:
        return f"regime_confidence_too_low:{regime_confidence:.2f}"
    if not _is_compressed(features):
        return f"no_prior_compression:channel_pctile={features.channel_width_percentile:.2f}"
    if features.donchian_low <= 0:
        return "no_valid_breakout_level"
    breakout_distance_bps = (features.donchian_low - reference_price) / features.donchian_low * 10_000.0
    if breakout_distance_bps < MIN_BREAKOUT_DISTANCE_BPS:
        return f"breakout_distance_insufficient:{breakout_distance_bps:.2f}"
    if features.range_expansion_ratio < VOLATILITY_EXPANSION_MIN_RATIO:
        return f"volatility_not_expanding:{features.range_expansion_ratio:.2f}"
    if features.volume_expansion_ratio < VOLUME_EXPANSION_MIN_RATIO:
        return f"volume_not_expanding:{features.volume_expansion_ratio:.2f}"
    if spread_bps > MAX_SPREAD_BPS:
        return f"spread_too_wide:{spread_bps:.2f}"
    if features.atr_bps < MIN_ATR_BPS:
        return f"volatility_below_unusable_floor:{features.atr_bps:.2f}"
    if features.atr_bps > MAX_ATR_BPS:
        return f"volatility_above_panic_ceiling:{features.atr_bps:.2f}"
    return None


def _expected_move_bps(features: BreakoutFeatures, breakout_distance_bps: float) -> tuple:
    """§13's expected-move needs are lighter than §10.5's explicit formula
    (breakout has no equivalent section), so this reuses trend_cost_aware_v1's
    conservative pattern: an ATR-capped projection, marked cold-start until
    segment quantiles exist (same honest gap as trend's §10.5 note).

    Deliberately NOT reduced by `breakout_distance_bps` already travelled --
    an early design considered subtracting it on the theory that distance
    already covered isn't "still ahead", but that inverts the real
    relationship (a decisive initial thrust is evidence FOR continuation,
    not a reason to project less of it) and made the estimate degenerate to
    zero for any breakout larger than the ATR projection itself. The
    parameter is kept (feature-flagged into the signature) so a future,
    evidence-backed continuation model can use it without an interface
    change; it is unused today, same cold-start honesty as trend's §10.5."""
    atr_projection_bps = features.atr_bps * ATR_TARGET_MULTIPLIER
    return atr_projection_bps, True


def _confidence(features: BreakoutFeatures, regime_confidence: float, data_quality: float) -> float:
    """§13's confidence needs mirror §10.6: diagnostic composite, clamped to
    [0,1], never a substitute for the net-edge admission decision (enforced
    structurally the same way -- confidence is not a cost_model input)."""
    compression_strength = 1.0 - features.channel_width_percentile
    c = (
        0.30 * compression_strength
        + 0.20 * min(1.0, features.range_expansion_ratio / (VOLATILITY_EXPANSION_MIN_RATIO * 2))
        + 0.20 * min(1.0, features.volume_expansion_ratio / (VOLUME_EXPANSION_MIN_RATIO * 2))
        + 0.15 * max(0.0, min(1.0, regime_confidence))
        + 0.15 * max(0.0, min(1.0, data_quality))
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
    """§13's top-level candidate generator, structured identically to
    strategy_trend_cost_aware_v1.generate_candidates() -- see that
    docstring for the shared determinism/bypass-safety guarantees this
    function makes identically (injected signal_id_factory, never imports
    from the paper-entry surface, verified by
    tests/test_strategy_volatility_breakout_v1_bypass.py)."""
    if best_ask < best_bid or best_bid <= 0:
        return []
    spread_bps = (best_ask - best_bid) / ((best_ask + best_bid) / 2.0) * 10_000.0

    try:
        features = compute_breakout_features(candles)
    except ValueError:
        return []

    reference_price = float(candles[-1]["close"])
    latest_open_time_ms = int(candles[-1]["open_time"])
    signals: List[StrategySignal] = []

    for side, gate_fn, level in (
        ("BUY", long_candidate, features.donchian_high),
        ("SELL", short_candidate, features.donchian_low),
    ):
        rejection = gate_fn(
            features=features, regime=regime, regime_confidence=regime_confidence,
            reference_price=reference_price, spread_bps=spread_bps,
        )
        if rejection is not None:
            continue

        if side == "BUY":
            breakout_distance_bps = (reference_price - level) / level * 10_000.0
        else:
            breakout_distance_bps = (level - reference_price) / level * 10_000.0

        gross_move_bps, is_cold_start = _expected_move_bps(features, breakout_distance_bps)
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

        # §13.4's candidate criteria explicitly include net-edge-positive as
        # part of confirmation, and the router still independently
        # recomputes this (never trusts a strategy's self-report) --
        # identical split to trend_cost_aware_v1.
        if not edge.admitted:
            continue

        confidence = _confidence(features, regime_confidence, data_quality)
        atr_stop_distance = max(features.atr_bps, MIN_ATR_BPS) / 10_000.0 * reference_price

        if side == "BUY":
            # §13.6 breakout stop: primarily the structural level (retest of
            # the breakout boundary, minus a small cushion -- the classic
            # false-breakout failure mode), widened by the ATR-based
            # invalidation whenever that is the more conservative (farther)
            # of the two. Never the tighter of the two: for a large breakout
            # bar, an ATR-only stop can sit ABOVE the just-broken level,
            # which would mean stopping out on ordinary post-breakout noise
            # rather than an actual retest failure -- structurally wrong for
            # this strategy's own thesis.
            structural_stop = level * (1.0 - RETEST_STOP_BUFFER_FRAC)
            volatility_stop = reference_price - atr_stop_distance
            stop = min(structural_stop, volatility_stop)
            invalidation = stop
            target = reference_price + gross_move_bps / 10_000.0 * reference_price
        else:
            structural_stop = level * (1.0 + RETEST_STOP_BUFFER_FRAC)
            volatility_stop = reference_price + atr_stop_distance
            stop = max(structural_stop, volatility_stop)
            invalidation = stop
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
                "donchian_high": features.donchian_high,
                "donchian_low": features.donchian_low,
                "channel_width_bps": features.channel_width_bps,
                "channel_width_percentile": features.channel_width_percentile,
                "atr_bps": features.atr_bps,
                "atr_percentile": features.atr_percentile,
                "range_expansion_ratio": features.range_expansion_ratio,
                "volume_expansion_ratio": features.volume_expansion_ratio,
                "inside_bar_fraction": features.inside_bar_fraction,
                "declining_range_persistence": features.declining_range_persistence,
                "breakout_distance_bps": breakout_distance_bps,
                "cold_start": is_cold_start,
            },
            reason_codes=("BREAKOUT_CANDIDATE_ADMITTED",),
            evidence_only=True,
        ))

    return signals
