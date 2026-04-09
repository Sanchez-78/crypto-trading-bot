"""
signal_coherence.py — Signal Quality / Coherence Scorer (V10.12)

Provides a continuous quality score [0.5, 1.0] that measures the INTERNAL
CONSISTENCY of each signal's indicators. This complements the binary gates
in realtime_decision_engine.py: instead of blocking, coherence modulates EV.

Integration point (realtime_decision_engine.evaluate_signal):
  After EV computation, before the allow_trade() gate:
    _coh = coherence_score(signal)
    ev   = ev * max(0.6, _coh)         # floor at 0.6: never fully mutes EV
    signal["coherence"] = round(_coh, 4)

Four independent dimensions:

1. Regime-Feature Alignment (40% weight):
   Are the active boolean features appropriate for the detected regime?
   In BULL_TREND: "trend", "mom", "pullback" carry most informational weight.
   In RANGING: "bounce", "wick" are the primary mean-reversion signals.
   In HIGH_VOL: "breakout", "vol" dominate.
   A counter-regime feature mix doesn't block — it reduces EV contribution.

2. Momentum Coherence (35% weight):
   Do continuous momentum indicators (mom5, mom10, OBI z-score, rsi_slope,
   ema_diff) point in the same direction as the signal action?
   Each indicator is checked independently; the fraction in agreement is
   the score. Only indicators with meaningful absolute value are included
   (zero-valued = missing data → dropped, not counted as disagreement).
   Research (Chan 2013; Jansen 2020): momentum alignment at short horizons
   reduces adverse excursion probability by ~12-18%.

3. Indicator Agreement (15% weight):
   Fraction of 7 boolean edge features that are True.
   Breadth of independent confirmation — a signal with 6/7 features true
   has more convergent evidence than one with 3/7.
   Note: this dimension is INDEPENDENT of regime-feature alignment —
   it measures quantity, not quality-adjusted fit.

4. Price Z-Score Quality (10% weight):
   In RANGING / QUIET_RANGE regimes: price Z-score alignment with signal
   direction. BUY with z ≤ -1.5 (oversold deviation) → maximum score.
   In trend regimes: neutral 0.5 (Z-score less predictive in momentum).
   Research (Avellaneda & Lee 2010): |z| > 1.5 = statistically actionable
   mean-reversion opportunity.

Output ranges:
  Strong confirmed signal:   0.80 – 0.95
  Average quality signal:    0.62 – 0.78
  Weak / contradictory:      0.50 – 0.62

Floor at 0.50: even a maximally incoherent signal retains 50% EV credit.
Ceiling at 1.0: perfect coherence does not boost EV beyond what the gate
already computed.
"""

# ── Regime-feature alignment weights ──────────────────────────────────────────
# Higher weight = more confirmatory in this regime.
# Relative weights; normalization happens in regime_feature_alignment().

_REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "BULL_TREND": {
        "trend":    2.0,   # EMA cross = primary trend confirmation
        "pullback": 1.5,   # price retreated to entry zone = low-risk add
        "bounce":   1.5,   # price recovering from pullback
        "breakout": 1.0,   # directional break confirms momentum
        "vol":      0.8,   # volume expansion supportive but not required
        "mom":      1.8,   # momentum alignment critical in trend context
        "wick":     0.5,   # wick less informative in trending markets
    },
    "BEAR_TREND": {
        "trend":    2.0,
        "pullback": 1.5,
        "bounce":   1.5,
        "breakout": 1.0,
        "vol":      0.8,
        "mom":      1.8,
        "wick":     0.5,
    },
    "RANGING": {
        "trend":    0.4,   # trend features noisy in range — low weight
        "pullback": 0.8,
        "bounce":   2.0,   # bounce off range boundary = primary signal
        "breakout": 0.2,   # breakouts in range are often fakeouts
        "vol":      0.5,
        "mom":      1.5,   # momentum still relevant for entry timing
        "wick":     1.8,   # wick rejection confirms range boundary
    },
    "QUIET_RANGE": {
        "trend":    0.3,
        "pullback": 0.5,
        "bounce":   2.2,   # bounce is the dominant signal in dead markets
        "breakout": 0.1,   # almost never meaningful in QUIET_RANGE
        "vol":      0.3,
        "mom":      1.5,
        "wick":     2.0,   # wick rejection is the clearest signal here
    },
    "HIGH_VOL": {
        "trend":    0.8,
        "pullback": 0.8,
        "bounce":   0.8,
        "breakout": 2.0,   # vol expansion + directional break = core signal
        "vol":      2.0,   # vol itself is the regime signal
        "mom":      1.0,
        "wick":     0.4,   # wicks are noise in HIGH_VOL
    },
}

_DEFAULT_WEIGHTS: dict[str, float] = {k: 1.0 for k in
    ["trend", "pullback", "bounce", "breakout", "vol", "mom", "wick"]}

_BOOL_FEATURE_KEYS = ("trend", "pullback", "bounce", "breakout", "vol", "mom", "wick")


# ── Feature extraction ─────────────────────────────────────────────────────────

def _bool_features(signal: dict) -> dict[str, bool]:
    """Extract 7 canonical boolean edge features from signal safely."""
    raw = signal.get("features", {})
    return {k: bool(raw.get(k, False)) for k in _BOOL_FEATURE_KEYS if k in raw}


def _cont_features(signal: dict) -> dict[str, float]:
    """Extract continuous momentum indicators from signal, defaulting to 0."""
    raw = signal.get("features", {})
    return {
        "mom5":      float(raw.get("mom5",      0.0) or 0.0),
        "mom10":     float(raw.get("mom10",     0.0) or 0.0),
        "obi":       float(raw.get("obi",       0.0) or 0.0),
        "rsi_slope": float(raw.get("rsi_slope", 0.0) or 0.0),
        "ema_diff":  float(raw.get("ema_diff",  0.0) or 0.0),
    }


# ── Dimension scorers ─────────────────────────────────────────────────────────

def regime_feature_alignment(signal: dict) -> float:
    """
    Score [0, 1]: weighted fraction of active features that are confirmatory
    for the detected regime.

    weighted_active   = Σ_{f where f is True} regime_weight[f]
    weighted_possible = Σ_f  regime_weight[f]
    score             = weighted_active / weighted_possible

    Returns 0.5 when no boolean features are available (missing data → neutral).
    """
    regime   = signal.get("regime", "RANGING")
    features = _bool_features(signal)
    weights  = _REGIME_WEIGHTS.get(regime, _DEFAULT_WEIGHTS)

    if not features:
        return 0.5

    w_active   = sum(weights.get(f, 1.0) for f, v in features.items() if v)
    w_possible = sum(weights.values())

    return w_active / max(w_possible, 1e-9)


def momentum_coherence(signal: dict) -> float:
    """
    Score [0, 1]: fraction of continuous momentum indicators aligned with
    the signal's action direction.

    Indicators:
      mom5       — 5-tick price momentum
      mom10      — 10-tick price momentum
      obi        — OBI z-score (>+0.15 = meaningful bid pressure)
      rsi_slope  — RSI direction (>0.01 = rising)
      ema_diff   — EMA10 − EMA50 (>1e-8 = uptrend)

    For BUY: positive indicator = agreement.
    For SELL: negative indicator = agreement.

    Only indicators with meaningful absolute values are included.
    Zero-valued indicators are treated as missing (excluded from denominator).
    Returns 0.5 when no valid indicators are available (neutral, not penalizing).
    """
    action = signal.get("action", "BUY")
    cont   = _cont_features(signal)
    sign   = 1 if action == "BUY" else -1

    # (value, minimum_abs_to_count_as_meaningful)
    indicator_specs = [
        ("mom5",      1e-9),
        ("mom10",     1e-9),
        ("obi",       0.15),    # OBI z-score threshold for meaningful imbalance
        ("rsi_slope", 0.01),    # RSI must change by at least 0.01 to be meaningful
        ("ema_diff",  1e-8),
    ]

    checks = []
    for key, threshold in indicator_specs:
        val = cont.get(key, 0.0)
        if abs(val) >= threshold:
            checks.append(val * sign > 0)

    if not checks:
        return 0.5

    return sum(checks) / len(checks)


def indicator_agreement(signal: dict) -> float:
    """
    Score [0, 1]: fraction of 7 boolean edge features that are True.

    Measures breadth of independent confirmation, not regime fit.
    All 7 features active → 1.0 (maximum independent confirmation).
    3/7 True (SCORE_MIN gate floor) → 0.43 (minimum realistic case).
    Returns 0.5 when no boolean features are present.
    """
    features = _bool_features(signal)
    if not features:
        return 0.5

    n_active = sum(1 for v in features.values() if v)
    return n_active / max(len(features), 1)


def price_z_quality(signal: dict) -> float:
    """
    Score [0.25, 1.0]: price Z-score alignment bonus for RANGING regimes.

    Only meaningful in RANGING / QUIET_RANGE where price deviation from
    the rolling mean is the primary edge signal.

    BUY with z ≤ -1.5 (large negative deviation, price oversold) → 1.0
    BUY with z ≤ -1.0 → 0.75
    BUY with z ≥ +1.0 (buying into overbought range) → 0.25 (penalized)

    SELL mirror image.
    In trend regimes: neutral 0.5 (Z-score less informative in momentum).
    """
    regime = signal.get("regime", "RANGING")
    if regime not in ("RANGING", "QUIET_RANGE"):
        return 0.5

    action  = signal.get("action", "BUY")
    price_z = float(signal.get("features", {}).get("price_z", 0.0) or 0.0)

    if action == "BUY":
        if price_z <= -1.5:  return 1.00
        if price_z <= -1.0:  return 0.75
        if price_z >= +1.0:  return 0.25   # buying into overbought range
    else:   # SELL
        if price_z >= +1.5:  return 1.00
        if price_z >= +1.0:  return 0.75
        if price_z <= -1.0:  return 0.25   # selling into oversold range

    return 0.50   # price near mean — no strong Z-signal


# ── Composite scorer ──────────────────────────────────────────────────────────

def coherence_score(signal: dict) -> float:
    """
    Composite signal quality score [0.5, 1.0].

    Weighted combination of four independent dimensions:
      40% — regime_feature_alignment : features right for this regime?
      35% — momentum_coherence       : continuous indicators agree?
      15% — indicator_agreement      : how many features fired?
      10% — price_z_quality          : Z-score fits action? (RANGING only)

    Floor at 0.50 — even the worst coherent signal retains half EV credit.
    EV gate (allow_trade) is the final arbiter of signal quality;
    coherence just provides a continuous quality gradient within passing signals.

    Typical score ranges at evaluate_signal integration:
      Weak / contradictory signals:   0.50–0.62  → EV ×0.60–0.62
      Average signals:                0.63–0.78  → EV ×0.63–0.78
      Strong confirmed signals:       0.79–0.95  → EV ×0.79–0.95
    """
    rfa = regime_feature_alignment(signal)
    mc  = momentum_coherence(signal)
    ia  = indicator_agreement(signal)
    pzq = price_z_quality(signal)

    score = (
        0.40 * rfa +
        0.35 * mc  +
        0.15 * ia  +
        0.10 * pzq
    )
    return max(0.50, min(1.00, score))
