"""
PRIORITY 1: Canonical Metrics Unification — Single Source of Truth for Performance Metrics

Provides unified, consistent functions for:
  - Profit Factor (PF) — gross_wins / gross_losses
  - Win Rate (WR) — won / (won + lost)
  - Expectancy — mean pnl per trade
  - Exit breakdown — scratch %, TP %, timeout % of trade volume
  - Overall health — composite score across metrics

All components (dashboard, audit, economic gate, alerts) use these same functions.
This eliminates inconsistencies (e.g., dashboard 0.65 vs economic 4.93).

Usage:
  from src.services.canonical_metrics import (
      canonical_profit_factor, canonical_win_rate,
      canonical_expectancy, canonical_exit_breakdown,
      canonical_overall_health
  )
"""

import logging
from typing import Optional, Dict
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class MetricsSnapshot:
    """Immutable snapshot of canonical metrics at a point in time."""
    profit_factor: float
    win_rate: float
    total_trades: int
    won_trades: int
    lost_trades: int
    flat_trades: int
    total_net_pnl: float
    expectancy: float
    scratch_exit_ratio: float
    tp_exit_ratio: float
    timeout_exit_ratio: float
    avg_hold_seconds: float


def canonical_profit_factor(closed_trades: list[dict] = None) -> float:
    """
    Canonical profit factor: gross_wins / gross_losses.

    Matches dashboard MetricsEngine.compute_canonical_trade_stats() exactly.
    - If closed_trades provided: compute from those trades only.
    - If None: returns 0.0 (caller must provide trades for accurate PF).

    Args:
        closed_trades: List of trade dicts with 'net_pnl'. Required for accuracy.

    Returns:
        float: PF ratio. Uses MetricsEngine logic: gross_pnl / loss_sum.
    """
    if closed_trades is None or not closed_trades:
        return 0.0

    # Mirror MetricsEngine.compute_canonical_trade_stats() logic
    profits = [t.get("net_pnl", 0.0) for t in closed_trades]
    gross_pnl = sum(p for p in profits if p > 0)
    loss_sum = abs(sum(p for p in profits if p < 0))

    if loss_sum > 0:
        return gross_pnl / loss_sum
    elif gross_pnl > 0:
        return float("inf")
    else:
        return 1.0


def canonical_profit_factor_with_meta(closed_trades: list[dict] = None) -> dict:
    """
    V10.13u+4: Canonical PF with full diagnostics metadata.

    Returns exactly which source was used, how many trades, and the calculation details.
    Use this to verify Economic Health is using the dashboard's canonical source.

    Args:
        closed_trades: List of trade dicts. If None, returns empty source indicator.

    Returns:
        dict with: pf, source, closed_trades (count), wins, losses, gross_win, gross_loss, net_pnl
    """
    if closed_trades is None or not closed_trades:
        return {
            "pf": 0.0,
            "source": "none_provided",
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "gross_win": 0.0,
            "gross_loss": 0.0,
            "net_pnl": 0.0,
        }

    profits = [t.get("net_pnl", 0.0) for t in closed_trades]
    gross_pnl = sum(p for p in profits if p > 0)
    loss_sum = abs(sum(p for p in profits if p < 0))

    if loss_sum > 0:
        pf = gross_pnl / loss_sum
    elif gross_pnl > 0:
        pf = float("inf")
    else:
        pf = 1.0

    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p < 0)

    return {
        "pf": pf,
        "source": "canonical_closed_trades",
        "closed_trades": len(closed_trades),
        "wins": wins,
        "losses": losses,
        "gross_win": gross_pnl,
        "gross_loss": loss_sum,
        "net_pnl": sum(profits),
    }


def canonical_win_rate(closed_trades: list[dict] = None) -> float:
    """
    Canonical win rate: won / (won + lost).

    Uses canonical state (canonical_state.py) if available for authoritative counts.

    Args:
        closed_trades: List of trade dicts. If None, uses canonical_state.

    Returns:
        float: WR ratio (0.0 to 1.0). 0.5 if no data.
    """
    if closed_trades is None:
        try:
            from src.services.canonical_state import get_canonical_state
            state = get_canonical_state()
            trades_won = state.get("trades_won", 0)
            trades_lost = state.get("trades_lost", 0)
        except Exception:
            return 0.5
    else:
        trades_won = sum(1 for t in closed_trades if t.get("net_pnl", 0) > 0)
        trades_lost = sum(1 for t in closed_trades if t.get("net_pnl", 0) <= 0)

    total = trades_won + trades_lost
    if total == 0:
        return 0.5
    return trades_won / total


def canonical_expectancy(closed_trades: list[dict] = None) -> float:
    """
    Canonical expectancy: mean pnl per trade.

    Args:
        closed_trades: List of trade dicts with 'net_pnl'. If None, uses METRICS.

    Returns:
        float: Mean PnL per trade. 0.0 if no data.
    """
    if closed_trades is None:
        try:
            from src.services.learning_event import METRICS
            total_pnl = METRICS.get("net_pnl_total", 0.0)
            num_trades = METRICS.get("trades", 0)
        except Exception:
            return 0.0
    else:
        total_pnl = sum(t.get("net_pnl", 0.0) for t in closed_trades)
        num_trades = len(closed_trades)

    if num_trades == 0:
        return 0.0
    return total_pnl / num_trades


def canonical_exit_breakdown() -> Dict[str, float]:
    """
    Canonical exit type breakdown as % of total trade volume.

    Returns dict with:
      - scratch_ratio: (SCRATCH_EXIT + MICRO_EXIT) / total
      - tp_ratio: (TP + PARTIAL_TP_*) / total
      - timeout_ratio: (TIMEOUT_*) / total
      - sl_ratio: SL hits / total
      - trail_ratio: TRAIL hits / total
      - other_ratio: remaining / total

    Returns:
        Dict[str, float]: Exit type ratios (sum to 1.0)
    """
    try:
        from src.services.exit_attribution import get_exit_stats
        stats = get_exit_stats()
    except Exception:
        return {
            "scratch_ratio": 0.0,
            "tp_ratio": 0.0,
            "timeout_ratio": 0.0,
            "sl_ratio": 0.0,
            "trail_ratio": 0.0,
            "other_ratio": 1.0,
        }

    if not stats:
        return {
            "scratch_ratio": 0.0,
            "tp_ratio": 0.0,
            "timeout_ratio": 0.0,
            "sl_ratio": 0.0,
            "trail_ratio": 0.0,
            "other_ratio": 1.0,
        }

    total = sum(s["count"] for s in stats.values())
    if total == 0:
        return {
            "scratch_ratio": 0.0,
            "tp_ratio": 0.0,
            "timeout_ratio": 0.0,
            "sl_ratio": 0.0,
            "trail_ratio": 0.0,
            "other_ratio": 1.0,
        }

    scratch_count = sum(
        s["count"] for et, s in stats.items()
        if "SCRATCH" in et or "MICRO" in et
    )
    tp_count = sum(
        s["count"] for et, s in stats.items()
        if "TP" in et or ("PARTIAL" in et and "TP" in et)
    )
    timeout_count = sum(
        s["count"] for et, s in stats.items()
        if "TIMEOUT" in et
    )
    sl_count = stats.get("SL", {}).get("count", 0)
    trail_count = stats.get("TRAIL", {}).get("count", 0)
    other_count = total - scratch_count - tp_count - timeout_count - sl_count - trail_count

    return {
        "scratch_ratio": scratch_count / total if total > 0 else 0.0,
        "tp_ratio": tp_count / total if total > 0 else 0.0,
        "timeout_ratio": timeout_count / total if total > 0 else 0.0,
        "sl_ratio": sl_count / total if total > 0 else 0.0,
        "trail_ratio": trail_count / total if total > 0 else 0.0,
        "other_ratio": other_count / total if total > 0 else 0.0,
    }


def canonical_overall_health() -> Dict:
    """
    Composite health score across all canonical metrics.

    Returns dict with:
      - pf: profit factor (target > 1.5)
      - wr: win rate (target > 0.55)
      - expectancy: mean pnl (target > 0)
      - scratch_ratio: should be < 0.30 (81% is bad)
      - health_score: 0.0-1.0 composite
      - status: "EXCELLENT" | "GOOD" | "CAUTION" | "CRITICAL"

    Returns:
        Dict with health components and overall status
    """
    pf = canonical_profit_factor()
    wr = canonical_win_rate()
    exp = canonical_expectancy()
    exits = canonical_exit_breakdown()

    scratch_ratio = exits.get("scratch_ratio", 0.0)

    health_components = {
        "pf": pf,
        "wr": wr,
        "expectancy": exp,
        "scratch_ratio": scratch_ratio,
    }

    pf_score = min(1.0, max(0.0, (pf - 1.0) / 2.0))
    wr_score = max(0.0, (wr - 0.50) / 0.15)
    scratch_score = max(0.0, 1.0 - (scratch_ratio / 0.50))

    health_score = (pf_score * 0.4 + wr_score * 0.35 + scratch_score * 0.25)

    if health_score >= 0.75:
        status = "EXCELLENT"
    elif health_score >= 0.55:
        status = "GOOD"
    elif health_score >= 0.35:
        status = "CAUTION"
    else:
        status = "CRITICAL"

    return {
        "components": health_components,
        "health_score": health_score,
        "status": status,
        "diagnostics": {
            "pf_target_met": pf >= 1.5,
            "wr_target_met": wr >= 0.55,
            "exp_positive": exp > 0,
            "scratch_acceptable": scratch_ratio < 0.30,
        }
    }


def get_metrics_snapshot() -> MetricsSnapshot:
    """
    Capture a point-in-time snapshot of all canonical metrics.

    Useful for:
      - Pre-live audit comparisons
      - Dashboard periodic updates
      - Performance tracking over time

    Returns:
        MetricsSnapshot: Immutable snapshot with all key metrics
    """
    try:
        from src.services.canonical_state import get_canonical_state
        state = get_canonical_state()
        total_trades = state.get("trades_total", 0)
        won_trades = state.get("trades_won", 0)
        lost_trades = state.get("trades_lost", 0)
    except Exception:
        total_trades = 0
        won_trades = 0
        lost_trades = 0

    flat_trades = 0
    try:
        from src.services.learning_event import METRICS
        flat_trades = METRICS.get("trades_flat", 0)
        total_net_pnl = METRICS.get("net_pnl_total", 0.0)
    except Exception:
        total_net_pnl = 0.0

    pf = canonical_profit_factor()
    wr = canonical_win_rate()
    exp = canonical_expectancy()

    exits = canonical_exit_breakdown()
    avg_hold = 0.0
    try:
        from src.services.exit_attribution import get_exit_stats
        stats = get_exit_stats()
        if stats:
            total_hold_seconds = sum(s.get("total_hold_seconds", 0) for s in stats.values())
            total_count = sum(s.get("count", 0) for s in stats.values())
            if total_count > 0:
                avg_hold = total_hold_seconds / total_count
    except Exception:
        pass

    return MetricsSnapshot(
        profit_factor=pf,
        win_rate=wr,
        total_trades=total_trades,
        won_trades=won_trades,
        lost_trades=lost_trades,
        flat_trades=flat_trades,
        total_net_pnl=total_net_pnl,
        expectancy=exp,
        scratch_exit_ratio=exits.get("scratch_ratio", 0.0),
        tp_exit_ratio=exits.get("tp_ratio", 0.0),
        timeout_exit_ratio=exits.get("timeout_ratio", 0.0),
        avg_hold_seconds=avg_hold,
    )


def canonical_rr(tp_distance: float, sl_distance: float) -> float:
    """
    PATCH 4: Canonical Risk-Reward ratio computation.

    Single source of truth for RR across RDE, execution, and dashboard.
    Used consistently in decision logs, execution validation, and UI display.

    Args:
        tp_distance: Distance to take-profit (absolute value)
        sl_distance: Distance to stop-loss (absolute value)

    Returns:
        float: Risk-reward ratio (TP / SL), or 0.0 if SL invalid
    """
    tp = abs(float(tp_distance) if isinstance(tp_distance, (int, float)) else 0.0)
    sl = abs(float(sl_distance) if isinstance(sl_distance, (int, float)) else 0.0)

    if sl <= 1e-12:
        return 0.0
    if tp <= 1e-12:
        return 0.0

    return tp / sl
