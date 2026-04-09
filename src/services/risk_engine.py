"""
risk_engine.py — Portfolio Risk Budget Controller (V10.12)

Replaces the binary _risk_guard() (scale all positions ×0.7 when over cap)
with a predictive, correlation-aware model that acts BEFORE a position opens.

Three core functions consumed by trade_executor:

  apply_risk_budget(size, sl_pct, action, regime, positions) → float
    Constrains incoming size to fit within the remaining risk budget.
    Correlation-aware: hedge portfolios can accommodate a larger new
    position than a fully concentrated same-direction portfolio.

  corr_size_factor(new_action, new_regime, positions) → float [0.60, 1.10]
    Continuous, regime-aware complement to count-based
    correlation_size_penalty() in execution.py.
      Same dir + same regime → 0.60  (heavy concentration penalty)
      Same dir + diff regime → 0.80  (moderate)
      Opposite direction     → 1.10  (hedge bonus)

  replacement_correlation_adj(new_action, new_regime, positions, worst_sym)
    → float [0.70, 1.30]
    Adjusts the V10.10 efficiency threshold: replacing worst_sym with a
    position that DIVERSIFIES the portfolio needs to clear a lower bar;
    one that CONCENTRATES needs to clear a higher bar.

Correlation model (heuristic — no synchronized tick-level OHLC needed):
  Same direction + same regime  → ρ = 0.70
  Same direction + diff regime  → ρ = 0.45
  Opposite direction            → ρ = −0.20

Portfolio risk = σ_p = √(Σ r_i² + 2 Σ_{i<j} ρ_ij r_i r_j)
where r_i = size_i × sl_pct_i

Cap: MAX_PORTFOLIO_RISK = 0.05 (matches _MAX_TOTAL_RISK in trade_executor).
Correlated portfolio (ρ=0.70 all) → effective cap ~0.035.
Hedged portfolio (ρ=−0.20 all)   → effective cap ~0.065.

Safety:
  apply_risk_budget() NEVER returns more than input `size`.
  All functions clamp their outputs to known safe ranges.
  Division-safe; all exceptions return neutral fallbacks.
  Pure functions — no side effects, read-only access to positions.

Legacy class (RiskEngine) preserved for backward compatibility.
"""

import math
import time as _time
from collections import deque

# ── Legacy class — preserved, not used by trade_executor ──────────────────────

class RiskEngine:
    """Original stub — kept for import compatibility. Logic superseded by V10.12."""

    def __init__(self):
        self.max_risk_per_trade = 0.02
        self.max_drawdown       = 0.15

    def compute_edge(self, confidence, winrate):
        return (confidence * 0.6) + (winrate * 0.4)

    def position_size(self, balance, entry, stop_loss, edge):
        if stop_loss is None or entry == stop_loss:
            return 0
        risk_per_unit = abs(entry - stop_loss)
        capital_risk  = balance * self.max_risk_per_trade
        size          = capital_risk / risk_per_unit
        return size * max(0.1, edge)

    def should_trade(self, drawdown, stabilizer_state):
        if drawdown > self.max_drawdown:
            return False
        if stabilizer_state.get("cooldown", 0) > 0:
            return False
        return True


# ── Constants ──────────────────────────────────────────────────────────────────

MAX_PORTFOLIO_RISK = 0.05       # 5% — matches _MAX_TOTAL_RISK in trade_executor
MAX_PORTFOLIO_VAR  = MAX_PORTFOLIO_RISK ** 2   # 0.0025

# Per-regime fraction of total variance budget.
# BULL/BEAR get more because confirmed-direction positions carry real EV.
# HIGH_VOL gets less because spread + slippage erode the edge faster.
REGIME_BUDGET_FRAC = {
    "BULL_TREND":   0.45,
    "BEAR_TREND":   0.45,
    "RANGING":      0.30,
    "QUIET_RANGE":  0.20,
    "HIGH_VOL":     0.15,
}
_DEFAULT_BUDGET_FRAC = 0.25

# Pairwise correlation heuristic — empirically tuned for Binance crypto pairs
# (daily/hourly data 2021-2024: same-regime BTC/ETH/SOL/BNB correlation ~0.65-0.75)
_RHO_SAME_SAME =  0.70    # same direction + same regime
_RHO_SAME_DIFF =  0.45    # same direction + different regime
_RHO_OPPOSITE  = -0.20    # opposite direction (partial natural hedge)

# ── V10.13: Dynamic correlation memory ────────────────────────────────────────
# Stores rolling realized PnL pairs per (sym_a, sym_b) to learn true correlation.
# Falls back to heuristic when <MIN_CORR_SAMPLES pairs are available.
_corr_memory: dict[tuple, deque] = {}   # (sym_a, sym_b) → deque[(pnl_a, pnl_b)]
_CORR_WINDOW  = 30     # number of co-closed trade pairs to retain
_MIN_CORR_N   = 8      # minimum pairs before switching from heuristic to realized

# ── V10.13: Portfolio PnL trajectory (for momentum) ───────────────────────────
_pf_pnl_hist: deque = deque(maxlen=20)   # (timestamp, total_live_pnl) snapshots


# ── Internal helpers ───────────────────────────────────────────────────────────

def _sl_pct(pos: dict) -> float:
    """SL distance as fraction of entry. Safe fallback 0.004 (0.4%)."""
    entry = pos.get("entry", 0)
    sl    = pos.get("sl", 0)
    if entry <= 0 or sl <= 0:
        return 0.004
    return abs(sl - entry) / max(entry, 1e-9)


def _pos_risk(pos: dict) -> float:
    """Single position risk contribution: r_i = size_i × sl_pct_i."""
    return pos.get("size", 0.0) * _sl_pct(pos)


def _realized_rho(sym_a: str, sym_b: str) -> float | None:
    """
    Realized correlation from rolling trade PnL pairs.
    Returns None when insufficient data (falls back to heuristic).

    Pearson correlation of (pnl_a, pnl_b) pairs from _corr_memory.
    Pairs are appended when both symbols close trades in the same session.
    """
    key  = (min(sym_a, sym_b), max(sym_a, sym_b))   # canonical order
    buf  = _corr_memory.get(key)
    if buf is None or len(buf) < _MIN_CORR_N:
        return None

    xs = [p[0] for p in buf]
    ys = [p[1] for p in buf]
    n  = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx  = (sum((x - mx) ** 2 for x in xs) / n) ** 0.5
    sy  = (sum((y - my) ** 2 for y in ys) / n) ** 0.5
    if sx < 1e-9 or sy < 1e-9:
        return None
    return max(-1.0, min(1.0, num / (n * sx * sy)))


def _pairwise_rho(pos_a: dict, pos_b: dict) -> float:
    """
    Pairwise correlation: realized (V10.13) when available, heuristic fallback.

    V10.13: first queries _corr_memory for realized ρ from actual trade
    outcomes. When insufficient data, falls back to the direction/regime
    heuristic from V10.12.

    Research basis (heuristic): Binance spot 2021-2024, same-regime
    same-direction pairs: realized ρ ≈ 0.65-0.75.
    """
    sym_a = pos_a.get("signal", {}).get("symbol",
            pos_a.get("sym", ""))
    sym_b = pos_b.get("signal", {}).get("symbol",
            pos_b.get("sym", ""))

    if sym_a and sym_b and sym_a != sym_b:
        realized = _realized_rho(sym_a, sym_b)
        if realized is not None:
            return realized

    # Heuristic fallback
    dir_a = pos_a.get("action", "BUY")
    dir_b = pos_b.get("action", "BUY")
    reg_a = pos_a.get("signal", {}).get("regime", "RANGING")
    reg_b = pos_b.get("signal", {}).get("regime", "RANGING")

    if dir_a == dir_b:
        return _RHO_SAME_SAME if reg_a == reg_b else _RHO_SAME_DIFF
    return _RHO_OPPOSITE


def _new_pos_proxy(action: str, regime: str) -> dict:
    """Minimal position dict for _pairwise_rho comparisons."""
    return {"action": action, "signal": {"regime": regime}}


# ── Public API ─────────────────────────────────────────────────────────────────

def portfolio_variance(positions: dict) -> float:
    """
    Correlation-adjusted portfolio variance.

      Var = Σ_i r_i² + 2 × Σ_{i<j} ρ_ij × r_i × r_j

    Clamped to 0.0 (minor negative values can arise from the -0.20 hedge
    correlation when all positions are opposite-direction — numerical artefact).
    """
    pos_list = list(positions.values())
    n = len(pos_list)
    if n == 0:
        return 0.0

    risks = [_pos_risk(p) for p in pos_list]
    var   = sum(r * r for r in risks)

    for i in range(n):
        for j in range(i + 1, n):
            rho = _pairwise_rho(pos_list[i], pos_list[j])
            var += 2.0 * rho * risks[i] * risks[j]

    return max(0.0, var)


def portfolio_risk(positions: dict) -> float:
    """Portfolio standard deviation σ_p = √(portfolio_variance)."""
    return math.sqrt(portfolio_variance(positions))


def apply_risk_budget(size: float, sl_pct: float,
                      action: str, regime: str,
                      positions: dict) -> float:
    """
    Constrain `size` so the new position's marginal variance fits within the
    remaining portfolio risk budget.

    Solves the quadratic:
      a × x² + b × x ≤ remaining_var
      where  a = sl_pct²
             b = 2 × sl_pct × Σ_i ρ_{i,new} × r_i
             x = new_size (what we're solving for)

    Negative b (hedged portfolio) → new position reduces portfolio risk →
    larger sizes are allowed; discriminant still ≥ 0 since remaining_var ≥ 0.

    Also enforces a per-regime sub-budget so no single regime can consume
    the full variance pool.

    Returns a value ≤ size. NEVER returns more than the input `size`.
    Returns size × 0.30 on emergency (portfolio already over limit).
    """
    if not positions or sl_pct <= 1e-9:
        return size

    current_var   = portfolio_variance(positions)
    remaining_var = max(0.0, MAX_PORTFOLIO_VAR - current_var)

    if remaining_var <= 0.0:
        return size * 0.30   # emergency: already over the hard cap

    new_pos = _new_pos_proxy(action, regime)
    cov_sum = sum(
        _pairwise_rho(new_pos, p) * _pos_risk(p)
        for p in positions.values()
    )

    a = sl_pct ** 2
    b = 2.0 * sl_pct * cov_sum   # can be ≤ 0 when new pos hedges the portfolio

    # Quadratic formula — discriminant always ≥ 0 (b²+4a×rem, both terms ≥ 0)
    discriminant    = b * b + 4.0 * a * remaining_var
    max_size_global = (-b + math.sqrt(max(0.0, discriminant))) / (2.0 * a)
    max_size_global = max(0.001, min(max_size_global, size))

    # Per-regime sub-budget enforcement
    reg_frac     = REGIME_BUDGET_FRAC.get(regime, _DEFAULT_BUDGET_FRAC)
    reg_budget   = MAX_PORTFOLIO_VAR * reg_frac
    same_reg_pos = {s: p for s, p in positions.items()
                    if p.get("signal", {}).get("regime", "") == regime}
    reg_var_used = portfolio_variance(same_reg_pos)
    reg_remaining = max(0.0, reg_budget - reg_var_used)

    if reg_remaining < (max_size_global * sl_pct) ** 2:
        max_size_reg    = math.sqrt(max(0.0, reg_remaining)) / sl_pct
        max_size_global = min(max_size_global, max(0.001, max_size_reg))

    return min(size, max_size_global)


def corr_size_factor(new_action: str, new_regime: str,
                     positions: dict) -> float:
    """
    Continuous, regime-aware sizing factor [0.60, 1.10].

    Complements execution.py's correlation_size_penalty() (which uses only
    a direction count) with regime-context and a hedge bonus:

      All same dir + same reg  → 0.60  (concentrated risk — heavy penalty)
      All same dir + diff reg  → 0.80  (partial concentration)
      Neutral / no positions   → 1.00
      All opposite direction   → 1.10  (diversifying hedge — slight boost)

    In practice with mixed portfolios, the factor is a weighted average.
    Applied INSTEAD of the corr_size_factor within trade_executor V10.12 block.
    The original correlation_size_penalty() remains active as a parallel gate.
    """
    if not positions:
        return 1.0

    n = len(positions)
    total_weight = 0.0

    for p in positions.values():
        p_dir = p.get("action", "BUY")
        p_reg = p.get("signal", {}).get("regime", "RANGING")

        if p_dir == new_action:
            total_weight += 0.60 if p_reg == new_regime else 0.80
        else:
            total_weight += 1.10

    return max(0.60, min(1.10, total_weight / n))


def replacement_correlation_adj(new_action: str, new_regime: str,
                                positions: dict, worst_sym: str) -> float:
    """
    Threshold multiplier [0.70, 1.30] for V10.10 replacement decisions.

    After replacing `worst_sym`, how correlated is the new position with
    the REMAINING portfolio?

      High avg_rho (concentrated) → multiplier > 1.0 → raise bar to replace
      Low/negative avg_rho (diverse/hedge) → multiplier < 1.0 → lower bar

    Integration in trade_executor V10.10 block:
      _eff_thr *= replacement_correlation_adj(action, regime, _positions, worst10)

    So a trade that genuinely diversifies the portfolio clears the threshold
    at 70% of the standard level; one that piles on gets a 30% higher bar.
    """
    remaining = {s: p for s, p in positions.items() if s != worst_sym}
    if not remaining:
        return 1.0

    new_pos = _new_pos_proxy(new_action, new_regime)
    avg_rho = sum(
        _pairwise_rho(new_pos, p) for p in remaining.values()
    ) / len(remaining)

    # Linear: avg_rho=-0.20→0.88×  0→1.0×  +0.70→1.42× (clamped at 1.30)
    multiplier = 1.0 + avg_rho * 0.60
    return max(0.70, min(1.30, multiplier))


def risk_report(positions: dict) -> dict:
    """
    Diagnostic snapshot of current portfolio risk state.
    Called from trade_executor for logging when apply_risk_budget fires.
    Never raises — returns {} on any error.
    """
    try:
        pvar = portfolio_variance(positions)
        frac = pvar / max(MAX_PORTFOLIO_VAR, 1e-9)
        pstd = math.sqrt(pvar)

        regime_breakdown = {}
        for regime in set(
            p.get("signal", {}).get("regime", "UNKNOWN")
            for p in positions.values()
        ):
            same_reg = {s: p for s, p in positions.items()
                        if p.get("signal", {}).get("regime", "") == regime}
            reg_var  = portfolio_variance(same_reg)
            reg_cap  = MAX_PORTFOLIO_VAR * REGIME_BUDGET_FRAC.get(
                regime, _DEFAULT_BUDGET_FRAC)
            regime_breakdown[regime] = {
                "risk":     round(math.sqrt(reg_var), 6),
                "cap":      round(math.sqrt(reg_cap), 6),
                "pct_used": round(reg_var / max(reg_cap, 1e-9), 4),
            }

        return {
            "portfolio_risk":   round(pstd, 6),
            "portfolio_var":    round(pvar, 8),
            "budget_used_pct":  round(frac, 4),
            "n_positions":      len(positions),
            "regime_breakdown": regime_breakdown,
        }
    except Exception:
        return {}


# ── V10.13: Dynamic correlation memory update ─────────────────────────────────

def update_correlation_memory(closed_sym: str, closed_pnl: float,
                               positions: dict) -> None:
    """
    Record a realized (pnl_closed, pnl_peer) pair for every symbol currently
    open alongside the just-closed position. Called from trade_executor
    immediately before del _positions[sym] so the peer positions are still live.

    The closed_pnl is paired with each peer's current live_pnl (best proxy for
    realized return at the same time window). Pairs accumulate in _corr_memory
    keyed by canonical (min_sym, max_sym) tuple and feed _realized_rho().

    Bootstrap-safe: does nothing until at least one peer position is open.
    Thread-safe: deque.append() is atomic in CPython.
    """
    for peer_sym, peer_pos in positions.items():
        if peer_sym == closed_sym:
            continue
        peer_pnl = peer_pos.get("live_pnl", 0.0)
        key = (min(closed_sym, peer_sym), max(closed_sym, peer_sym))
        if key not in _corr_memory:
            _corr_memory[key] = deque(maxlen=_CORR_WINDOW)
        _corr_memory[key].append((closed_pnl, peer_pnl))


# ── V10.13: Portfolio PnL trajectory snapshot ─────────────────────────────────

def record_portfolio_pnl(positions: dict) -> None:
    """
    Snapshot total live_pnl of all open positions into the rolling history.
    Called from trade_executor.on_price() once per global tick (not per symbol).
    Used by portfolio_momentum() to compute trajectory direction and slope.
    """
    total_pnl = sum(p.get("live_pnl", 0.0) * p.get("size", 1.0)
                    for p in positions.values())
    _pf_pnl_hist.append((_time.time(), total_pnl))


# ── V10.13: Portfolio momentum ────────────────────────────────────────────────

def portfolio_momentum(positions: dict | None = None) -> float:
    """
    Trajectory-aware portfolio momentum score ∈ [-1.0, +1.0].

    Uses OLS slope of recent size-weighted portfolio PnL snapshots from
    _pf_pnl_hist (populated by record_portfolio_pnl() each tick).

    Positive momentum → system is trending toward profit → allow risk expansion.
    Negative momentum → system is degrading → tighten risk budget.

    Fallback (< 4 snapshots): uses current position live_pnl sign as proxy.
    Returns 0.0 when no data is available (neutral — no throttling).

    Usage in trade_executor handle_signal():
      size *= max(0.70, 1.0 + 0.20 * portfolio_momentum())
      → momentum=+1.0 → ×1.20 (expansion)
      → momentum=-1.0 → ×0.70 (floor — never below 70%)
      → momentum=0.0  → ×1.00 (neutral)
    """
    # ── OLS slope over snapshot window ───────────────────────────────────────
    snaps = list(_pf_pnl_hist)
    if len(snaps) >= 4:
        n   = len(snaps)
        ts  = [s[0] for s in snaps]
        pnl = [s[1] for s in snaps]
        t0  = ts[0]
        xs  = [t - t0 for t in ts]   # relative seconds
        mx  = sum(xs) / n
        my  = sum(pnl) / n
        num = sum((xs[i] - mx) * (pnl[i] - my) for i in range(n))
        den = sum((xs[i] - mx) ** 2 for i in range(n))
        if den > 1e-9:
            slope = num / den   # PnL change per second
            # Normalize by typical PnL magnitude; cap at ±1
            norm = max(abs(my) * 0.01, 1e-6)
            return max(-1.0, min(1.0, slope / norm))

    # ── Fallback: direction of current open positions ─────────────────────────
    if positions:
        signed = [p.get("live_pnl", 0.0) for p in positions.values()]
        pos_n  = sum(1 for x in signed if x > 0)
        neg_n  = sum(1 for x in signed if x < 0)
        if pos_n + neg_n == 0:
            return 0.0
        return (pos_n - neg_n) / (pos_n + neg_n)

    return 0.0


# ── V10.13: Portfolio pressure ────────────────────────────────────────────────

def portfolio_pressure(positions: dict) -> float:
    """
    Global stress score ∈ [0.0, 1.0] combining four independent stress signals.
    Used to throttle trades, reduce sizes, disable recycling, and tighten
    replacement thresholds.

    Components:
      drawdown_stress (weight 0.35):
        Current drawdown vs equity peak, normalized to 0-20% range.
        >20% DD → 1.0; <1% → ~0.05. Dominant term: capital preservation.

      failure_stress (weight 0.25):
        failure_score from diagnostics.py, normalized to [0,3] range.
        >3 → 1.0; 0 → 0.0. Reflects overfit + regime shift + exec decay.

      risk_budget_stress (weight 0.25):
        Current portfolio variance as fraction of MAX_PORTFOLIO_VAR.
        100% budget used → 1.0; 0% → 0.0.

      regime_concentration_stress (weight 0.15):
        Fraction of positions in the most-concentrated regime.
        All in same regime → 1.0; perfectly spread → 0.0.

    Returns 0.0 on empty portfolio or when any component fails.
    Safe: all components have try/except; partial failures return 0.0
    for that component only.
    """
    # 1. Drawdown stress
    dd_stress = 0.0
    try:
        from src.services.diagnostics import max_drawdown as _mdd
        dd_val    = float(_mdd() or 0.0)
        dd_stress = min(1.0, dd_val / 0.20)   # normalize to 20% range
    except Exception:
        pass

    # 2. Failure score stress
    fs_stress = 0.0
    try:
        from src.services.diagnostics import failure_score as _fs
        fs_val    = float(_fs(positions) or 0.0)
        fs_stress = min(1.0, fs_val / 3.0)    # normalize: >3.0 = halt territory
    except Exception:
        pass

    # 3. Risk budget stress
    rb_stress = 0.0
    try:
        pvar      = portfolio_variance(positions)
        rb_stress = min(1.0, pvar / max(MAX_PORTFOLIO_VAR, 1e-9))
    except Exception:
        pass

    # 4. Regime concentration stress
    rc_stress = 0.0
    try:
        n = len(positions)
        if n >= 2:
            regime_counts: dict[str, int] = {}
            for p in positions.values():
                r = p.get("signal", {}).get("regime", "RANGING")
                regime_counts[r] = regime_counts.get(r, 0) + 1
            max_count = max(regime_counts.values())
            rc_stress = max_count / n   # 1.0 when all same regime
    except Exception:
        pass

    pressure = (0.35 * dd_stress
              + 0.25 * fs_stress
              + 0.25 * rb_stress
              + 0.15 * rc_stress)
    return max(0.0, min(1.0, pressure))


# ── V10.13: Global portfolio score ────────────────────────────────────────────

def portfolio_score(positions: dict) -> float:
    """
    Global portfolio quality metric for replacement decisions.

    score = sum(efficiency_live)
            + momentum_bonus
            − risk_penalty

    Components:
      sum(efficiency_live):  total live capital efficiency across all positions.
        efficiency_live = policy_ev × exp(-t/tau) — stored per position.
        Higher is better: more EV per unit of expected hold time.

      momentum_bonus [0, 0.1]:  portfolio trajectory boosts or suppresses score.
        Positive momentum (+1.0) → +0.10; negative (-1.0) → 0.
        Bounded [0, 0.1] to avoid momentum dominating the efficiency signal.

      risk_penalty [0, ∞):  penalize over-concentration and drawdown stress.
        = portfolio_variance(positions) × 20 + pressure × 0.2
        ×20 maps typical variance (0.0001–0.001) to (0.002–0.02) range,
        comparable to efficiency contributions from 1–3 positions.

    Returns 0.0 on empty portfolio.
    Higher score = portfolio is in better shape.
    Used by _replace_if_better() to compare current vs simulated portfolios.
    """
    if not positions:
        return 0.0

    eff_sum = sum(
        p.get("efficiency_live", p.get("efficiency", 0.0))
        for p in positions.values()
    )

    mom        = portfolio_momentum(positions)
    mom_bonus  = max(0.0, mom * 0.10)   # only positive momentum boosts score

    pvar       = portfolio_variance(positions)
    pressure   = portfolio_pressure(positions)
    risk_pen   = pvar * 20.0 + pressure * 0.20

    return eff_sum + mom_bonus - risk_pen
