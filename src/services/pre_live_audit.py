"""
pre_live_audit.py — Audit + Replay + Regression Validation System (V10.12c)

Simulates or replays signals through the full sizing chain, exports structured
JSON, compares against a baseline for regression detection, and acts as a
CI/CD gate.  Read-only: does NOT modify any production state or database.

    python -m src.services.pre_live_audit [OPTIONS]

Options:
    --trades N          Number of synthetic trades (default 40)
    --quiet             Suppress per-trade verbose logs
    --seed N            RNG seed for reproducibility (default 42)
    --replay            Load real closed trades from Firestore instead of synthetic
    --out PATH          Write full JSON result to file
    --baseline PATH     Compare current run against previous JSON export
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
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
            "_source":         "synthetic",
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


def _net_edge(ev: float, spread: float, fee_rt: float = 0.0015) -> dict[str, float]:
    """V10.13u Fix 5: Return detailed net-edge decomposition instead of scalar.

    Returns dict with:
    - gross_ev: raw EV input
    - spread_cost: cost of half-spread (one-way trade assumption)
    - fee_cost: cost of exchange fees
    - slippage_cost: estimated slippage (currently 0, but placeholder for future)
    - net_ev: final EV after all costs
    """
    spread_cost = spread * 0.5
    slippage_cost = 0.0  # Not directly modeled; spread proxy used
    net_ev = ev - spread_cost - fee_rt - slippage_cost

    return {
        "gross_ev":      ev,
        "spread_cost":   spread_cost,
        "fee_cost":      fee_rt,
        "slippage_cost": slippage_cost,
        "net_ev":        net_ev,
    }


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

    # V10.13u Fix 5: Net-edge decomposition for transparency
    net_edge_gross_ev:      float = 0.0
    net_edge_spread_cost:   float = 0.0
    net_edge_fee_cost:      float = 0.0
    net_edge_slippage_cost: float = 0.0
    net_edge_final:         float = 0.0

    # Monotone check
    monotone_ok:         bool      = True
    monotone_violations: list[str] = field(default_factory=list)

    # Provenance
    source: str = "synthetic"   # "synthetic" | "replay"
    branch: str = "normal"      # PATCH 6: "normal" | "forced" | "micro"

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

    r = AuditResult(
        idx=idx, sym=sym, action=action, regime=regime, price=price,
        source=signal.get("_source", "synthetic"),
    )

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
    # V10.13u Fix 5: Detailed decomposition instead of scalar
    net_decomp = _net_edge(ev, r.spread)
    net = net_decomp["net_ev"]

    # Store decomposition for audit insight
    r.net_edge_gross_ev = net_decomp["gross_ev"]
    r.net_edge_spread_cost = net_decomp["spread_cost"]
    r.net_edge_fee_cost = net_decomp["fee_cost"]
    r.net_edge_slippage_cost = net_decomp["slippage_cost"]
    r.net_edge_final = net

    if net <= 0.0:
        r.net_edge_blocked = True
        if verbose:
            print(f"    net_edge[audit]: BLOCKED  net={net:.5f}")
            print(f"      Components: ev={net_decomp['gross_ev']:.4f} "
                  f"- spread={net_decomp['spread_cost']:.4f} "
                  f"- fee={net_decomp['fee_cost']:.4f} "
                  f"- slip={net_decomp['slippage_cost']:.4f}")
            # Identify which factor is the primary blocker
            costs = [
                ("spread", net_decomp['spread_cost']),
                ("fee", net_decomp['fee_cost']),
                ("slippage", net_decomp['slippage_cost']),
            ]
            primary = max(costs, key=lambda x: x[1])
            print(f"      Primary block: {primary[0]} cost {primary[1]:.4f} "
                  f"exceeds EV {net_decomp['gross_ev']:.4f}")
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


# ── Summary metric builder ─────────────────────────────────────────────────────

def _build_summary(results: list[AuditResult]) -> dict[str, Any]:
    """PATCH 6: Compute canonical summary metrics split by branch (normal/forced/micro)."""
    # Overall summary
    passed  = [r for r in results if r.passed]
    total   = len(results)
    blocked = total - len(passed)

    sizes = [r.s_final     for r in passed]
    rbs   = [r.risk_budget for r in passed]
    eqs   = [r.exec_quality for r in passed]
    mono_v = sum(len(r.monotone_violations) for r in results)

    overall_summary = {
        "total_trades":        total,
        "blocked_trades":      blocked,
        "blocked_ratio":       round(blocked / max(total, 1), 4),
        "monotone_violations": mono_v,
        "avg_size":            round(sum(sizes) / max(len(sizes), 1), 6),
        "min_size":            round(min(sizes, default=0.0), 6),
        "max_size":            round(max(sizes, default=0.0), 6),
        "avg_risk_budget":     round(sum(rbs) / max(len(rbs), 1), 4),
        "max_risk_budget":     round(max(rbs, default=0.0), 4),
        "exec_quality_mean":   round(sum(eqs) / max(len(eqs), 1), 4),
    }

    # PATCH 6: Branch-split summary (normal/forced/recovery)
    normal_results = [r for r in results if r.branch in (None, "normal", "")]
    forced_results = [r for r in results if r.branch == "forced"]
    micro_results = [r for r in results if r.branch == "micro"]

    def make_branch_summary(branch_results, branch_name):
        """Build summary for a specific branch."""
        if not branch_results:
            return {f"{branch_name}_total": 0, f"{branch_name}_blocked": 0, f"{branch_name}_blocked_ratio": 0.0}
        branch_passed = [r for r in branch_results if r.passed]
        branch_total = len(branch_results)
        branch_blocked = branch_total - len(branch_passed)
        return {
            f"{branch_name}_total": branch_total,
            f"{branch_name}_passed": len(branch_passed),
            f"{branch_name}_blocked": branch_blocked,
            f"{branch_name}_blocked_ratio": round(branch_blocked / max(branch_total, 1), 4),
        }

    normal_summary = make_branch_summary(normal_results, "normal")
    forced_summary = make_branch_summary(forced_results, "forced")
    micro_summary = make_branch_summary(micro_results, "micro")

    # Merge all summaries
    overall_summary.update(normal_summary)
    overall_summary.update(forced_summary)
    overall_summary.update(micro_summary)

    return overall_summary


# ── JSON serialisation helper ──────────────────────────────────────────────────

def _safe_json(obj: Any) -> Any:
    """Recursively convert numpy scalars and non-serialisable types to JSON-safe equivalents."""
    if hasattr(obj, "item"):          # numpy scalar (float32, int64, …)
        return obj.item()
    if isinstance(obj, dict):
        return {k: _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_json(v) for v in obj]
    if isinstance(obj, bool):         # must come before int check
        return obj
    if isinstance(obj, float):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, str):
        return obj
    return str(obj)                   # last-resort: stringify unknown types


# ── JSON export ────────────────────────────────────────────────────────────────

def _export_json(
    results:  list[AuditResult],
    mode:     str,
    config:   dict[str, Any],
    path:     str,
) -> None:
    """
    Write full audit result to a JSON file.

    Output structure:
        version, timestamp, mode, config, summary, trades[]
    """
    summary = _build_summary(results)
    trades  = [_safe_json(dataclasses.asdict(r)) for r in results]
    payload: dict[str, Any] = {
        "version":   "v10.12c",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "mode":      mode,
        "config":    config,
        "summary":   summary,
        "trades":    trades,
    }
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        print(f"[audit] exported → {path}")
    except Exception as exc:
        print(f"[audit] JSON export failed: {exc}")


# ── Replay loader ──────────────────────────────────────────────────────────────

def _load_replay_signals(n: int) -> list[dict] | None:
    """
    Load the last `n` closed trades from Firestore and convert them to the
    audit signal format expected by _audit_one().

    Returns None if Firestore is unavailable; caller falls back to synthetic.
    This function is strictly read-only — it makes no writes to the database.

    Field mapping (slim_trade schema → audit signal):
        symbol          → sym
        action          → action
        price           → price  (entry price)
        confidence      → confidence
        regime          → regime
        ws              → ws
        ev              → (used as confidence proxy when confidence missing)
        features        → features  (preserved verbatim)
        features.volatility → atr  (atr ≈ price × volatility × 2.0)
    """
    try:
        from src.services.firebase_client import init_firebase, load_history
        init_firebase()
        raw: list[dict] = load_history(limit=n) or []
        if not raw:
            print("[audit] replay unavailable, using synthetic fallback "
                  "(load_history returned empty)")
            return None

        signals: list[dict] = []
        for t in raw:
            sym    = str(t.get("symbol") or t.get("sym") or "BTCUSDT")
            action = str(t.get("action") or t.get("signal") or "BUY").upper()
            if action not in ("BUY", "SELL"):
                action = "BUY"

            price  = float(t.get("price") or t.get("entry_price") or 65000.0)
            if price <= 0:
                price = 65000.0

            regime = str(t.get("regime") or t.get("strategy") or "RANGING")
            if regime not in ("BULL_TREND", "BEAR_TREND", "RANGING",
                              "QUIET_RANGE", "HIGH_VOL"):
                regime = "RANGING"

            conf   = float(t.get("confidence") or t.get("ev") or 0.55)
            conf   = max(0.01, min(0.99, conf))
            ws     = float(t.get("ws") or 0.5)
            ws     = max(0.01, min(0.99, ws))

            feats: dict = {}
            raw_feats = t.get("features")
            if isinstance(raw_feats, dict):
                feats = {k: v for k, v in raw_feats.items()
                         if isinstance(v, (bool, int, float))}

            # Derive ATR from stored volatility feature (volatility ≈ atr_pct/2)
            volatility = float(feats.get("volatility", 0.0) or 0.0)
            atr = price * max(volatility * 2.0, 0.008)   # floor 0.8% ATR

            signals.append({
                "sym":             sym,
                "action":          action,
                "regime":          regime,
                "confidence":      conf,
                "price":           price,
                "atr":             atr,
                "features":        feats,
                "ws":              ws,
                "_is_replacement": False,
                "_recycling_pnl":  None,
                "_source":         "replay",
            })

        if not signals:
            print("[audit] replay unavailable, using synthetic fallback "
                  "(no valid signals after mapping)")
            return None

        return signals

    except Exception as exc:
        print(f"[audit] replay unavailable, using synthetic fallback "
              f"({exc.__class__.__name__}: {exc})")
        return None


# ── Regression comparison ──────────────────────────────────────────────────────

_REG_FAIL    = "FAIL"
_REG_WARNING = "WARNING"
_REG_OK      = "OK"


def _compare_baseline(
    current: dict[str, Any],
    baseline_path: str,
) -> tuple[bool, list[str]]:
    """
    Load a previous audit JSON and compare summary metrics against `current`.

    Returns
    -------
    passed : bool
        True if no FAIL conditions triggered.
    lines : list[str]
        Human-readable regression report lines ready for printing.

    Failure conditions (exit 1):
        - monotone_violations increased
        - blocked_ratio increased by >0.25
        - avg_risk_budget increased by >20%  (WARNING only, not FAIL)
    """
    lines: list[str] = []
    failed = False

    try:
        with open(baseline_path, "r", encoding="utf-8") as fh:
            baseline_doc = json.load(fh)
        bs: dict[str, Any] = baseline_doc.get("summary", {})
    except FileNotFoundError:
        lines.append(f"  [WARN] Baseline not found: {baseline_path}  (skipping comparison)")
        return True, lines
    except Exception as exc:
        lines.append(f"  [ERROR] Cannot load baseline: {exc}")
        return True, lines   # don't fail CI on unreadable baseline

    def _pct_str(old: float, new: float) -> str:
        if abs(old) < 1e-12:
            return "+∞%" if new > 0 else "0.0%"
        return f"{(new - old) / abs(old) * 100:+.1f}%"

    def _row(label: str, old: float, new: float, status: str) -> str:
        return (f"  {label:<22} {_pct_str(old, new):<10} "
                f"{old:.4f} → {new:.4f}   {status}")

    lines.append("")
    lines.append("REGRESSION CHECK:")

    # avg_size
    old_v = float(bs.get("avg_size",  0.0))
    new_v = float(current.get("avg_size", 0.0))
    lines.append(_row("avg_size:", old_v, new_v, _REG_OK))

    # max_size
    old_v = float(bs.get("max_size",  0.0))
    new_v = float(current.get("max_size", 0.0))
    lines.append(_row("max_size:", old_v, new_v, _REG_OK))

    # avg_risk_budget — WARNING at >20%, not a hard FAIL
    old_rb = float(bs.get("avg_risk_budget", 0.0))
    new_rb = float(current.get("avg_risk_budget", 0.0))
    rb_change_pct = abs((new_rb - old_rb) / max(abs(old_rb), 1e-9)) * 100
    rb_status = _REG_WARNING if rb_change_pct > 20.0 else _REG_OK
    lines.append(_row("risk_budget:", old_rb, new_rb, rb_status))

    # blocked_ratio — FAIL if increase > 0.25
    old_br = float(bs.get("blocked_ratio", 0.0))
    new_br = float(current.get("blocked_ratio", 0.0))
    br_delta = new_br - old_br
    br_status = _REG_FAIL if br_delta > 0.25 else _REG_OK
    if br_status == _REG_FAIL:
        failed = True
    delta_str = f"  (Δ+{br_delta:.2f})" if br_delta > 0 else ""
    lines.append(f"  {'blocked_ratio:':<22} {old_br:.2f} → {new_br:.2f}"
                 f"{delta_str:<12}   {br_status}")

    # exec_quality_mean — WARNING at >5% drop
    old_eq = float(bs.get("exec_quality_mean", 0.0))
    new_eq = float(current.get("exec_quality_mean", 0.0))
    eq_drop_pct = (old_eq - new_eq) / max(abs(old_eq), 1e-9) * 100
    eq_status = _REG_WARNING if eq_drop_pct > 5.0 else _REG_OK
    lines.append(_row("exec_quality:", old_eq, new_eq, eq_status))

    # monotone_violations — FAIL if increased
    old_mv = int(bs.get("monotone_violations", 0))
    new_mv = int(current.get("monotone_violations", 0))
    mv_status = _REG_FAIL if new_mv > old_mv else _REG_OK
    if mv_status == _REG_FAIL:
        failed = True
    lines.append(f"  {'monotone:':<22} {old_mv} → {new_mv}"
                 + (" " * 10) + f"   {mv_status}")

    return not failed, lines


# ── Summary report ─────────────────────────────────────────────────────────────

def _print_summary(results: list[AuditResult], mode: str = "synthetic") -> None:
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
    rde_blocks = sum(1 for r in results if not r.rde_pass)
    eq_blocks = sum(1 for r in results if r.eq_skip)
    net_blocks = sum(1 for r in results if r.net_edge_blocked)
    cost_blocks = sum(1 for r in results if r.cost_guard_blocked)
    heat_blocks = sum(1 for r in results if r.heat_blocked)

    print(f"  RDE                    : {rde_blocks}")
    print(f"  exec_quality HARD_SKIP : {eq_blocks}")
    print(f"  net_edge               : {net_blocks}")
    print(f"  cost_guard             : {cost_blocks}")
    print(f"  heat_limit             : {heat_blocks}")

    # V10.13u Fix 5: Net-edge decomposition breakdown
    if net_blocks > 0:
        net_blocked = [r for r in results if r.net_edge_blocked]
        spread_blocked = sum(1 for r in net_blocked if r.net_edge_spread_cost > r.net_edge_gross_ev)
        fee_blocked = sum(1 for r in net_blocked if r.net_edge_fee_cost > (r.net_edge_gross_ev - r.net_edge_spread_cost))
        slip_blocked = sum(1 for r in net_blocked if r.net_edge_slippage_cost > 0)

        print(f"\n  ── Net-edge decomposition ({net_blocks} blocked) ──")
        if spread_blocked > 0:
            print(f"    Primary blocker: SPREAD  {spread_blocked}/{net_blocks}")
        if fee_blocked > 0:
            print(f"    Primary blocker: FEE     {fee_blocked}/{net_blocks}")
        if slip_blocked > 0:
            print(f"    Primary blocker: SLIP    {slip_blocked}/{net_blocks}")

        avg_gross = sum(r.net_edge_gross_ev for r in net_blocked) / max(len(net_blocked), 1)
        avg_spread = sum(r.net_edge_spread_cost for r in net_blocked) / max(len(net_blocked), 1)
        avg_fee = sum(r.net_edge_fee_cost for r in net_blocked) / max(len(net_blocked), 1)
        print(f"    Avg gross_ev={avg_gross:.5f}  spread_cost={avg_spread:.5f}  fee={avg_fee:.5f}")

    # Monotone violations (reduce-only from corr stage onward)
    mono_fail = [r for r in passed if not r.monotone_ok]
    print(f"\n  ── Monotone check (reduce-only: corr→final) ────────")
    print(f"  Violations             : {len(mono_fail)}")
    for r in mono_fail[:5]:
        print(f"    [{r.idx:02d}] {r.sym}: {'; '.join(r.monotone_violations)}")

    print(f"\n{'=' * 68}")

    # ── Structured canonical summary block (Feature 6) ────────────────────────
    sm       = _build_summary(results)
    min_s    = sm["min_size"]
    avg_s    = sm["avg_size"]
    max_s    = sm["max_size"]
    avg_rb   = sm["avg_risk_budget"]
    max_rb   = sm["max_risk_budget"]
    blocked_n = sm["blocked_trades"]
    blocked_r = sm["blocked_ratio"]
    mono_v   = sm["monotone_violations"]

    print(f"\nSUMMARY[v10.12c]:")
    print(f"  trades={total}  mode={mode}")
    print(f"  size[min/avg/max]={min_s:.4f} / {avg_s:.4f} / {max_s:.4f}")
    print(f"  risk_budget[avg/max]={avg_rb:.2f} / {max_rb:.2f}")
    print(f"  blocked={blocked_n} ({blocked_r:.3f})")
    print(f"  monotone_violations={mono_v}")
    print(f"{'=' * 68}")


# ── Public entry point ────────────────────────────────────────────────────────

def run_audit(
    n_trades:      int  = 40,
    verbose:       bool = True,
    seed:          int  = 42,
    replay:        bool = False,
    out:           str | None = None,
    baseline:      str | None = None,
) -> tuple[list[AuditResult], bool]:
    """
    Run pre-live audit on synthetic or replayed signals.

    Parameters
    ----------
    n_trades  : Number of trades to audit.
    verbose   : Per-trade verbose logging.
    seed      : RNG seed (used for synthetic mode; ignored in replay).
    replay    : If True, load real closed trades from Firestore.
    out       : If set, write full JSON to this file path.
    baseline  : If set, compare summary against this JSON baseline.

    Returns
    -------
    results : list[AuditResult]
    ci_pass : bool — False if any CI failure condition triggered.
    """
    mode = "replay" if replay else "synthetic"
    print(f"{'=' * 68}")
    print(f"PRE-LIVE AUDIT  (V10.12c)  n={n_trades}  seed={seed}  mode={mode}")
    print(f"{'=' * 68}")

    # V10.13u: Log runtime version for audit traceability
    try:
        from src.services.version_info import format_runtime_marker
        print(f"{format_runtime_marker()}\n")
    except Exception:
        pass  # Fail silently if version_info unavailable

    # ── Signal acquisition ────────────────────────────────────────────────────
    signals: list[dict]
    if replay:
        loaded = _load_replay_signals(n_trades)
        if loaded is None:
            mode    = "synthetic"   # fallback logged inside _load_replay_signals
            signals = _make_signals(n_trades, seed)
        else:
            signals = loaded
    else:
        signals = _make_signals(n_trades, seed)

    # ── Audit loop ────────────────────────────────────────────────────────────
    results:   list[AuditResult] = []
    positions: dict[str, Any]    = {}   # simulated open position book

    for i, sig in enumerate(signals):
        r = _audit_one(sig, positions, idx=i + 1, verbose=verbose)
        results.append(r)

        # Add passing trades to the simulated book (cap at 3 positions)
        if r.passed and len(positions) < 3 and sig["sym"] not in positions:
            positions[sig["sym"]] = {
                "action":   sig["action"],
                "size":     r.s_final,
                "entry":    sig["price"],
                "sl":       sig["price"] * (0.996 if sig["action"] == "BUY" else 1.004),
                "sl_move":  0.004,      # consistent with _proxy in trade_executor
                "tp_move":  0.010,
                "live_pnl": 0.0,
                "regime":   sig["regime"],
            }
        # Rotate oldest position every 5 trades — simulates normal turnover
        if i > 0 and i % 5 == 0 and positions:
            positions.pop(next(iter(positions)))

    # ── Reports ───────────────────────────────────────────────────────────────
    _verify_warm_start()
    _print_summary(results, mode=mode)

    summary = _build_summary(results)

    # ── Regression comparison ─────────────────────────────────────────────────
    reg_pass = True
    if baseline:
        reg_pass, reg_lines = _compare_baseline(summary, baseline)
        for line in reg_lines:
            print(line)
        if not reg_pass:
            print("\n  [REGRESSION] One or more FAIL conditions triggered.")

    # ── JSON export ───────────────────────────────────────────────────────────
    if out:
        config: dict[str, Any] = {
            "trades": n_trades,
            "seed":   seed,
            "quiet":  not verbose,
            "replay": replay,
        }
        _export_json(results, mode, config, out)

    # ── CI/CD gate conditions ─────────────────────────────────────────────────
    mono_violations = summary["monotone_violations"]
    blocked_ratio   = summary["blocked_ratio"]

    ci_pass = True
    if mono_violations > 0:
        print(f"\n  [CI FAIL] monotone_violations={mono_violations} > 0")
        ci_pass = False
    if blocked_ratio > 0.80:
        print(f"\n  [CI FAIL] blocked_ratio={blocked_ratio:.3f} > 0.80")
        ci_pass = False
    if not reg_pass:
        ci_pass = False

    if ci_pass:
        print("\n  [CI] PASS")
    else:
        print("\n  [CI] FAIL")

    return results, ci_pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="CryptoMaster pre-live audit + replay + regression validator (V10.12c)"
    )
    ap.add_argument("--trades",   type=int,  default=40,
                    help="Number of trades to audit (default: 40)")
    ap.add_argument("--quiet",    action="store_true",
                    help="Suppress per-trade verbose logs")
    ap.add_argument("--seed",     type=int,  default=42,
                    help="RNG seed for synthetic mode (default: 42)")
    ap.add_argument("--replay",   action="store_true",
                    help="Load real closed trades from Firestore instead of synthetic")
    ap.add_argument("--out",      type=str,  default=None,
                    help="Write full JSON result to this file path")
    ap.add_argument("--baseline", type=str,  default=None,
                    help="Compare current run against this previous JSON export")
    args = ap.parse_args()

    _, passed = run_audit(
        n_trades  = args.trades,
        verbose   = not args.quiet,
        seed      = args.seed,
        replay    = args.replay,
        out       = args.out,
        baseline  = args.baseline,
    )
    sys.exit(0 if passed else 1)
