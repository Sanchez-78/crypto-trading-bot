"""
Live execution-engine dashboard layer.

Reads from execution.py (risk_ev, equity, bandit/bayes state) and
diagnostics.py (failure_score, sharpe, winrate, avg_edge) to provide
a unified observability view that supplements bot2/main.py print_status().

dashboard_control(positions) → float:
  1.0  normal sizing
  0.5  degradation detected (failure_score > 1.5)
  0.0  critical — block new trades  (failure_score > 3.0)
"""

import numpy as np

from src.services.execution   import _equity, _equity_peak, risk_ev
from src.services.diagnostics import (
    failure_score, sharpe, winrate, avg_edge, max_drawdown,
)


# ── State snapshot ─────────────────────────────────────────────────────────────

def dashboard_snapshot(positions):
    """
    Snapshot of execution-engine state for observability.
    positions: dict from trade_executor._positions
      {sym: {"signal": {...}, "size": float, ...}}
    """
    eq   = _equity[0]
    peak = _equity_peak[0]

    snap = {
        "equity":      eq,
        "drawdown":    (peak - eq) / max(peak, 1e-9),
        "exposure":    sum(p["size"] for p in positions.values()),
        "n_positions": len(positions),
    }

    per_sym = {}
    for pos in positions.values():
        sym = pos["signal"]["symbol"]
        reg = pos["signal"].get("regime", "RANGING")
        per_sym[sym] = {
            "ev":   risk_ev(sym, reg),
            "size": pos["size"],
            "reg":  reg,
        }
    snap["symbols"] = per_sym
    snap["failure"] = failure_score(positions)
    return snap


# ────────────────────────────────────────────────────────────────────────────────
# PATCH 3.6: Simplified Snapshot Builder — Unified state snapshot
# ────────────────────────────────────────────────────────────────────────────────
def build_snapshot_minimal(positions, metrics=None):
    """PATCH 3.6: Build minimal snapshot for atomic rendering.
    
    Consolidates execution state, positions, and learning metrics into
    a single immutable snapshot suitable for deduplication and rendering.
    
    Args:
        positions: dict of open positions
        metrics: optional dict of current metrics
    
    Returns:
        dict: Unified snapshot for rendering
    """
    eq = _equity[0]
    peak = _equity_peak[0]
    
    snapshot = {
        "timestamp": __import__('time').time(),
        "system": {
            "equity": round(eq, 8),
            "drawdown": round((peak - eq) / max(peak, 1e-9), 4),
            "exposure": round(sum(p.get("size", 0) for p in positions.values()), 6),
            "positions": len(positions),
        },
        "symbols": {
            pos["signal"]["symbol"]: {
                "size": round(pos.get("size", 0), 6),
                "regime": pos["signal"].get("regime", "RANGING"),
            }
            for pos in positions.values()
        },
    }
    
    if metrics:
        snapshot["metrics"] = metrics
    
    return snapshot


# ── Metrics stream ─────────────────────────────────────────────────────────────

def dashboard_metrics():
    return {
        "sharpe":   sharpe(),
        "winrate":  winrate(),
        "avg_edge": avg_edge(),
        "max_dd":   max_drawdown(),
    }


# ── CLI print ──────────────────────────────────────────────────────────────────

def print_dashboard(positions):
    snap = dashboard_snapshot(positions)
    met  = dashboard_metrics()

    fscore = snap["failure"]
    fscore_tag = ("CRITICAL" if fscore > 3.0
                  else "WARN" if fscore > 1.5
                  else "OK")

    print(f"\n=== EXECUTION ENGINE ===")
    print(f"  Equity:   {snap['equity']:.6f}  |  DD: {snap['drawdown']:.2%}")
    print(f"  Exposure: {snap['exposure']:.3f}  |  Positions: {snap['n_positions']}")
    print(f"  Sharpe:   {met['sharpe']:.3f}  |  WR: {met['winrate']:.2%}  "
          f"|  Edge: {met['avg_edge']:.5f}  |  MaxDD: {met['max_dd']:.2%}")
    print(f"  Failure:  {fscore:.3f}  [{fscore_tag}]")
    for sym, data in snap["symbols"].items():
        ev_tag = f"+{data['ev']:.4f}" if data["ev"] >= 0 else f"{data['ev']:.4f}"
        print(f"    {sym:<12} {data['reg']:<12} EV:{ev_tag}  Size:{data['size']:.4f}")


# ── Alerts + control ───────────────────────────────────────────────────────────

def dashboard_alerts(positions):
    """
    Returns 'HALT', 'WARN', or 'OK' based on failure_score.
    Prints a warning line when degradation is detected.
    """
    score = failure_score(positions)
    if score > 3.0:
        print(f"  [DASHBOARD] HALT — failure_score={score:.2f} (critical)")
        return "HALT"
    if score > 1.5:
        print(f"  [DASHBOARD] WARN — failure_score={score:.2f} (degradation)")
        return "WARN"
    return "OK"


def dashboard_control(positions):
    """
    Sizing multiplier derived from failure_score.
      OK   → 1.0  (full sizing)
      WARN → 0.5  (half sizing)
      HALT → 0.0  (block all new trades)
    Called from trade_executor.handle_signal to gate position sizing.
    """
    state = dashboard_alerts(positions)
    if state == "HALT":
        return 0.0
    if state == "WARN":
        return 0.5
    return 1.0


# ── Loop integration ───────────────────────────────────────────────────────────

def dashboard_loop(positions):
    """
    Print execution dashboard + return sizing control multiplier.
    Intended to be called in bot2/main.py main loop alongside print_status().
    """
    print_dashboard(positions)
    return dashboard_control(positions)
