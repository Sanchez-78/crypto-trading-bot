"""
Real-time learning quality, convergence, and model health monitor.

Tracks per (sym, reg) pair:
  EV trend       — risk_ev sampled on every trade close
  WR trend       — rolling empirical win rate
  PnL history    — raw closed-trade pnl
  Bandit score   — UCB1 focus per pair
  Feature WR     — per-feature win rate (requires ≥10 samples)

Convergence:
  lm_convergence = 1 - (std of last 10 EVs) / (std of all EVs)
  → 1.0 = fully stable, 0.0 = still noisy

Health score:
  mean over all pairs with ≥20 trades of: convergence × max(EV, 0)

Alerts:
  health < 0.10 → BAD   (no learning detected)
  health < 0.30 → WEAK  (edge is thin)
  else          → GOOD
"""

import numpy as np

from src.services.execution import risk_ev, bandit_score

# ── Per-(sym, reg) state ───────────────────────────────────────────────────────

lm_ev_hist:      dict = {}   # (sym, reg) → [ev_t, ...]       (last 200)
lm_wr_hist:      dict = {}   # (sym, reg) → [rolling_wr, ...] (last 200)
lm_pnl_hist:     dict = {}   # (sym, reg) → [pnl, ...]        (last 200)
lm_count:        dict = {}   # (sym, reg) → int
lm_bandit_hist:  dict = {}   # (sym, reg) → [ucb_score, ...]  (last 200)
lm_feature_stats: dict = {}  # feature_name → [wins, total]

_HIST_CAP = 200


def _cap(lst):
    if len(lst) > _HIST_CAP:
        del lst[:-_HIST_CAP]


# ── Update hook — call on every trade close ────────────────────────────────────

def lm_update(sym, reg, pnl, ws, features):
    """
    Record one closed trade.
    sym:      symbol string ("BTCUSDT")
    reg:      regime string ("RANGING")
    pnl:      realised profit/loss (float)
    ws:       win-score at entry (float)
    features: dict of signal features (may be empty)
    """
    key = (sym, reg)

    # Trade count
    lm_count[key] = lm_count.get(key, 0) + 1

    # PnL history
    pnl_lst = lm_pnl_hist.setdefault(key, [])
    pnl_lst.append(float(pnl))
    _cap(pnl_lst)

    # Rolling win rate
    wins  = sum(1 for x in pnl_lst if x > 0)
    total = len(pnl_lst)
    wr    = wins / total
    wr_lst = lm_wr_hist.setdefault(key, [])
    wr_lst.append(wr)
    _cap(wr_lst)

    # EV snapshot
    ev = risk_ev(sym, reg)
    ev_lst = lm_ev_hist.setdefault(key, [])
    ev_lst.append(ev)
    _cap(ev_lst)

    # Bandit UCB snapshot
    b = bandit_score(sym, reg)
    b_lst = lm_bandit_hist.setdefault(key, [])
    b_lst.append(b)
    _cap(b_lst)

    # Feature win rates (key = feature name)
    win_flag = 1 if pnl > 0 else 0
    for fname in features:
        w, t = lm_feature_stats.get(fname, (0, 0))
        lm_feature_stats[fname] = (w + win_flag, t + 1)


# ── Convergence & edge metrics ─────────────────────────────────────────────────

def lm_convergence(sym, reg):
    """
    Variance-collapse convergence score ∈ [0, 1].
    Compares std of last 10 EV samples vs std of all samples.
    Returns 0 when fewer than 20 samples available.
    """
    evs = lm_ev_hist.get((sym, reg), [])
    if len(evs) < 20:
        return 0.0
    recent = float(np.std(evs[-10:]))
    long   = float(np.std(evs))
    return max(0.0, 1.0 - recent / (long + 1e-6))


def lm_edge_strength(sym, reg):
    """Current smoothed EV for this (sym, reg) pair."""
    return risk_ev(sym, reg)


def lm_bandit_focus(sym, reg):
    """Mean UCB score over last 10 bandit observations. 0 if insufficient data."""
    b = lm_bandit_hist.get((sym, reg), [])
    if len(b) < 10:
        return 0.0
    return float(np.mean(b[-10:]))


def lm_feature_quality():
    """
    Per-feature empirical win rate.
    Only returns features with ≥10 trades.
    Returns dict: {feature_name: win_rate}.
    """
    out = {}
    for fname, (w, t) in lm_feature_stats.items():
        if t < 10:
            continue
        out[fname] = w / t
    return out


# ── Global health score ────────────────────────────────────────────────────────

def lm_health():
    """
    Mean of (convergence × max(EV, 0)) across pairs with ≥20 trades.
    0.0 when no pair has enough data.
    """
    scores = []
    for (sym, reg), n in lm_count.items():
        if n < 20:
            continue
        conv = lm_convergence(sym, reg)
        ev   = lm_edge_strength(sym, reg)
        scores.append(conv * max(ev, 0.0))
    if not scores:
        return 0.0
    return float(np.mean(scores))


# ── Alerts ────────────────────────────────────────────────────────────────────

def lm_alerts():
    """
    Returns "BAD" / "WEAK" / "GOOD" and prints a warning when degraded.
    BAD:  health < 0.10 — no measurable learning signal
    WEAK: health < 0.30 — edge is thin, needs more data
    GOOD: system is converging with positive edge
    """
    h = lm_health()
    if h < 0.10:
        print("  [!] LEARNING: NO LEARNING SIGNAL DETECTED")
        return "BAD"
    if h < 0.30:
        print("  [!] LEARNING: WEAK EDGE -- still converging")
        return "WEAK"
    return "GOOD"


# ── Text monitor ──────────────────────────────────────────────────────────────

def print_learning_monitor():
    """
    Prints a compact learning monitor to stdout.
    Shown automatically in the bot2 main loop alongside print_status().
    """
    print("\n=== LEARNING MONITOR ===")

    any_pair = False
    for (sym, reg), n in sorted(lm_count.items()):
        if n < 10:
            continue
        any_pair = True
        conv = lm_convergence(sym, reg)
        ev   = lm_edge_strength(sym, reg)
        band = lm_bandit_focus(sym, reg)
        wr_lst = lm_wr_hist.get((sym, reg), [])
        wr     = wr_lst[-1] if wr_lst else 0.0
        short  = sym.replace("USDT", "")
        conv_tag = (f"conv:{conv:.2f}" if n >= 20
                    else f"conv:-- ({n}/20)")
        print(f"  {short:<4} {reg:<10}  n:{n:<4}  "
              f"EV:{ev:+.3f}  WR:{wr:.0%}  "
              f"{conv_tag}  bandit:{band:.2f}")

    if not any_pair:
        print("  (waiting for 10 closed trades per pair)")

    fq = lm_feature_quality()
    if fq:
        print("\n  Features (WR per signal key):")
        for fname, wr in sorted(fq.items(), key=lambda x: -x[1])[:10]:
            bar_w = 12
            filled = int(bar_w * wr)
            bar = "#" * filled + "-" * (bar_w - filled)
            tag = "+" if wr >= 0.55 else ("~" if wr >= 0.45 else "-")
            print(f"    {fname:<20}  [{bar}]  {wr:.0%}  {tag}")

    h = lm_health()
    alert = lm_alerts()
    print(f"\n  Health: {h:.3f}  [{alert}]")
    print("=" * 24)
