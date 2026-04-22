"""
V10.13v (Fix 7): Exit Outcome Distribution and Attribution

Tracks which exit types are actually closing trades and contributing to profitability.
Answers: Which exit types are making or losing money? Are scratch/micro exits protective
or destructive? Is realized expectancy coming from a tiny subset of exit types?
"""

import logging
from typing import Dict, List, Tuple

log = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════════
# 1. Canonical exit type classification
# ════════════════════════════════════════════════════════════════════════════════

EXIT_TYPES = {
    "TP": "Take Profit hit",
    "SL": "Stop Loss hit",
    "TRAIL": "Trailing stop hit",
    "PARTIAL_TP_25": "Partial TP 25% taken",
    "PARTIAL_TP_50": "Partial TP 50% taken",
    "BE_EXIT": "Breakeven exit",
    "SCRATCH_EXIT": "Scratch exit (micro loss accepted)",
    "MICRO_EXIT": "Micro exit (very small loss/gain)",
    "TIMEOUT_PROFIT": "Timeout with profit",
    "TIMEOUT_FLAT": "Timeout flat (near breakeven)",
    "TIMEOUT_LOSS": "Timeout with loss",
    "STAGNATION_EXIT": "Stagnation exit (no progress)",
    "HARVEST_EXIT": "Harvest mode exit",
    "WALL_EXIT": "Wall exit (price touched wall)",
    "MANUAL_EXIT": "Manual exit",
    "UNKNOWN_EXIT": "Unknown exit type",
}

# ════════════════════════════════════════════════════════════════════════════════
# 2. Exit stats aggregator
# ════════════════════════════════════════════════════════════════════════════════

_exit_stats: Dict[str, Dict] = {}


def _init_exit_type_stats(exit_type: str) -> None:
    """Initialize stats dict for an exit type."""
    if exit_type not in _exit_stats:
        _exit_stats[exit_type] = {
            "count": 0,
            "win_count": 0,
            "loss_count": 0,
            "total_gross_pnl": 0.0,
            "total_net_pnl": 0.0,
            "total_hold_seconds": 0,
            "symbols": {},
            "regimes": {},
        }


# ════════════════════════════════════════════════════════════════════════════════
# 3. Exit context payload
# ════════════════════════════════════════════════════════════════════════════════

def build_exit_ctx(
    sym: str,
    regime: str,
    side: str,
    entry_price: float,
    exit_price: float,
    size: float,
    hold_seconds: int,
    gross_pnl: float,
    fee_cost: float,
    slippage_cost: float,
    net_pnl: float,
    mfe: float,
    mae: float,
    final_exit_type: str,
    exit_reason_text: str = "",
    was_winner: bool = False,
    was_forced: bool = False,
    partials_taken: List[str] = None,
) -> dict:
    """V10.13v (Fix 7): Build canonical exit context payload.
    
    Returns dict with complete exit metadata for attribution.
    Every closed trade must have exactly one primary exit type.
    """
    r_multiple = None
    if size > 0:
        r_multiple = abs(net_pnl) / (size * 0.01)
    
    return {
        "symbol": sym,
        "regime": regime,
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "size": size,
        "hold_seconds": hold_seconds,
        "gross_pnl": gross_pnl,
        "fee_cost": fee_cost,
        "slippage_cost": slippage_cost,
        "net_pnl": net_pnl,
        "r_multiple": r_multiple,
        "mae": mae,
        "mfe": mfe,
        "partials_taken": partials_taken or [],
        "final_exit_type": final_exit_type,
        "exit_reason_text": exit_reason_text,
        "was_winner": was_winner,
        "was_forced": was_forced,
    }


def validate_exit_ctx(ctx: dict) -> Tuple[bool, List[str]]:
    """V10.13v (Fix 7): Validate exit context for consistency."""
    errors = []
    
    required = ["symbol", "final_exit_type", "net_pnl", "hold_seconds"]
    for field in required:
        if field not in ctx or ctx[field] is None:
            errors.append(f"Missing required field: {field}")
    
    if ctx.get("final_exit_type") not in EXIT_TYPES:
        errors.append(f"Invalid final_exit_type: {ctx.get('final_exit_type')}")
    
    if ctx.get("hold_seconds", 0) < 0:
        errors.append(f"Negative hold_seconds: {ctx.get('hold_seconds')}")
    
    if ctx.get("gross_pnl") is not None and ctx.get("net_pnl") is not None:
        expected = ctx["gross_pnl"] - ctx.get("fee_cost", 0) - ctx.get("slippage_cost", 0)
        actual = ctx["net_pnl"]
        if abs(actual - expected) > 0.00001:
            errors.append(
                f"Net PnL mismatch: gross={expected:.6f} but got {actual:.6f}"
            )
    
    return len(errors) == 0, errors


# ════════════════════════════════════════════════════════════════════════════════
# 4. Exit stats updater
# ════════════════════════════════════════════════════════════════════════════════

def update_exit_attribution(exit_ctx: dict) -> None:
    """V10.13v (Fix 7): Update exit stats aggregator with new trade exit."""
    is_valid, errors = validate_exit_ctx(exit_ctx)
    if not is_valid:
        log.error(f"[V10.13v EXIT_INTEGRITY_ERROR] Validation failed for {exit_ctx.get('symbol','?')}")
        for err in errors:
            log.error(f"  - {err}")
        return
    
    exit_type = exit_ctx.get("final_exit_type", "UNKNOWN_EXIT")
    sym = exit_ctx.get("symbol", "?")
    regime = exit_ctx.get("regime", "RANGING")
    net_pnl = exit_ctx.get("net_pnl", 0.0)
    hold_sec = exit_ctx.get("hold_seconds", 0)
    was_winner = exit_ctx.get("was_winner", False)
    
    _init_exit_type_stats(exit_type)
    
    stats = _exit_stats[exit_type]
    stats["count"] += 1
    stats["win_count"] += (1 if was_winner else 0)
    stats["loss_count"] += (0 if was_winner else 1)
    stats["total_gross_pnl"] += exit_ctx.get("gross_pnl", 0.0)
    stats["total_net_pnl"] += net_pnl
    stats["total_hold_seconds"] += hold_sec
    
    if sym not in stats["symbols"]:
        stats["symbols"][sym] = {"count": 0, "net_pnl": 0.0, "total_hold": 0}
    stats["symbols"][sym]["count"] += 1
    stats["symbols"][sym]["net_pnl"] += net_pnl
    stats["symbols"][sym]["total_hold"] += hold_sec
    
    if regime not in stats["regimes"]:
        stats["regimes"][regime] = {"count": 0, "net_pnl": 0.0, "total_hold": 0}
    stats["regimes"][regime]["count"] += 1
    stats["regimes"][regime]["net_pnl"] += net_pnl
    stats["regimes"][regime]["total_hold"] += hold_sec


# ════════════════════════════════════════════════════════════════════════════════
# 5. Exit attribution dashboard
# ════════════════════════════════════════════════════════════════════════════════

def render_exit_attribution_summary() -> str:
    """V10.13v (Fix 7): Generate exit attribution dashboard summary."""
    if not _exit_stats:
        return "[V10.13v EXIT] No trades closed yet."
    
    total_trades = sum(s["count"] for s in _exit_stats.values())
    total_net_pnl = sum(s["total_net_pnl"] for s in _exit_stats.values())
    
    lines = [
        "[V10.13v EXIT_ATTRIBUTION]",
        f"  Total trades: {total_trades}  |  Net PnL: {total_net_pnl:+.6f}",
    ]
    
    sorted_exits = sorted(
        _exit_stats.items(),
        key=lambda x: x[1]["count"],
        reverse=True
    )
    
    for exit_type, stats in sorted_exits:
        count = stats["count"]
        wins = stats["win_count"]
        pct_wins = (wins / count * 100) if count > 0 else 0
        total_pnl = stats["total_net_pnl"]
        avg_pnl = total_pnl / count if count > 0 else 0
        avg_hold = stats["total_hold_seconds"] / count if count > 0 else 0
        share = (count / total_trades * 100) if total_trades > 0 else 0
        
        lines.append(
            f"  {exit_type:20s}  count={count:3d}  share={share:5.1f}%  "
            f"wr={pct_wins:5.1f}%  net={total_pnl:+.6f}  avg={avg_pnl:+.6f}  "
            f"hold={avg_hold:6.0f}s"
        )
    
    scratch_micro = sum(
        s["count"] for et, s in _exit_stats.items()
        if "SCRATCH" in et or "MICRO" in et
    )
    tp_trail = sum(
        s["count"] for et, s in _exit_stats.items()
        if "TP" in et or "TRAIL" in et
    )
    
    lines.extend([
        f"  [Summary] Scratch+Micro: {scratch_micro}/{total_trades} ({scratch_micro/total_trades*100:.1f}%)",
        f"  [Summary] TP+Trail: {tp_trail}/{total_trades} ({tp_trail/total_trades*100:.1f}%)",
    ])
    
    return "\n".join(lines)


def log_exit_attribution_summary() -> None:
    """Log the exit attribution summary to debug logs."""
    summary = render_exit_attribution_summary()
    log.info(summary)


def get_exit_stats() -> Dict:
    """Return current exit attribution statistics."""
    return {k: dict(v) for k, v in _exit_stats.items()}


def reset_exit_stats() -> None:
    """Reset exit attribution stats."""
    global _exit_stats
    _exit_stats = {}
