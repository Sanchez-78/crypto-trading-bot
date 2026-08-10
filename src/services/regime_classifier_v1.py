"""Regime classifier for the P0.8+ pipeline (Evidence-First Strategy
Expansion v2 -- informal scope for the live-wiring phase; the document's
§22A "Regime Classifier Governance" section describes a more complete
required-states/online-only/tested contract than this MVP implements,
disclosed as a gap, not silently claimed as satisfied).

Produces exactly the four-value taxonomy every current P0.8+ strategy gates
on: SIDEWAYS, BULL_TREND, BEAR_TREND, VOLATILE (matches
regime_filter.RegimeFilter.allow()'s vocabulary).

This is deliberately a NEW, separate classifier, not a reuse of either
existing regime-shaped function in this repository:

  - signal_generator._regime() (private, five-value taxonomy: HIGH_VOL /
    BULL_TREND / BEAR_TREND / QUIET_RANGE / RANGING) -- a different,
    incompatible vocabulary already serving the OLD live path. Importing a
    private underscore-prefixed function from another module to repurpose
    its taxonomy would be exactly the kind of unverified assumption this
    program's §0.1 forbids, and the taxonomies don't even match.
  - regime_filter.RegimeFilter.allow() -- does not compute a regime, only
    filters a pre-computed one. (Observed in passing: it checks for
    "SIDEWAYS"/"VOLATILE", which signal_generator._regime() never actually
    produces -- an existing inconsistency in the OLD path, out of scope to
    fix here.)

Built from feature_extractor.regime() (EMA50/EMA200 trend direction +
EMA50 slope) and feature_extractor.vol() (ATR), which the P0.8+ strategy
modules already depend on for other features -- reusing that dependency
rather than adding a third indicator library.
"""
from __future__ import annotations

from typing import Mapping, Sequence, Tuple

from src.services import feature_extractor as fx

MIN_CANDLES = 200  # matches feature_extractor.regime()'s own EMA200 floor

# Matches signal_generator._regime()'s own HIGH_VOL threshold (atr_pct >
# 0.012) -- reused for consistency of magnitude even though the two
# functions' surrounding taxonomies differ (see module docstring).
VOLATILE_ATR_PCT_THRESHOLD = 0.012

# Slope as a fraction of price; below this magnitude, EMA50 is not moving
# meaningfully and the market is classified SIDEWAYS regardless of which
# side of EMA200 it happens to sit on.
MIN_TREND_SLOPE_FRACTION = 0.00005


def classify_regime(candles: Sequence[Mapping]) -> Tuple[str, float]:
    """Returns (regime, confidence). confidence in [0,1], diagnostic only
    (never itself an admission input -- same structural rule every P0.8+
    strategy already applies to its own confidence field).

    Fails closed on insufficient warmup: returns ("SIDEWAYS", 0.0) rather
    than raising or fabricating a confident trend classification from too
    little history. SIDEWAYS is deliberately the neutral/no-op regime for
    trend_cost_aware_v1 (rejects both long and short candidates in it) and
    the entry gate for sideways_mean_reversion_v1/volatility_breakout_v1 --
    zero confidence means those two will also correctly reject on the
    regime_confidence floor, so a cold-start candle window cannot silently
    admit anything.
    """
    if len(candles) < MIN_CANDLES:
        return "SIDEWAYS", 0.0

    close = float(candles[-1]["close"])
    if close <= 0:
        return "SIDEWAYS", 0.0

    vol_feats = fx.vol(list(candles))
    atr_pct = vol_feats["atr"] / close
    if atr_pct > VOLATILE_ATR_PCT_THRESHOLD:
        confidence = min(1.0, atr_pct / (VOLATILE_ATR_PCT_THRESHOLD * 2))
        return "VOLATILE", confidence

    regime_feats = fx.regime(list(candles))
    slope_fraction = regime_feats["trend_strength"] / close

    if regime_feats["trend"] == 1 and slope_fraction > MIN_TREND_SLOPE_FRACTION:
        confidence = max(0.5, min(1.0, slope_fraction / (MIN_TREND_SLOPE_FRACTION * 10)))
        return "BULL_TREND", confidence

    if regime_feats["trend"] == 0 and slope_fraction < -MIN_TREND_SLOPE_FRACTION:
        confidence = max(0.5, min(1.0, abs(slope_fraction) / (MIN_TREND_SLOPE_FRACTION * 10)))
        return "BEAR_TREND", confidence

    return "SIDEWAYS", 0.5
