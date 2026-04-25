"""
V10.13x.2: SCRATCH_EXIT forensic analytics & Health Decomposition v2

Dává odpovědi na kritické otázky:
1. Proč je SCRATCH_EXIT tak dominantní (76% obchodů)?
2. Proč je ekonomicky destruktivní?
3. Jaká je skutečná health rozložena do komponent?
4. Kde přesně ztrácí systém peníze?

Forensic breakdowns:
- SCRATCH_EXIT by symbol, regime, hold time, PnL bucket, MFE/MAE
- Expectancy decomposition (all vs decisive, by exit type, by symbol)
- Health v2: 8 granulárních komponent místo jedné komprimované metriky
- Scratch pressure alerts: upozornění když scratch > 60%, negative net

Usage:
  from src.services.scratch_forensics import scratch_report, health_decomposition_v2

  report = scratch_report()  # Vrátí detailní analýzu SCRATCH_EXIT
  health = health_decomposition_v2()  # Vrátí rozbitou health s komponentami
"""

import logging
import numpy as np
from collections import defaultdict

log = logging.getLogger(__name__)

# Track scratch-exit details pro analýzu
_scratch_details = []  # List of {sym, reg, hold_time_sec, pnl, mfe, mae, reason, ...}


def record_scratch_exit(sym: str, reg: str, hold_time_sec: float, pnl: float,
                        mfe: float, mae: float, reason: str = "unknown", **kwargs):
    """
    Zaznamenat SCRATCH_EXIT pro forensic analýzu.

    sym: symbol (BTCUSDT)
    reg: režim (BULL_TREND)
    hold_time_sec: jak dlouho byla pozice otevřená
    pnl: uzavřený PnL
    mfe: maximum favorable excursion (max pnl před uzavřením)
    mae: maximum adverse excursion (max loss před uzavřením)
    reason: důvod scratch close (e.g., "micro_close_hit", "flat_timeout", etc.)
    **kwargs: další fields (entry_ws, exit_price, entry_price, etc.)
    """
    detail = {
        "sym": sym,
        "reg": reg,
        "hold_time": hold_time_sec,
        "pnl": float(pnl),
        "mfe": float(mfe),
        "mae": float(mae),
        "reason": reason,
    }
    detail.update(kwargs)
    _scratch_details.append(detail)

    # Keep only last 500 scratch exits (don't bloat memory)
    if len(_scratch_details) > 500:
        del _scratch_details[:-500]


def scratch_report() -> dict:
    """
    V10.13x.2 PRIORITY 1: Generate forensic report na SCRATCH_EXIT.

    Returns dict:
    {
        "total_count": int,
        "total_pct": float,  # % of all trades
        "net_pnl": float,
        "avg_pnl": float,
        "median_pnl": float,
        "avg_hold_time": float,
        "avg_mfe": float,  # Avg MFE before scratch close
        "avg_mae": float,
        "by_symbol": {sym: {...breakdowns...}},
        "by_regime": {reg: {...breakdowns...}},
        "by_hold_bucket": {bucket: {...}},  # e.g., "0-30s", "30-60s", "1-5m", "5m+"
        "by_pnl_bucket": {bucket: {...}},  # e.g., "loss", "micro", "small_win"
        "mfe_follow_up": dict,  # Kolik scratch exitů bylo po pozitivní excursion?
        "negative_after_positive": int,  # Scratch po MFE > 0.0001
    }
    """
    if not _scratch_details:
        return {
            "total_count": 0,
            "status": "NO_DATA",
        }

    # Basic stats
    total = len(_scratch_details)
    pnls = [d["pnl"] for d in _scratch_details]
    net_pnl = sum(pnls)
    avg_pnl = np.mean(pnls)
    median_pnl = float(np.median(pnls))

    # Hold times (in seconds)
    hold_times = [d["hold_time"] for d in _scratch_details if d["hold_time"] > 0]
    avg_hold_time = float(np.mean(hold_times)) if hold_times else 0.0

    # MFE/MAE stats
    mfes = [d["mfe"] for d in _scratch_details]
    maes = [d["mae"] for d in _scratch_details]
    avg_mfe = float(np.mean(mfes)) if mfes else 0.0
    avg_mae = float(np.mean(maes)) if maes else 0.0

    # By symbol breakdown
    by_symbol = defaultdict(lambda: {"count": 0, "pnl": 0.0, "mfes": [], "hold": []})
    for d in _scratch_details:
        sym = d["sym"]
        by_symbol[sym]["count"] += 1
        by_symbol[sym]["pnl"] += d["pnl"]
        by_symbol[sym]["mfes"].append(d["mfe"])
        by_symbol[sym]["hold"].append(d["hold_time"])

    by_sym_final = {}
    for sym, data in by_symbol.items():
        by_sym_final[sym] = {
            "count": data["count"],
            "net_pnl": round(data["pnl"], 8),
            "avg_pnl": round(data["pnl"] / data["count"], 8) if data["count"] else 0.0,
            "avg_mfe": round(float(np.mean(data["mfes"])), 8) if data["mfes"] else 0.0,
            "avg_hold": round(float(np.mean(data["hold"])), 2) if data["hold"] else 0.0,
        }

    # By regime breakdown
    by_regime = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for d in _scratch_details:
        reg = d.get("reg", "UNKNOWN")
        by_regime[reg]["count"] += 1
        by_regime[reg]["pnl"] += d["pnl"]

    by_reg_final = {}
    for reg, data in by_regime.items():
        by_reg_final[reg] = {
            "count": data["count"],
            "net_pnl": round(data["pnl"], 8),
            "avg_pnl": round(data["pnl"] / data["count"], 8) if data["count"] else 0.0,
        }

    # By hold time bucket (0-30s, 30-60s, 1-5m, 5m+)
    def hold_bucket(t_sec: float) -> str:
        if t_sec < 30:
            return "0-30s"
        elif t_sec < 60:
            return "30-60s"
        elif t_sec < 300:
            return "1-5m"
        else:
            return "5m+"

    by_hold = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for d in _scratch_details:
        bucket = hold_bucket(d["hold_time"])
        by_hold[bucket]["count"] += 1
        by_hold[bucket]["pnl"] += d["pnl"]

    by_hold_final = {}
    for bucket, data in by_hold.items():
        by_hold_final[bucket] = {
            "count": data["count"],
            "net_pnl": round(data["pnl"], 8),
            "avg_pnl": round(data["pnl"] / data["count"], 8) if data["count"] else 0.0,
        }

    # By PnL bucket (loss, micro [0-0.0005], small [0.0005-0.002], medium [0.002+])
    def pnl_bucket(pnl_val: float) -> str:
        if pnl_val < 0:
            return "loss"
        elif pnl_val < 0.0005:
            return "micro"
        elif pnl_val < 0.002:
            return "small"
        else:
            return "medium"

    by_pnl = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for d in _scratch_details:
        bucket = pnl_bucket(d["pnl"])
        by_pnl[bucket]["count"] += 1
        by_pnl[bucket]["pnl"] += d["pnl"]

    by_pnl_final = {}
    for bucket, data in by_pnl.items():
        by_pnl_final[bucket] = {
            "count": data["count"],
            "net_pnl": round(data["pnl"], 8),
            "avg_pnl": round(data["pnl"] / data["count"], 8) if data["count"] else 0.0,
        }

    # MFE follow-up: kolik scratch exitů bylo po pozitivní excursion?
    negative_after_positive = sum(1 for d in _scratch_details if d["mfe"] > 0.0001 and d["pnl"] < 0)

    return {
        "total_count": total,
        "total_pct": round(100.0 * total / max(total, 1), 1),  # would need total trades
        "net_pnl": round(net_pnl, 8),
        "avg_pnl": round(avg_pnl, 8),
        "median_pnl": round(median_pnl, 8),
        "avg_hold_time_sec": round(avg_hold_time, 2),
        "avg_mfe": round(avg_mfe, 8),
        "avg_mae": round(avg_mae, 8),
        "by_symbol": by_sym_final,
        "by_regime": by_reg_final,
        "by_hold_bucket": by_hold_final,
        "by_pnl_bucket": by_pnl_final,
        "negative_after_positive": negative_after_positive,  # Scratch losses po MFE > 0
    }


def expectancy_decomposition(trades_data: dict = None) -> dict:
    """
    V10.13x.2 PRIORITY 2: Expectancy scope decomposition.

    Rozdělit expectancy na:
    - all_closed: všechny uzavřené trades
    - decisive_only: trades kde WR je jasný (ne flats/timeouts)
    - by_symbol: per symbol
    - by_exit_type: per exit type (SCRATCH_EXIT, TP, SL, timeout, etc.)

    Vysvětluje proč canonical WR=77% ale PnL je negativní.
    """
    # TODO: Integrate with learning_event.py data
    # For now, return stub
    return {
        "status": "PENDING_INTEGRATION",
        "note": "Requires trade-level PnL data from trade_executor and learning_event",
    }


def health_decomposition_v2() -> dict:
    """
    V10.13x.2 PRIORITY 3: Health decomposition v2 — 8 granulárních komponent.

    Místo jedné komprimované metriky (0.001), vrátit strukturu:
    {
        "overall": float,  # Final health score
        "status": "GOOD|WEAK|BAD",
        "components": {
            "edge_strength": float,        # Průměrný EV across pairs
            "convergence": float,          # % pairs s conv > 0.5
            "calibration": float,          # Signal quality consistency
            "stability": float,            # Edge consistency WR
            "breadth": float,              # % symbol coverage
            "exit_quality": float,         # Win ratio on decisive exits
            "scratch_penalty": float,      # -penalty if scratch > 60%
            "bootstrap_penalty": float,    # -penalty if < 50 trades
        },
        "warnings": [list of strings],
    }
    """
    try:
        from src.services.learning_monitor import (
            lm_count, lm_ev_hist, lm_wr_hist, lm_pnl_hist, lm_convergence,
            lm_edge_strength, lm_bandit_focus
        )
    except Exception as e:
        log.warning(f"[HEALTH_V2] Could not import learning_monitor: {e}")
        return {"status": "ERROR", "error": str(e)}

    warnings = []
    components = {}

    # Component 1: Edge strength (mean of positive EVs)
    positive_evs = []
    for (sym, reg), n in lm_count.items():
        if n >= 5:
            ev = lm_edge_strength(sym, reg)
            if ev > 0:
                positive_evs.append(ev)
    components["edge_strength"] = float(np.mean(positive_evs)) if positive_evs else 0.0

    if components["edge_strength"] < 0.001:
        warnings.append("edge_too_weak: mean edge < 0.001")

    # Component 2: Convergence (% pairs s convergence > 0.5)
    pairs_converged = 0
    pairs_total_n5 = 0
    for (sym, reg), n in lm_count.items():
        if n >= 5:
            pairs_total_n5 += 1
            conv = lm_convergence(sym, reg)
            if conv > 0.5:
                pairs_converged += 1

    components["convergence"] = (pairs_converged / pairs_total_n5) if pairs_total_n5 > 0 else 0.0

    if components["convergence"] < 0.3:
        warnings.append(f"low_convergence: only {pairs_converged}/{pairs_total_n5} pairs converged")

    # Component 3: Stability (Sharpe-like: mean/std of WR across pairs)
    wr_values = []
    for (sym, reg), n in lm_count.items():
        if n >= 10:
            wr_lst = lm_wr_hist.get((sym, reg), [])
            if wr_lst:
                wr_values.append(wr_lst[-1])

    if wr_values:
        wr_mean = float(np.mean(wr_values))
        wr_std = float(np.std(wr_values))
        # Stability: if std is low relative to mean, signal is stable
        components["stability"] = min(1.0, wr_mean / max(wr_std + 0.01, 0.01))
    else:
        components["stability"] = 0.0

    # Component 4: Breadth (how many unique symbols trading well)
    pairs_n10 = sum(1 for n in lm_count.values() if n >= 10)
    total_pairs = len(lm_count)
    components["breadth"] = (pairs_n10 / max(total_pairs, 1)) if total_pairs > 0 else 0.0

    if components["breadth"] < 0.3:
        warnings.append(f"low_breadth: only {pairs_n10} pairs with n≥10")

    # Component 5: Exit quality (ratio of profitable exits to total)
    # TODO: Requires close_reasons and PnL breakdown
    components["exit_quality"] = 0.0  # Stub

    # Component 6: Calibration (signal consistency across regimes)
    # TODO: Requires regime breakdown analysis
    components["calibration"] = 0.0  # Stub

    # Component 7: Scratch penalty
    scratch_data = scratch_report()
    scratch_penalty = 0.0
    if scratch_data.get("total_count", 0) > 0:
        total_trades = sum(lm_count.values())
        scratch_pct = scratch_data["total_count"] / max(total_trades, 1)
        if scratch_pct > 0.6:
            scratch_penalty = -0.2  # Heavy penalty if > 60%
            warnings.append(f"scratch_dominance: {scratch_pct:.1%} of trades are SCRATCH_EXIT")
        if scratch_data["net_pnl"] < 0:
            scratch_penalty = min(scratch_penalty - 0.1, -0.3)
            warnings.append(f"scratch_losses: net PnL {scratch_data['net_pnl']:.8f}")
    components["scratch_penalty"] = scratch_penalty

    # Component 8: Bootstrap penalty
    total_trades = sum(lm_count.values())
    bootstrap_penalty = 0.0
    if total_trades < 50:
        bootstrap_penalty = -0.1
        warnings.append(f"bootstrap_phase: only {total_trades} trades")
    elif total_trades < 100:
        bootstrap_penalty = -0.05
    components["bootstrap_penalty"] = bootstrap_penalty

    # Calculate overall health as weighted mean of positive components
    # Skip penalty components in the base score, add them after
    base_components = [
        components["edge_strength"],
        components["convergence"],
        components["stability"],
        components["breadth"],
    ]
    base_health = float(np.mean(base_components)) if base_components else 0.0

    # Apply penalties
    final_health = max(0.0, base_health + scratch_penalty + bootstrap_penalty)

    # Determine status
    if final_health >= 0.3:
        status = "GOOD"
    elif final_health >= 0.1:
        status = "WEAK"
    else:
        status = "BAD"

    return {
        "overall": round(final_health, 4),
        "status": status,
        "components": {k: round(v, 4) for k, v in components.items()},
        "warnings": warnings,
    }


def scratch_pressure_alert() -> dict:
    """
    V10.13x.2 PRIORITY 4: Scratch pressure alerts.

    Returns:
    {
        "alert_level": "OK|WARNING|CRITICAL",
        "scratch_share": float,  # % of total
        "scratch_net_pnl": float,
        "scratch_impact": str,  # Description
    }
    """
    try:
        from src.services.learning_monitor import lm_count
    except Exception:
        return {"alert_level": "ERROR"}

    total_trades = sum(lm_count.values())
    if total_trades == 0:
        return {"alert_level": "NO_DATA"}

    scratch = scratch_report()
    scratch_count = scratch.get("total_count", 0)
    scratch_pct = scratch_count / total_trades
    scratch_net = scratch.get("net_pnl", 0.0)

    alert_level = "OK"
    impact = ""

    if scratch_pct > 0.75:
        alert_level = "CRITICAL"
        impact = f"CRITICAL: {scratch_pct:.0%} of trades are SCRATCH_EXIT (net {scratch_net:.8f})"
    elif scratch_pct > 0.60:
        alert_level = "WARNING"
        impact = f"WARNING: {scratch_pct:.0%} scratch share (net {scratch_net:.8f})"
    elif scratch_net < 0:
        alert_level = "WARNING"
        impact = f"WARNING: scratch net PnL negative ({scratch_net:.8f})"

    return {
        "alert_level": alert_level,
        "scratch_share": round(scratch_pct, 3),
        "scratch_net_pnl": round(scratch_net, 8),
        "scratch_impact": impact,
    }
