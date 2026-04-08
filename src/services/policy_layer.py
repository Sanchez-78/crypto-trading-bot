"""
V10.7 Policy Layer — meta-adaptive EV multiplier.

policy_multiplier combines four context signals into a single scaling factor
centered at 1.0, clamped [0.5, 1.5]:

  meta_mode        aggressive=+0.15, neutral=0.0, defensive=-0.20
  regime_alignment [0,1] centered at 0.5 → contribution ±0.10
  confidence       [0,1] centered at 0.5 → contribution ±0.075
  recent_winrate   [0,1] centered at 0.5 → contribution ±0.10

policy_ev = risk_ev × policy_multiplier

Bootstrap-safe: all inputs at neutral defaults (mode=neutral, alignment=0.5,
confidence=0.5, winrate=0.5) → pm = 1.0, policy_ev = risk_ev (no change).
"""


def policy_multiplier(meta_mode: str, regime_alignment: float,
                      confidence: float, recent_winrate: float) -> float:
    """Compute policy scaling multiplier [0.5, 1.5].

    All contributions are additive around 1.0:
      mode_contrib:   aggressive=+0.15, neutral=0.0, defensive=-0.20
      align_contrib:  [0,1] centered at 0.5 → [-0.10, +0.10]
      conf_contrib:   [0,1] centered at 0.5 → [-0.075, +0.075]
      wr_contrib:     [0,1] centered at 0.5 → [-0.10, +0.10]

    Extreme case (aggressive, aligned, conf=1, wr=0.8): ≈1.40 → capped 1.5.
    Extreme case (defensive, counter, conf=0, wr=0.3): ≈0.54 → capped 0.5.
    """
    mode_contrib = {"aggressive": 0.15, "neutral": 0.0, "defensive": -0.20}.get(meta_mode, 0.0)
    align_contrib = 0.20 * (max(0.0, min(1.0, regime_alignment)) - 0.5)
    conf_contrib  = 0.15 * (max(0.0, min(1.0, confidence))       - 0.5)
    wr_contrib    = 0.20 * (max(0.0, min(1.0, recent_winrate))   - 0.5)
    pm = 1.0 + mode_contrib + align_contrib + conf_contrib + wr_contrib
    return max(0.5, min(1.5, pm))


def compute_policy_ev(risk_ev_val: float, meta_mode: str, regime_alignment: float,
                      confidence: float, recent_winrate: float):
    """Return (policy_ev, policy_multiplier_val).

    policy_ev = risk_ev × policy_multiplier
    At risk_ev=0 (bootstrap): policy_ev=0, pm is still computed for logging.
    """
    pm = policy_multiplier(meta_mode, regime_alignment, confidence, recent_winrate)
    return risk_ev_val * pm, pm


# ── V10.8 helpers ──────────────────────────────────────────────────────────────

def adaptive_max_pos(base_size: float, meta_mode: str, predicted_regime: str) -> float:
    """Return the maximum allowed position size given system health and predicted regime.

    defensive OR predicted HIGH_VOL → cap at 0.70 × base_size (risk-off)
    aggressive AND predicted trend   → cap at 1.30 × base_size (risk-on)
    else                             → base_size unchanged

    Applied as a hard cap — all upstream sizing (Kelly, meta, regime penalty)
    is preserved; this only prevents the final size from exceeding the ceiling.
    """
    if meta_mode == "defensive" or predicted_regime == "HIGH_VOL":
        return base_size * 0.70
    if meta_mode == "aggressive" and predicted_regime in ("BULL_TREND", "BEAR_TREND"):
        return base_size * 1.30
    return base_size


def scaled_partial_tp(base_mult: float, policy_mult: float) -> float:
    """Return the ATR multiplier at which partial TP fires, scaled by policy state.

    base_mult = 1.5 (current system default: exit 50% at 1.5×ATR profit).

    Higher policy_mult (aggressive/healthy) → fires later → let winners run more.
    Lower  policy_mult (defensive/poor)     → fires earlier → lock gains sooner.

    Clamp [1.0, 2.5]: never below 1×ATR (covers fees) or above 2.5×ATR (unreachable).
    """
    return max(1.0, min(2.5, base_mult * policy_mult))
