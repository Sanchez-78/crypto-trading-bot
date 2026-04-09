"""
pre_live_audit.py — Pre-Live Audit Script (V10.12c)

Simulates 20–50 synthetic signals through the full sizing chain and logs
intermediate sizes, risk-engine metrics, execution quality, and RDE
auditor factors.  Read-only: does NOT modify any production state.

    python -m src.services.pre_live_audit [--trades N] [--quiet] [--seed N]
"""

from __future__ import annotations

import argparse
import os
import sys
import random
from dataclasses import dataclass, field
from typing import Any

# ── Bootstrap path ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import base64
if not os.getenv("FIREBASE_KEY_BASE64") and os.path.exists("firebase_key.json"):
    with open("firebase_key.json", "rb") as _f:
        os.environ["FIREBASE_KEY_BASE64"] = base64.b64encode(_f.read()).decode("utf-8")


# ── Synthetic signal factory ───────────────────────────────────────────────────

_REGIMES = ["BULL_TREND", "BEAR_TREND", "RANGING", "QUIET_RANGE", "HIGH_VOL"]
_ACTIONS = ["BUY", "SELL"]

_FEATURE_TEMPLATES = [
    {"rsi_oversold": True,   "macd_cross_up": True,  "vol_spike": False, "bb_squeeze": False},
    {"rsi_overbought": True, "macd_cross_dn": True,  "vol_spike": True,  "bb_squeeze": False},
    {"bb_squeeze": True,     "macd_cross_up": False, "vol_spike": False, "rsi_oversold": False},
    {"rsi_oversold": True,   "vol_spike": True,      "macd_cross_up": True,  "bb_upper": False},
    {"trend_align": True,    "vol_spike": False,     "rsi_oversold": False,  "bb_lower": True},
]

_BASE_PRICES = {
    "BTCUSDT": 65000.0,
    "ETHUSDT":  3200.0,
    "SOLUSDT":   160.0,
    "BNBUSDT":   580.0,
    "ADAUSDT":     0.45,
}


def _make_signals(n: int = 40, seed: int = 42) -> list[dict]:
    rng  = random.Random(seed)
    syms = list(_BASE_PRICES.keys())
    out: list[dict] = []
    for i in range(n):
        sym   = syms[i % len(syms)]
        price = _BASE_PRICES[sym] * (1.0 + rng.uniform(-0.04, 0.04))
        atr   = price * rng.uniform(0.008, 0.025)
        feats = dict(rng.choice(_FEATURE_TEMPLATES))
        feats["rsi"]       = rng.uniform(25.0, 75.0)
        feats["atr_pct"]   = atr / price
        feats["vol_ratio"] = rng.uniform(0.8, 2.5)
        out.append({
            "sym":             sym,
            "action":          rng.choice(_ACTIONS),
            "regime":          rng.choice(_REGIMES),
            "confidence":      rng.uniform(0.45, 0.85),
            "price":           price,
            "atr":             atr,
            "features":        feats,
            "ws":              rng.uniform(0.40, 0.90),
            "_is_replacement": False,
            "_recycling_pnl":  None,
        })
    return out


# ── Audit-only sizing helpers ──────────────────────────────────────────────────
# Approximations of internal trade_executor logic — for logging only.

_BASE_SIZE = 0.025   # conservative per-trade baseline

def _kelly(ev: float) -> float:
    """Kelly: base × clamp(ev×6, 0.5, 3.0)"""
    return _BASE_SIZE * max(0.5, min(3.0, ev * 6.0))


def _policy_mult(regime: str, ev: float) -> float:
    """Simplified regime + EV policy multiplier."""
    base = {"BULL_TREND": 1.00, "BEAR_TREND": 1.00,
            "RANGING": 0.85, "QUIET_RANGE": 0.70, "HIGH_VOL": 0.75}.get(regime, 0.85)
    ev_adj = max(0.50, min(1.30, 0.80 + max(0.0, ev) * 5.0))
    return max(0.40, min(1.50, base * ev_adj))


def _meta_mult(wr: float, dd: float) -> float:
    """Meta-controller multiplier based on WR and drawdown."""
    if   dd > 0.15: return 0.50
    elif dd > 0.10: return 0.70
    elif wr < 0.30: return 0.75
    elif wr > 0.65: return 1.10
    else:           return 1.00


def _net_edge(ev: float, spread: float, fee_rt: float = 0.0015) -> float:
    return ev - spread * 0.5 - fee_rt


def _cost_ok(ev: float, fee_rt: float = 0.0015) -> bool:
    return ev > fee_rt * 2.0


# ── Synthetic OrderBook stub ───────────────────────────────────────────────────

class _AuditOB:
    """Minimal OrderBook substitute — no real L2 data needed for audit."""
    __slots__ = ("bid", "ask", "bid_vol", "ask_vol")

    def __init__(self, price: float, spread_pct: float = 0.0005,
                 bid_vol: float = 15.0, ask_vol: float = 12.0):
        half         = price * spread_pct / 2.0
        self.bid     = price - half
        self.ask     = price + half
        self.bid_vol = bid_vol
        self.ask_vol = ask_vol


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class AuditResult:
    idx:    int
    sym:    str
    action: str
    regime: str
    price:  float

    # RDE output
    ev:             float = 0.0
    ev_threshold:   float = 0.0
    auditor_factor: float = 1.0
    velocity_pen:   float = 1.0
    streak_pen:     float = 1.0
    combo_pen:      float = 1.0
    emergency:      bool  = False

    # Sizing chain intermediates (after each multiplier)
    s_kelly:       float = 0.0
    s_policy:      float = 0.0
    s_meta:        float = 0.0
    s_corr:        float = 0.0
    s_var:         float = 0.0
    s_exec_q:      float = 0.0
    s_risk_budget: float = 0.0
    s_final:       float = 0.0

    # Per-stage multipliers
    policy_mult: float = 1.0
    meta_mult:   float = 1.0
    corr_mult:   float = 1.0
    exec_quality:float = 1.0

    # Risk budget decomposition
    risk_budget: float = 1.0
    dd:          float = 0.0
    sharpe:      float = 0.0
    ruin:        float = 0.0
    heat:        float = 0.0
    max_heat:    float = 0.20

    # Execution quality decomposition
    spread:   float = 0.0
    slippage: float = 0.0
    fill:     float = 1.0
    lat:      float = 1.0

    # Gate outcomes
    rde_pass:           bool = True
    eq_skip:            bool = False
    net_edge_blocked:   bool = False
    cost_guard_blocked: bool = False
    heat_blocked:       bool = False

    # Monotone check
    monotone_ok:         bool      = True
    monotone_violations: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (self.rde_pass
                and not self.eq_skip
                and not self.net_edge_blocked
                and not self.cost_guard_blocked
                and not self.heat_blocked
                and self.s_final > 0)


# ── Core per-trade audit ───────────────────────────────────────────────────────

def _audit_one(signal: dict, positions: dict, idx: int, verbose: bool) -> AuditResult:
    sym    = signal["sym"]
    action = signal["action"]
    regime = signal["regime"]
    price  = signal["price"]
    atr    = signal["atr"]

    r = AuditResult(idx=idx, sym=sym, action=action, regime=regime, price=price)

    if verbose:
        sep = "─" * 68
        print(f"\n{sep}")
        print(f"[{idx:02d}] {sym}  {action}  {regime}  "
              f"price={price:.4f}  atr={atr:.4f}  conf={signal['confidence']:.3f}")
        print(sep)

    # ── 0. RDE gate ───────────────────────────────────────────────────────────
    ev = 0.03   # fallback used if RDE unavailable
    try:
        from src.services.realtime_decision_engine import (
            evaluate_signal  as _rde,
            get_ev_threshold as _get_thr,
        )
        sig_copy = dict(signal)   # RDE mutates the dict in-place
        enriched = _rde(sig_copy)
        if enriched is None:
            r.rde_pass = False
            if verbose:
                print(f"    RDE[v10.10b]: BLOCKED  sym={sym}")
            return r

        ev              = float(enriched.get("ev",              0.03))
        r.ev            = ev
        r.auditor_factor = float(enriched.get("auditor_factor", 1.0))
        r.velocity_pen  = float(enriched.get("velocity_penalty", 1.0))
        r.streak_pen    = float(enriched.get("streak_penalty",  1.0))
        r.combo_pen     = float(enriched.get("combo_penalty",   1.0))
        try:
            r.ev_threshold = float(_get_thr())
        except Exception:
            r.ev_threshold = 0.05

    except Exception as exc:
        # Firebase / import unavailable — use confidence as EV proxy
        ev = max(0.03, float(signal.get("confidence", 0.55)) - 0.40)
        r.ev           = ev
        r.ev_threshold = 0.05
        if verbose:
            print(f"    RDE[v10.10b]: skipped ({exc.__class__.__name__})  "
                  f"ev_proxy={ev:.3f}")

    if verbose and r.rde_pass:
        print(f"    RDE[v10.10b]: ev={r.ev:.3f} thr={r.ev_threshold:.3f} "
              f"vel_pen={r.velocity_pen:.2f} streak_pen={r.streak_pen:.2f} "
              f"combo_pen={r.combo_pen:.2f} emergency={r.emergency}")

    # ── 1. Kelly size (includes auditor_factor already folding vel+streak+combo)
    s          = _kelly(ev) * r.auditor_factor
    r.s_kelly  = s

    # ── 2. Policy ─────────────────────────────────────────────────────────────
    pm         = _policy_mult(regime, ev)
    s         *= pm
    r.s_policy = s
    r.policy_mult = pm
    if verbose:
        print(f"    policy[audit]: mode={regime}  pm={pm:.3f}  policy_ev={ev:.4f}  "
              f"kelly={r.s_kelly:.5f}→{s:.5f}")

    # ── 3. Meta ───────────────────────────────────────────────────────────────
    dd_approx = 0.0
    wr_approx = 0.55
    try:
        from src.services.learning_event import METRICS as _M
        t = _M.get("trades", 0)
        if t > 0:
            wr_approx = _M.get("wins", 0) / t
        dd_approx = float(_M.get("drawdown", 0.0) or 0.0)
    except Exception:
        pass
    mm         = _meta_mult(wr_approx, dd_approx)
    s         *= mm
    r.s_meta   = s
    r.meta_mult = mm
    if verbose:
        print(f"    meta[audit]:   wr={wr_approx:.2f}  dd={dd_approx:.3f}  "
              f"meta×{mm:.2f}  post={s:.5f}")

    # ── 4. Correlation ────────────────────────────────────────────────────────
    csf = 1.0
    try:
        from src.services.risk_engine import corr_size_factor as _csf
        csf = _csf(action, regime, positions)
    except Exception as exc:
        if verbose:
            print(f"    corr[audit]:   skipped ({exc.__class__.__name__})")
    s          *= csf
    r.s_corr    = s
    r.corr_mult = csf
    if verbose:
        print(f"    corr[audit]:   csf×{csf:.2f}  post={s:.5f}")

    # ── 5. VaR budget ─────────────────────────────────────────────────────────
    sl_pct = 0.004   # 0.4% proxy — matches _proxy sl_move in trade_executor
    try:
        from src.services.risk_engine import apply_risk_budget as _arb
        s_pre = s
        s     = _arb(s, sl_pct, action, regime, positions)
        if verbose and s < s_pre * 0.95:
            print(f"    VaR[audit]:    constrained {s_pre:.5f}→{s:.5f}  "
                  f"sl_pct={sl_pct:.4f}")
    except Exception as exc:
        if verbose:
            print(f"    VaR[audit]:    skipped ({exc.__class__.__name__})")
    r.s_var = s
    if verbose:
        print(f"    VaR[audit]:    post={s:.5f}")

    # ── 6. Execution quality ──────────────────────────────────────────────────
    atr_pct = atr / max(price, 1e-9)
    ob      = _AuditOB(price)
    eq_res  = {"skip": False, "exec_quality": 1.0, "spread": 0.0005,
               "slip": 0.0005, "fill": 1.0, "lat": 1.0}
    try:
        from src.services.execution_quality import exec_quality_score
        eq_res = exec_quality_score(sym, action, price, atr_pct, ob)
    except Exception as exc:
        if verbose:
            print(f"    exec_quality[v10.11]: skipped ({exc.__class__.__name__})")

    r.eq_skip     = bool(eq_res.get("skip",         False))
    r.exec_quality = float(eq_res.get("exec_quality", 1.0))
    r.spread      = float(eq_res.get("spread",       0.0005))
    r.slippage    = float(eq_res.get("slip",         0.0005))
    r.fill        = float(eq_res.get("fill",          1.0))
    r.lat         = float(eq_res.get("lat",           1.0))

    if r.eq_skip:
        if verbose:
            print(f"    exec_quality[v10.11]: HARD_SKIP  "
                  f"spread={r.spread:.5f} > 0.00150  sym={sym}")
        return r

    s          *= r.exec_quality
    r.s_exec_q  = s
    if verbose:
        print(f"    exec_quality[v10.11]: exec_q={r.exec_quality:.2f} "
              f"spread={r.spread:.5f} slip={r.slippage:.5f} "
              f"fill={r.fill:.2f} lat={r.lat:.2f}  post={s:.5f}")

    # ── 7. Net edge ───────────────────────────────────────────────────────────
    net = _net_edge(ev, r.spread)
    if net <= 0.0:
        r.net_edge_blocked = True
        if verbose:
            print(f"    net_edge[audit]: BLOCKED  net={net:.5f}  "
                  f"ev={ev:.3f}  spread={r.spread:.5f}")
        return r
    if verbose:
        print(f"    net_edge[audit]: OK  net={net:.5f}")

    # ── 8. Cost guard ─────────────────────────────────────────────────────────
    if not _cost_ok(ev):
        r.cost_guard_blocked = True
        if verbose:
            print(f"    cost_guard[audit]: BLOCKED  ev={ev:.3f} < fee×2 (0.003)")
        return r
    # Size unchanged through net_edge / cost_guard gates
    r.s_net_edge = r.s_cost_guard = s

    # ── 9. Portfolio risk budget ──────────────────────────────────────────────
    try:
        from src.services.risk_engine import (
            portfolio_risk_budget as _prb,
            heat_limit_ok         as _hlo,
        )
        rb_res       = _prb(positions)
        rb           = rb_res["risk_budget"]
        r.risk_budget = rb
        r.dd          = rb_res.get("dd",       0.0)
        r.sharpe      = rb_res.get("sharpe",   0.0)
        r.ruin        = rb_res.get("ruin",     0.0)
        r.heat        = rb_res.get("heat",     0.0)
        r.max_heat    = rb_res.get("max_heat", 0.20)

        if not _hlo(positions, rb):   # existing positions only; incoming capped by VaR above
            r.heat_blocked = True
            if verbose:
                print(f"    risk_budget[v10.12c]: HEAT_LIMIT  sym={sym}  risk={rb:.2f}")
            return r

        if rb < 1.0:
            s *= rb

        if verbose:
            print(f"    risk_budget[v10.12c]: risk={rb:.2f} "
                  f"dd={r.dd:.3f} sharpe={r.sharpe:.2f} "
                  f"ruin={r.ruin:.3f} heat={r.heat:.5f} "
                  f"max_heat={r.max_heat:.5f}  post={s:.5f}")
    except Exception as exc:
        if verbose:
            print(f"    risk_budget[v10.12c]: skipped ({exc.__class__.__name__})")

    r.s_risk_budget = s
    r.s_final       = s

    if verbose:
        print(f"    FINAL: size={s:.5f}  chain: "
              f"kelly={r.s_kelly:.5f} "
              f"→policy={r.s_policy:.5f} "
              f"→meta={r.s_meta:.5f} "
              f"→corr={r.s_corr:.5f} "
              f"→VaR={r.s_var:.5f} "
              f"→eq={r.s_exec_q:.5f} "
              f"→rb={r.s_risk_budget:.5f}")

    # ── 10. Monotone check ────────────────────────────────────────────────────
    # After the corr stage, every subsequent multiplier must be ≤1.  Policy and
    # meta are exempt — both are allowed to scale up (by design).
    _TIGHTEN_STAGES = [
        ("corr→VaR",      r.s_corr,        r.s_var),
        ("VaR→exec_q",    r.s_var,         r.s_exec_q),
        ("exec_q→rb",     r.s_exec_q,      r.s_risk_budget),
        ("rb→final",      r.s_risk_budget, r.s_final),
    ]
    for label, before, after in _TIGHTEN_STAGES:
        if before > 1e-9 and after > before * 1.001:
            r.monotone_ok = False
            r.monotone_violations.append(
                f"{label}: {before:.5f}→{after:.5f} "
                f"(+{(after / before - 1) * 100:.1f}%)"
            )

    return r


# ── Warm start verification ────────────────────────────────────────────────────

def _verify_warm_start() -> None:
    print(f"\n{'=' * 68}")
    print("WARM START VERIFICATION")
    print(f"{'=' * 68}")
    try:
        from src.services.risk_engine  import _peak_equity, _rb_ema
        from src.services.learning_event import METRICS

        stored_peak = float(METRICS.get("equity_peak", 0.0) or 0.0)
        stored_dd   = float(METRICS.get("drawdown",    0.0) or 0.0)

        peak_ok = abs(_peak_equity[0] - stored_peak) < 1e-6 or stored_peak == 0.0
        print(f"  METRICS['equity_peak']   = {stored_peak:.6f}")
        print(f"  _peak_equity[0]          = {_peak_equity[0]:.6f}  "
              f"{'[OK]' if peak_ok else '[MISMATCH — check REC-1 seed]'}")

        print(f"  METRICS['drawdown']      = {stored_dd:.6f}")
        if stored_dd > 0:
            expected_seed = max(0.3, min(1.0, 1.0 - stored_dd * 2.0))
            if _rb_ema[0] is None:
                ema_note = "[WARN: None — module loaded but seed failed?]"
            else:
                ema_note = (f"current={_rb_ema[0]:.4f}  "
                            f"seed_expected≈{expected_seed:.4f}  "
                            f"[drift normal after audit calls]")
        else:
            ema_note = (f"current={_rb_ema[0]:.4f}" if _rb_ema[0] is not None
                        else "[None — initialised on first portfolio_risk_budget() call]")
        print(f"  _rb_ema[0]               = {ema_note}")

    except Exception as exc:
        print(f"  [ERROR] {exc}")


# ── Summary report ─────────────────────────────────────────────────────────────

def _print_summary(results: list[AuditResult]) -> None:
    print(f"\n{'=' * 68}")
    print("AUDIT SUMMARY REPORT")
    print(f"{'=' * 68}")

    passed  = [r for r in results if r.passed]
    total   = len(results)

    print(f"\n  Trades audited         : {total}")
    print(f"  Passed to execution    : {len(passed)}")
    print(f"  Blocked                : {total - len(passed)}")

    if passed:
        sizes = [r.s_final    for r in passed]
        rbs   = [r.risk_budget for r in passed]
        eqs   = [r.exec_quality for r in passed]

        print(f"\n  ── Size distribution ───────────────────────────────")
        print(f"  Min final size         : {min(sizes):.5f}")
        print(f"  Max final size         : {max(sizes):.5f}")
        print(f"  Avg final size         : {sum(sizes)/len(sizes):.5f}")

        print(f"\n  ── Risk budget ─────────────────────────────────────")
        print(f"  Avg risk_budget        : {sum(rbs)/len(rbs):.3f}")
        print(f"  Max risk_budget        : {max(rbs):.3f}")
        print(f"  Min risk_budget        : {min(rbs):.3f}")

        print(f"\n  ── Execution quality ───────────────────────────────")
        print(f"  Avg exec_quality       : {sum(eqs)/len(eqs):.3f}")
        print(f"  Min exec_quality       : {min(eqs):.3f}")

    # Heat violations (heat > max_heat in existing book)
    heat_over = [r for r in results if r.max_heat > 0 and r.heat > r.max_heat]
    print(f"\n  ── Heat violations (existing book) ─────────────────")
    print(f"  heat > max_heat        : {len(heat_over)}")
    for r in heat_over[:5]:
        print(f"    [{r.idx:02d}] {r.sym} {r.action}  "
              f"heat={r.heat:.5f}  max={r.max_heat:.5f}")

    # Low exec quality
    low_eq = [r for r in passed if r.exec_quality < 0.60]
    print(f"  exec_quality < 0.60    : {len(low_eq)}")
    for r in low_eq[:5]:
        print(f"    [{r.idx:02d}] {r.sym} {r.action}  "
              f"eq={r.exec_quality:.3f}  spread={r.spread:.5f}")

    # Soft penalties
    print(f"\n  ── Soft penalties applied ──────────────────────────")
    print(f"  velocity_pen < 1.0     : {sum(1 for r in results if r.velocity_pen < 1.0)}")
    print(f"  streak_pen < 1.0       : {sum(1 for r in results if r.streak_pen   < 1.0)}")
    print(f"  combo_pen < 1.0        : {sum(1 for r in results if r.combo_pen    < 1.0)}")
    print(f"  emergency mode         : {sum(1 for r in results if r.emergency)}")

    # Block breakdown
    print(f"\n  ── Block breakdown ─────────────────────────────────")
    print(f"  RDE                    : {sum(1 for r in results if not r.rde_pass)}")
    print(f"  exec_quality HARD_SKIP : {sum(1 for r in results if r.eq_skip)}")
    print(f"  net_edge               : {sum(1 for r in results if r.net_edge_blocked)}")
    print(f"  cost_guard             : {sum(1 for r in results if r.cost_guard_blocked)}")
    print(f"  heat_limit             : {sum(1 for r in results if r.heat_blocked)}")

    # Monotone violations (reduce-only from corr stage onward)
    mono_fail = [r for r in passed if not r.monotone_ok]
    print(f"\n  ── Monotone check (reduce-only: corr→final) ────────")
    print(f"  Violations             : {len(mono_fail)}")
    for r in mono_fail[:5]:
        print(f"    [{r.idx:02d}] {r.sym}: {'; '.join(r.monotone_violations)}")

    print(f"\n{'=' * 68}")


# ── Public entry point ────────────────────────────────────────────────────────

def run_audit(
    n_trades: int = 40,
    verbose:  bool = True,
    seed:     int  = 42,
) -> list[AuditResult]:
    """
    Run pre-live audit on `n_trades` synthetic signals.

    Parameters
    ----------
    n_trades : Number of synthetic trades to simulate.
    verbose  : Per-trade verbose logging (disable with --quiet).
    seed     : RNG seed for reproducibility.
    """
    print(f"{'=' * 68}")
    print(f"PRE-LIVE AUDIT  (V10.12c)  n={n_trades}  seed={seed}")
    print(f"{'=' * 68}")

    signals   = _make_signals(n_trades, seed)
    results:  list[AuditResult]  = []
    positions: dict[str, Any]    = {}   # simulated open position book

    for i, sig in enumerate(signals):
        r = _audit_one(sig, positions, idx=i + 1, verbose=verbose)
        results.append(r)

        # Add passing trades to the simulated book (cap at 3 positions)
        if r.passed and len(positions) < 3 and sig["sym"] not in positions:
            positions[sig["sym"]] = {
                "action":  sig["action"],
                "size":    r.s_final,
                "entry":   sig["price"],
                "sl":      sig["price"] * (0.996 if sig["action"] == "BUY" else 1.004),
                "sl_move": 0.004,      # consistent with _proxy in trade_executor
                "tp_move": 0.010,
                "live_pnl": 0.0,
                "regime":   sig["regime"],
            }
        # Rotate oldest position every 5 trades — simulates normal turnover
        if i > 0 and i % 5 == 0 and positions:
            positions.pop(next(iter(positions)))

    _verify_warm_start()
    _print_summary(results)
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CryptoMaster pre-live audit (V10.12c)")
    ap.add_argument("--trades", type=int, default=40,  help="Number of synthetic trades")
    ap.add_argument("--quiet",  action="store_true",   help="Suppress per-trade logs")
    ap.add_argument("--seed",   type=int, default=42,  help="RNG seed for reproducibility")
    args = ap.parse_args()
    run_audit(n_trades=args.trades, verbose=not args.quiet, seed=args.seed)
