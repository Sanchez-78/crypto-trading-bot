"""
monte_council.py — 3-lane Monte Carlo survival + Council environmental confidence.

Ported from: Mammon/Left_Hemisphere/Monte_Carlo + Mammon/Cerebellum/council
Adapted for CryptoMaster's tick-driven, multi-symbol architecture.

Monte Carlo (3-lane survival):
  worst   lane — 2.0× noise scale  (pessimistic)
  neutral lane — 1.0× noise scale  (baseline)
  best    lane — 0.5× noise scale  (optimistic)
  score   = w_worst×worst + w_neutral×neutral + w_best×best

Council (environmental confidence):
  Weighted ATR + ADX + Volume + Spread scoring → single [0, 1]

Combined gate:
  combined = sqrt(monte × council)
  inhibit  = combined < COMBINED_BLOCK   → hard inhibit (no trade)
  soft     = combined < COMBINED_SOFT    → auditor_factor × 0.75

Regime → ADX proxy:
  BULL_TREND / BEAR_TREND  → 40
  RANGING                  → 18
  QUIET_RANGE              → 10
  HIGH_VOL                 → 28
  default                  → 25
"""

from __future__ import annotations

import numpy as np
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── Monte Carlo weights & settings ────────────────────────────────────────────
_MC_W_WORST      = 0.20
_MC_W_NEUTRAL    = 0.35
_MC_W_BEST       = 0.45
_MC_NOISE_SCALAR = 0.30          # fraction of ATR as 1-sigma noise (baseline lane)
_MC_PATHS        = 333           # per lane  (999 total — fast, numpy-only)

# ── Council weights ────────────────────────────────────────────────────────────
_C_W_ATR    = 0.15
_C_W_ADX    = 0.40
_C_W_VOL    = 0.25
_C_W_SPREAD = 0.20

# ── Gate thresholds ────────────────────────────────────────────────────────────
MONTE_GATE      = 0.42           # below this → flag MONTE_LOW
COUNCIL_GATE    = 0.35           # below this → flag COUNCIL_LOW
COMBINED_SOFT   = 0.38           # auditor_factor × 0.75  (soft penalty)
COMBINED_BLOCK  = 0.28           # hard inhibit — do not open position

# ── Regime → approximate ADX ─────────────────────────────────────────────────
_REGIME_ADX: dict[str, float] = {
    "BULL_TREND":  40.0,
    "BEAR_TREND":  40.0,
    "TRENDING":    35.0,
    "RANGING":     18.0,
    "QUIET_RANGE": 10.0,
    "HIGH_VOL":    28.0,
    "CHOP":        15.0,
}


# ── Monte Carlo ────────────────────────────────────────────────────────────────

def monte_survival(
    price: float,
    atr: float,
    mu_bias: float = 0.0,
    sigma_mult: float = 1.0,
    noise_scalar: float = _MC_NOISE_SCALAR,
    paths: int = _MC_PATHS,
    seed: Optional[int] = None,
) -> dict:
    """3-lane Monte Carlo survival score.

    Survival = fraction of simulated paths where final_price > entry_price.

    Parameters
    ----------
    price        : current entry price
    atr          : ATR (absolute)
    mu_bias      : directional drift; positive = bullish tilt
    sigma_mult   : overall volatility multiplier  (1.0 = regime-neutral)
    noise_scalar : ATR fraction per 1-sigma step
    paths        : simulations per lane
    seed         : optional RNG seed for determinism

    Returns
    -------
    dict — worst, neutral, best survival rates + weighted score [0, 1]
    """
    if price <= 0 or atr <= 0:
        return {"worst": 0.5, "neutral": 0.5, "best": 0.5, "score": 0.5}

    rng   = np.random.default_rng(seed)
    sigma = atr * noise_scalar * max(sigma_mult, 0.1)

    def _lane(scale: float) -> float:
        finals = price + rng.normal(mu_bias, sigma * scale, paths)
        return float(np.mean(finals > price))

    worst   = _lane(2.0)
    neutral = _lane(1.0)
    best    = _lane(0.5)
    score   = _MC_W_WORST * worst + _MC_W_NEUTRAL * neutral + _MC_W_BEST * best

    return {
        "worst":   round(worst,   4),
        "neutral": round(neutral, 4),
        "best":    round(best,    4),
        "score":   round(score,   4),
    }


# ── Council ────────────────────────────────────────────────────────────────────

def council_confidence(
    atr_ratio: float,       # atr / atr_avg  (>1.0 = elevated vol)
    adx: float,             # ADX 0-100; or use _REGIME_ADX proxy
    volume_ratio: float,    # volume / vol_avg
    spread_bps: float = 0,  # bid-ask spread in basis points
    atr_bps: float   = 50,  # ATR in bps (for spread normalisation)
) -> float:
    """Weighted environmental confidence score [0, 1].

    Sub-scores (each clamped [0, 1]):
      ATR_score    = clamp(atr_ratio − 0.5, 0, 1)          [w = 0.15]
      ADX_score    = clamp(adx / 50.0,      0, 1)           [w = 0.40]
      Volume_score = clamp(vol_ratio / 2.0, 0, 1)           [w = 0.25]
      Spread_score = 1 − clamp(spread_bps / atr_bps, 0, 1) [w = 0.20]

    Returns weighted mean normalised by total weight sum.
    """
    def _clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    atr_s    = _clamp(atr_ratio - 0.5)
    adx_s    = _clamp(adx / 50.0)
    vol_s    = _clamp(volume_ratio / 2.0)
    spread_s = 1.0 - _clamp(spread_bps / max(atr_bps, 1.0))

    total_w = _C_W_ATR + _C_W_ADX + _C_W_VOL + _C_W_SPREAD
    score = (
        _C_W_ATR    * atr_s  +
        _C_W_ADX    * adx_s  +
        _C_W_VOL    * vol_s  +
        _C_W_SPREAD * spread_s
    ) / total_w

    return round(score, 4)


# ── Combined gate ──────────────────────────────────────────────────────────────

def monte_council_gate(
    price: float,
    atr: float,
    regime: str       = "RANGING",
    atr_avg: float    = 0.0,
    volume_ratio: float = 1.0,
    spread_bps: float  = 0.0,
    mu_bias: float     = 0.0,
) -> dict:
    """Combined Monte Carlo + Council environmental gate.

    Derives ADX from regime string when no explicit ADX is available.
    Uses geometric mean to penalise any single badly-scoring dimension.

    Returns
    -------
    dict:
      monte_score   : float [0, 1]
      council_score : float [0, 1]
      combined      : float [0, 1]  geometric mean
      inhibit       : bool   — combined < COMBINED_BLOCK  → hard block
      soft_penalty  : bool   — combined < COMBINED_SOFT   → auditor × 0.75
      af_mult       : float  — auditor_factor multiplier to apply (0.75 or 1.0)
      reason        : str
    """
    atr_ratio = (atr / atr_avg) if atr_avg > 0 else 1.0
    atr_bps   = (atr / price * 10_000) if price > 0 else 50.0
    adx       = _REGIME_ADX.get(regime, 25.0)

    mc       = monte_survival(price, atr, mu_bias=mu_bias)
    mc_score = mc["score"]

    council  = council_confidence(
        atr_ratio    = atr_ratio,
        adx          = adx,
        volume_ratio = volume_ratio,
        spread_bps   = spread_bps,
        atr_bps      = atr_bps,
    )

    # Geometric mean — equally penalises weak Monte OR weak Council
    combined = float(np.sqrt(max(mc_score, 1e-9) * max(council, 1e-9)))

    inhibit      = combined < COMBINED_BLOCK
    soft_penalty = combined < COMBINED_SOFT
    af_mult      = 0.75 if (soft_penalty and not inhibit) else 1.0

    reason = "OK"
    if inhibit:
        reason = "INHIBIT_COMBINED"
    elif soft_penalty:
        if mc_score < MONTE_GATE:
            reason = "SOFT_MONTE_LOW"
        elif council < COUNCIL_GATE:
            reason = "SOFT_COUNCIL_LOW"
        else:
            reason = "SOFT_COMBINED"

    return {
        "monte_score":   round(mc_score, 4),
        "council_score": round(council,  4),
        "combined":      round(combined, 4),
        "inhibit":       inhibit,
        "soft_penalty":  soft_penalty,
        "af_mult":       af_mult,
        "reason":        reason,
    }
