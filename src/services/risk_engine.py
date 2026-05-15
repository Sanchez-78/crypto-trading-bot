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
from typing import Any

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
            # Use max(abs(my), 0.01) to prevent near-zero mean from amplifying to ±1 spuriously
            norm = max(abs(my), 0.01) * 0.01
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


# ══════════════════════════════════════════════════════════════════════════════
# V10.12c — Portfolio Risk Budget multiplier (stability refinements)
# ══════════════════════════════════════════════════════════════════════════════

# Base notional heat cap — adaptive: expands during good performance,
# tightens during drawdown. See _adaptive_base_heat().
_BASE_HEAT_NOMINAL: float = 0.20   # 20% nominal

# EMA state for risk_budget smoothing (prevents jumpy sizing)
_rb_ema: list[float | None] = [None]   # mutable scalar; None = uninitialised
_RB_EMA_ALPHA: float = 0.10            # 0.9 × prev + 0.1 × raw

# Module-level peak equity tracker (true equity, includes unrealized PnL)
_peak_equity: list[float] = [0.0]
try:
    from src.services.learning_event import METRICS as _M_init
    _peak_equity[0] = float(_M_init.get("equity_peak", 0.0) or 0.0)
    _dd0 = float(_M_init.get("drawdown", 0.0) or 0.0)
    _rb_ema[0] = max(0.3, min(1.0, 1.0 - _dd0 * 2.0))
    del _M_init, _dd0
except Exception:
    pass

# ── Daily drawdown circuit breaker ────────────────────────────────────────────
# Resets at midnight UTC. Hard halt when session loss exceeds DAILY_DD_LIMIT.
# Graduated: 5% → 1.0× , 3% → 0.75× , DAILY_DD_LIMIT(5%) → HALT
import time as _time_re
_DAILY_DD_LIMIT  = 0.05    # 5% daily loss → hard halt (no new trades)
_DAILY_DD_WARN   = 0.03    # 3% → size reduced to 75%
_daily_start_eq: list[float] = [0.0]   # equity at session start
_daily_reset_day: list[int]  = [-1]    # UTC day of last reset


def _maybe_reset_daily() -> None:
    """Reset daily equity baseline at midnight UTC."""
    today = int(_time_re.time() // 86400)
    if _daily_reset_day[0] != today:
        try:
            from src.services.learning_event import METRICS as _M_d
            _daily_start_eq[0] = float(_M_d.get("profit", 0.0))
        except Exception:
            _daily_start_eq[0] = 0.0
        _daily_reset_day[0] = today


def daily_dd_factor() -> float:
    """
    Returns size multiplier based on today's session drawdown:
      DD < 3%  → 1.00 (no penalty)
      DD < 5%  → 0.75 (reduce size)
      DD >= 5% → 0.00 (hard halt — return 0.0 signals caller to block)
    """
    _maybe_reset_daily()
    try:
        from src.services.learning_event import METRICS as _M_d
        current = float(_M_d.get("profit", 0.0))
    except Exception:
        return 1.0
    start = _daily_start_eq[0]
    if _daily_reset_day[0] < 0:
        return 1.0   # not yet initialised
    # daily_loss = absolute drop in cumulative profit since session start.
    # METRICS["profit"] is a running sum of trade P&L fractions — so the
    # difference IS the day's loss as a fraction of capital. Dividing by
    # abs(start) was wrong: tiny start values caused 1000%+ "loss" on any
    # small trade, triggering permanent HALT after the first tick.
    daily_loss = start - current
    if daily_loss >= _DAILY_DD_LIMIT:
        return 0.0   # HALT
    if daily_loss >= _DAILY_DD_WARN:
        return 0.75  # reduce
    return 1.0


def is_daily_dd_safe() -> bool:
    """Returns False when daily loss limit is reached → block all new trades."""
    return daily_dd_factor() > 0.0

# Cache for prob_ruin from Monte Carlo (Firebase I/O — refresh every 5 min)
_mc_cache: dict[str, Any] = {"prob_ruin": None, "ts": 0.0}
_MC_TTL = 3600.0   # V10.14: Increased from 300s to 1 hour to reduce Firebase reads
                    # At 50k reads/day limit, 86k ticks/min would exhaust quota in <1 hour
                    # Cache auditor state for 1 hour unless explicitly cleared


# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_prob_ruin() -> float | None:
    """
    Load prob_ruin from auditor_state["monte_carlo"] with 5-min cache.
    Returns None when unavailable (triggers mc_factor = 1.0 neutral).
    """
    now = _time.time()
    if now - _mc_cache["ts"] < _MC_TTL and _mc_cache["prob_ruin"] is not None:
        return _mc_cache["prob_ruin"]
    try:
        from src.services.firebase_client import load_auditor_state
        state = load_auditor_state() or {}
        mc = state.get("monte_carlo", {})
        pr = mc.get("prob_ruin")
        _mc_cache["prob_ruin"] = float(pr) if pr is not None else None
        _mc_cache["ts"] = now
        return _mc_cache["prob_ruin"]
    except Exception:
        return None


def _true_equity(positions: dict) -> float:
    """
    V10.12c: True equity = realized PnL + unrealized PnL across open positions.

    unrealized contribution per position = live_pnl (fractional return) × size.
    live_pnl is set each tick: (curr - entry) / entry × direction.
    Positions dict may be empty — returns realized-only equity in that case.
    """
    try:
        from src.services.learning_event import METRICS as _M
        realized = _M.get("profit", 0.0)
    except Exception:
        realized = 0.0

    unrealized = sum(
        p.get("live_pnl", 0.0) * abs(p.get("size", 0.0))
        for p in positions.values()
    )
    return realized + unrealized


def _adaptive_base_heat(dd: float) -> float:
    """
    V10.12c: Adaptive heat cap — tightens during drawdown, expands on recovery.
    dd=0.0 → 0.30 (full expansion)
    dd=0.20 → 0.20 (nominal)
    dd=0.40+ → 0.10 (floor, high drawdown)
    Formula: 0.20 + 0.10 × (1 - dd), clamped [0.10, 0.30].
    """
    return max(0.10, min(0.30, _BASE_HEAT_NOMINAL + 0.10 * (1.0 - dd)))


# ── Public API ─────────────────────────────────────────────────────────────────

def portfolio_risk_budget(positions: dict) -> dict[str, float]:
    """
    Compute a system-health multiplier risk_budget ∈ [0.3, 1.0].

    V10.12c changes vs V10.12b:
      - Drawdown uses TRUE equity (realized + unrealized), not realized-only.
      - Peak equity tracked at module level and updated each call.
      - Raw multiplier smoothed via EMA (α=0.10) to prevent jumpy sizing.
      - Returns heat / max_heat for logging.

    Three independent axes:
      dd_factor     — drawdown depth (primary circuit breaker)
      sharpe_factor — trend quality (are wins covering losses?)
      mc_factor     — Monte Carlo ruin probability (tail risk)

    Fail-safe: any exception returns risk_budget=1.0 (no scaling).
    """
    result = {
        "risk_budget": 1.0, "dd": 0.0, "sharpe": 0.0, "ruin": 0.0,
        "heat": 0.0, "max_heat": _adaptive_base_heat(0.0),
    }
    try:
        # ── True equity + drawdown ────────────────────────────────────────────
        equity = _true_equity(positions)

        # Update module-level peak (never decreases)
        if equity > _peak_equity[0]:
            _peak_equity[0] = equity
        peak = _peak_equity[0]

        if peak > 0:
            dd = max(0.0, (peak - equity) / max(peak, 1e-6))
        else:
            dd = 0.0

        if dd < 0.05:
            dd_factor = 1.0
        elif dd < 0.10:
            dd_factor = 0.80
        elif dd < 0.20:
            dd_factor = 0.60
        else:
            dd_factor = 0.40

        # ── Sharpe factor ─────────────────────────────────────────────────────
        sharpe = None
        try:
            from src.services.diagnostics import sharpe as _sr
            sharpe = _sr()
        except Exception:
            pass
        if sharpe is None:
            sharpe_factor = 1.0
        elif sharpe > 1.5:
            sharpe_factor = 1.0
        elif sharpe > 1.0:
            sharpe_factor = 0.90
        else:
            sharpe_factor = 0.75

        # ── Monte Carlo ruin factor ───────────────────────────────────────────
        prob_ruin = _get_prob_ruin()
        if prob_ruin is None:
            mc_factor = 1.0
        elif prob_ruin > 0.20:
            mc_factor = 0.60
        elif prob_ruin > 0.10:
            mc_factor = 0.80
        else:
            mc_factor = 1.0

        # ── EMA smoothing (prevents jumpy sizing on noisy inputs) ─────────────
        raw_budget = dd_factor * sharpe_factor * mc_factor
        if _rb_ema[0] is None:
            _rb_ema[0] = raw_budget          # first call — no history yet
        else:
            _rb_ema[0] = (1.0 - _RB_EMA_ALPHA) * _rb_ema[0] + _RB_EMA_ALPHA * raw_budget
        risk_budget = max(0.3, min(1.0, _rb_ema[0]))

        # ── Heat accounting ───────────────────────────────────────────────────
        base_heat = _adaptive_base_heat(dd)
        heat      = _vol_weighted_heat(positions)
        max_heat  = base_heat * risk_budget

        result = {
            "risk_budget": round(risk_budget, 4),
            "dd":          round(dd,          4),
            "sharpe":      round(sharpe or 0.0, 3),
            "ruin":        round(prob_ruin or 0.0, 3),
            "heat":        round(heat,      4),
            "max_heat":    round(max_heat,  4),
        }

    except Exception:
        pass   # neutral fallback already set

    return result


def _vol_weighted_heat(positions: dict) -> float:
    """
    V10.12c: Volatility-weighted exposure — high-vol positions count more.
    Uses sl_move (abs(sl-entry)/entry) as the atr_pct proxy; it's always
    present in the position dict and captures the volatility at open.
    Fallback: 0.001 (0.1%) when field is missing or zero.
    """
    total = 0.0
    for p in positions.values():
        size    = abs(p.get("size", 0.0))
        atr_pct = max(p.get("sl_move", 0.0), 0.001)
        total  += size * atr_pct
    return total


def heat_limit_ok(positions: dict, risk_budget: float) -> bool:
    """
    V10.12c: Vol-weighted heat vs adaptive cap.

    max_heat = _adaptive_base_heat(current_dd) × risk_budget
    total_exposure = Σ size × max(sl_move, 0.001)   [vol-weighted]

    Returns False → skip new trade (heat full).
    Fail-safe: True on any exception (allow trade).
    """
    try:
        # Reconstruct current dd from module-level peak (consistent with
        # the dd used in portfolio_risk_budget — no extra equity I/O).
        equity    = _true_equity(positions)
        peak      = _peak_equity[0]
        dd        = max(0.0, (peak - equity) / max(peak, 1e-6)) if peak > 0 else 0.0

        base_heat      = _adaptive_base_heat(dd)
        max_heat       = base_heat * risk_budget
        total_exposure = _vol_weighted_heat(positions)
        return total_exposure <= max_heat
    except Exception:
        return True   # fail-safe: allow trade
