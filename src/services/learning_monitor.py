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

from src.services.execution import bandit_score

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


def true_ev(sym, reg):
    """Bounded Sharpe-EV via tanh: tanh(mean / max(std, 0.002)).
    Output is always in (-1, +1) — eliminates spikes from near-zero std.
    std floor 0.002 prevents division explosion on perfectly consistent
    streaks (e.g. 5 identical small wins → std≈0 → raw ratio → ±∞).
    Returns 0.0 until at least 10 samples are available.
    """
    pnl = lm_pnl_hist.get((sym, reg), [])
    if len(pnl) < 10:
        return 0.0
    arr  = pnl[-20:]
    std  = max(float(np.std(arr)), 0.002)
    return float(np.tanh(float(np.mean(arr)) / std))


def conf_ev(sym, reg):
    """Confidence-weighted EV: true_ev × min(n/50, 1).
    Pairs with fewer than 50 trades are linearly suppressed — a pair with
    10 trades contributes 20% of its EV to allocation; at 50+ trades it
    receives full weight. Prevents new pairs from dominating on tiny samples.
    """
    n    = lm_count.get((sym, reg), 0)
    conf = min(n / 50.0, 1.0)
    return true_ev(sym, reg) * conf


def record_features(features, pnl):
    """Fractional feature attribution: each active feature receives 1/N credit
    instead of a full binary win. With N features per signal, each gets equal
    share — prevents high-frequency features from dominating WR stats simply
    because they co-occur with many others.
    win/t remains in [0, 1] so lm_feature_quality() percentages are unchanged.
    """
    if not features:
        return
    credit = 1.0 / len(features)
    win = 1 if pnl > 0 else 0
    for f in features:
        w, t = lm_feature_stats.get(f, (0.0, 0.0))
        lm_feature_stats[f] = (w + win * credit, t + credit)


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

    # EV snapshot — PnL-based, not time-decayed Sharpe blend
    ev = true_ev(sym, reg)
    ev_lst = lm_ev_hist.setdefault(key, [])
    ev_lst.append(ev)
    _cap(ev_lst)

    # Bandit UCB snapshot
    b = bandit_score(sym, reg)
    b_lst = lm_bandit_hist.setdefault(key, [])
    b_lst.append(b)
    _cap(b_lst)

    # Feature win rates — direct update, no soft sampling
    record_features(features, pnl)


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
    """Current PnL-based EV for this (sym, reg) pair."""
    return true_ev(sym, reg)


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


# ── Force-mode and toxic-reset ────────────────────────────────────────────────

def force_mode():
    """True when fewer than 50 total PnL observations exist across all pairs.
    Below this threshold EV estimates are unreliable — EV gates are disabled
    and only ws > 0.30 is required so data can flow in unconditionally.
    """
    total = sum(len(v) for v in lm_pnl_hist.values())
    return total < 50


def reset_if_toxic():
    """Disabled — reset loop was blocking data flow. No-op."""
    return


# ── Global health score ────────────────────────────────────────────────────────

def lm_health():
    """
    Mean of (convergence × max(EV, 0)) across pairs with ≥10 trades.
    0.0 when no pair has enough data.
    Threshold lowered 20→10: with 3 symbols in slow markets,
    accumulating 20 in-session trades per pair can take hours.
    """
    scores = []
    for (sym, reg), n in lm_count.items():
        if n < 10:
            continue
        conv = lm_convergence(sym, reg)
        ev   = lm_edge_strength(sym, reg)
        scores.append(conv * max(ev, 0.0))
    if not scores:
        return 0.0
    return float(np.mean(scores))


# ── Meta state + adaptive control ────────────────────────────────────────────

meta: dict = {
    "ws_mult":    1.0,   # WS threshold multiplier  (< 1 loosens, > 1 tightens)
    "risk_mult":  1.0,   # position size risk scaler
    "alloc_mult": 1.0,   # allocation scaler
}


def meta_update():
    """
    Adjust meta multipliers from live system signals. Call every loop tick.

    Frozen at 1.0 during bootstrap (<100 trades) to prevent meta from
    suppressing early learning before sufficient data exists.

    learning quality (lm_health):
      < 0.20 → loosen threshold + shrink allocation (system still learning)
      > 0.40 → tighten threshold + expand allocation (edge confirmed)
      else   → reset to neutral 1.0

    performance (Sharpe from equity curve):
      > 1.5  → raise risk_mult (strong positive drift)
      < 0.5  → lower risk_mult (weak / negative drift)
      else   → reset to 1.0

    drawdown (peak DD from equity curve):
      > 0.10 → risk_mult 0.6 override (takes precedence over Sharpe boost)
    """
    try:
        from src.services.execution import is_bootstrap
        if is_bootstrap():
            meta["ws_mult"]    = 1.0
            meta["risk_mult"]  = 1.0
            meta["alloc_mult"] = 1.0
            return
    except Exception:
        pass

    h  = lm_health()
    try:
        from src.services.diagnostics import sharpe as _sharpe, max_drawdown as _dd
        sr = _sharpe()
        dd = _dd()
    except Exception:
        sr = 0.0
        dd = 0.0

    # Learning quality gate (softened — less aggressive suppression/expansion)
    if h < 0.20:
        meta["ws_mult"]    = 0.95
        meta["alloc_mult"] = 0.90
    elif h > 0.40:
        meta["ws_mult"]    = 1.05
        meta["alloc_mult"] = 1.05
    else:
        meta["ws_mult"]    = 1.0
        meta["alloc_mult"] = 1.0

    # Performance gate (softened)
    if sr > 1.5:
        meta["risk_mult"] = 1.05
    elif sr < 0.5:
        meta["risk_mult"] = 0.90
    else:
        meta["risk_mult"] = 1.0

    # Drawdown override — takes precedence over Sharpe boost
    if dd > 0.10:
        meta["risk_mult"] = 0.60


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


# ── Firestore-serialisable snapshot ──────────────────────────────────────────

def lm_snapshot():
    """
    Return a JSON-serialisable dict suitable for embedding in metrics/latest.
    Called from bot2/main.py alongside execution_data, no extra Firestore writes.
    Shape:
      {
        health:   float,
        alert:    "GOOD"|"WEAK"|"BAD",
        mode:     "COLD"|"WARM"|"LIVE",
        pairs: {
          "BTCUSDT_BULL": {sym, reg, n, ev, wr, conv, bandit}
          ...
        },
        features: {feature_name: win_rate, ...}   (>=10 trades, top 10 by WR)
      }
    """
    try:
        from src.services.execution import bootstrap_mode
        mode = bootstrap_mode()
    except Exception:
        mode = "UNKNOWN"

    pairs = {}
    for (sym, reg), n in lm_count.items():
        wr_lst  = lm_wr_hist.get((sym, reg), [])
        ev_lst  = lm_ev_hist.get((sym, reg), [])
        b_lst   = lm_bandit_hist.get((sym, reg), [])
        wr   = round(float(wr_lst[-1]), 4) if wr_lst else 0.0
        ev   = round(float(ev_lst[-1]), 4) if ev_lst else 0.0
        conv = round(lm_convergence(sym, reg), 3)
        band = round(lm_bandit_focus(sym, reg), 3)
        key  = f"{sym}_{reg}"
        pairs[key] = {
            "sym":    sym,
            "reg":    reg,
            "n":      n,
            "ev":     ev,
            "wr":     wr,
            "conv":   conv,
            "bandit": band,
        }

    fq = lm_feature_quality()
    top_features = {
        k: round(v, 4)
        for k, v in sorted(fq.items(), key=lambda x: -x[1])[:10]
    }

    h = lm_health()
    a = lm_alerts()

    return {
        "health":   round(h, 4),
        "alert":    a,
        "mode":     mode,
        "pairs":    pairs,
        "features": top_features,
    }


# ── Text monitor ──────────────────────────────────────────────────────────────

def print_learning_monitor():
    """
    Prints a compact learning monitor to stdout.
    Shown automatically in the bot2 main loop alongside print_status().
    """
    print("\n=== LEARNING MONITOR ===")

    any_pair = False
    for (sym, reg), n in sorted(lm_count.items()):
        if n < 3:
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
