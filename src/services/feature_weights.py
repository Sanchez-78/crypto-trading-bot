"""
V10.9 Feature Weight Adaptation — deterministic per-feature EV learning.

Tracks how each boolean signal feature (trend, pullback, bounce, breakout, vol,
mom, wick) performs historically per (symbol, regime) pair and adapts its weight
multiplicatively.  Weights start at 1.0 and converge toward features with
above-average EV; poor-performing features are downweighted.

Weight update formula (per feature f):
    ev_avg_f = ev_sum[f] / ev_count[f]            running per-feature average
    alpha    = max(0.01, alpha_base × lm_health × (1 - drawdown))
    w_new    = clamp(w_old × (1 + alpha × (ev_f - ev_avg_f)), 0.5, 1.5)

    ev_f > ev_avg_f  →  weight rises   (feature outperforming its own history)
    ev_f < ev_avg_f  →  weight falls   (feature underperforming)
    alpha shrinks at high drawdown / low lm_health → slower adaptation when struggling
    alpha floor 0.01 prevents weights from completely freezing

Integration points (trade_executor.py):
    handle_signal  — compute_weighted_score gate (blocks trades < MIN_SCORE after bootstrap)
    on_price close — update_feature_weights called with learning_pnl / n_active_features

Bootstrap-safe:
    During cold start (< 30 trades) the score gate is bypassed.
    Until lm_health > 0 the effective alpha ≈ 0.01 (near-frozen, minimal drift).
    All weights start at 1.0 — no feature is favoured before data exists.
"""

# ── Constants ──────────────────────────────────────────────────────────────────

# Feature names exactly as emitted by signal_generator.py (boolean features only)
BASE_WEIGHTS: dict = {
    "trend":    1.0,
    "pullback": 1.0,
    "bounce":   1.0,
    "breakout": 1.0,
    "vol":      1.0,
    "mom":      1.0,
    "wick":     1.0,
}

FEATURES   = list(BASE_WEIGHTS)   # canonical order
N_FEATURES = len(FEATURES)        # 7

WEIGHT_MIN = 0.5    # floor: feature can lose up to half influence
WEIGHT_MAX = 1.5    # ceiling: feature can gain up to 1.5× influence

# Gate threshold: raw weighted sum across binary features (all weights=1 → max score=7)
# MIN_SCORE=3 requires at least 3 active features with baseline weight — fires post-bootstrap.
MIN_SCORE = 3.0

# ── State ─────────────────────────────────────────────────────────────────────

# Per-(symbol, regime) state — in-memory, resets on process restart (stateless design)
_state: dict = {}


def _get_state(sym: str, reg: str) -> dict:
    """Return (create if missing) per-(sym, reg) weight state."""
    key = (sym, reg)
    if key not in _state:
        _state[key] = {
            "weights":  BASE_WEIGHTS.copy(),
            "ev_sum":   {f: 0.0 for f in FEATURES},   # per-feature running sum
            "ev_count": {f: 0   for f in FEATURES},   # per-feature trade count
        }
    return _state[key]


# ── Public API ─────────────────────────────────────────────────────────────────

def update_feature_weights(symbol: str, regime: str, feature_evs: dict,
                           lm_health: float, drawdown: float,
                           alpha_base: float = 0.2) -> dict:
    """Update per-feature weights from a closed position.

    Parameters
    ----------
    symbol      : trading pair (e.g. "BTCUSDT")
    regime      : market regime at open (e.g. "BULL_TREND")
    feature_evs : {feature_name: ev_contribution}
                  Typically: learning_pnl / n_active_features for each active feature;
                  inactive features are omitted (neither rewarded nor penalised).
    lm_health   : [0, 1] system learning quality from learning_monitor.lm_health()
    drawdown    : [0, 1] max drawdown from diagnostics.max_drawdown()
    alpha_base  : base learning rate (default 0.2)

    Returns updated weight dict for the (symbol, regime) pair.
    """
    if not feature_evs:
        return get_weights(symbol, regime)

    state   = _get_state(symbol, regime)
    weights = state["weights"]

    # Alpha shrinks under stress; floor 0.01 prevents complete weight freeze
    alpha = max(0.01, alpha_base * max(lm_health, 0.0) * max(1.0 - drawdown, 0.0))

    for f, ev in feature_evs.items():
        if f not in weights:
            # Unseen feature (e.g. new signal added later) — initialise at neutral
            weights[f]              = 1.0
            state["ev_sum"][f]      = 0.0
            state["ev_count"][f]    = 0

        # Per-feature running mean (fixed: was incorrectly shared across features)
        state["ev_sum"][f]   += ev
        state["ev_count"][f] += 1
        ev_avg_f = state["ev_sum"][f] / state["ev_count"][f]

        # Multiplicative update — moves weight toward features exceeding their own avg
        w_new = weights[f] * (1.0 + alpha * (ev - ev_avg_f))
        weights[f] = max(WEIGHT_MIN, min(WEIGHT_MAX, w_new))

    return dict(weights)


def compute_weighted_score(signal_features: dict, symbol: str, regime: str) -> float:
    """Compute weighted sum of active boolean signal features.

    Parameters
    ----------
    signal_features : {feature_name: bool | float} — subset of signal["features"]
                      Typically: the boolean features extracted via isinstance(v, bool).
    symbol, regime  : for per-(sym, reg) weight lookup.

    Returns raw score = Σ feature_value × weight over FEATURES.

    Interpretation:
      All weights=1.0, 7 features all active  →  7.0   (max at baseline)
      All weights=1.0, 4 features active       →  4.0   (typical passing trade)
      All weights=1.0, 2 features active       →  2.0   (below MIN_SCORE=3.0 → blocked)
      After adaptation, well-performing features raise the score above raw count.
    """
    weights = _get_state(symbol, regime)["weights"]
    return sum(
        float(signal_features.get(f, 0)) * weights.get(f, 1.0)
        for f in FEATURES
    )


def get_weights(symbol: str, regime: str) -> dict:
    """Return a copy of current weights for a (symbol, regime) pair."""
    return dict(_get_state(symbol, regime)["weights"])
