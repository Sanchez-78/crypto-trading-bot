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
