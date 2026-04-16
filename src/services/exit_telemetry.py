"""
V10.13j: Exit Evaluation Telemetry — Proves smart exit logic is executing

Logs every exit evaluation to show:
  - Which conditions were checked
  - Which triggered
  - Why position wasn't exited (if multiple candidates)
  - Overall harvest composition

Called from trade_executor when evaluating each open position.
"""

import logging
import time
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)

# Counters for harvest composition
_exit_eval_counts = {
    "micro_tp": 0,
    "breakeven": 0,
    "partial_25": 0,
    "partial_50": 0,
    "partial_75": 0,
    "early_stop": 0,
    "trail": 0,
    "scratch": 0,
    "stagnation": 0,
    "no_exit": 0,
}

_last_eval_ts = [0.0]
_eval_log_interval = 60  # Log summary every 60s


def log_exit_evaluation(
    symbol: str,
    side: str,
    entry_price: float,
    tp: float,
    sl: float,
    current_price: float,
    pnl_pct: float,
    duration_s: int,
    checked: Dict[str, bool],  # exit_type -> was_fired
    chosen_reason: Optional[str] = None,
) -> None:
    """
    Log exit evaluation results.
    
    Args:
        symbol: Trading pair (e.g., BTCUSDT)
        side: BUY or SELL
        entry_price: Entry price
        tp: Take profit price
        sl: Stop loss price
        current_price: Current price
        pnl_pct: Current P&L as fraction (0.001 = 0.1%)
        duration_s: Position age in seconds
        checked: Dict showing which conditions were evaluated
        chosen_reason: Why position was/wasn't exited
    """
    
    # Calculate TP progress
    if side == "BUY":
        tp_move = (tp - entry_price) / entry_price if tp != entry_price else 1.0
        tp_progress = (current_price - entry_price) / (tp - entry_price) if tp_move > 0 else 0.0
    else:
        tp_move = (entry_price - tp) / entry_price if tp != entry_price else 1.0
        tp_progress = (entry_price - current_price) / (entry_price - tp) if tp_move > 0 else 0.0
    
    # Build condition flags
    conditions = " ".join([
        f"micro={'Y' if checked.get('micro_tp') else 'N'}",
        f"be={'Y' if checked.get('breakeven') else 'N'}",
        f"p25={'Y' if checked.get('partial_25') else 'N'}",
        f"p50={'Y' if checked.get('partial_50') else 'N'}",
        f"p75={'Y' if checked.get('partial_75') else 'N'}",
        f"trail={'Y' if checked.get('trail') else 'N'}",
        f"scratch={'Y' if checked.get('scratch') else 'N'}",
        f"stag={'Y' if checked.get('stagnation') else 'N'}",
    ])
    
    # Log telemetry
    if chosen_reason:
        _exit_eval_counts[chosen_reason.lower()] = _exit_eval_counts.get(chosen_reason.lower(), 0) + 1
        log.info(
            f"[EXIT_HIT] {symbol:8} {side:4} "
            f"pnl={pnl_pct*100:+.3f}% tp_prog={tp_progress:.2f} age={duration_s:3d}s "
            f"reason={chosen_reason}"
        )
    else:
        _exit_eval_counts["no_exit"] = _exit_eval_counts.get("no_exit", 0) + 1
        log.debug(
            f"[EXIT_EVAL] {symbol:8} {side:4} "
            f"pnl={pnl_pct*100:+.3f}% tp_prog={tp_progress:.2f} age={duration_s:3d}s "
            f"checked=[{conditions}] → no exit"
        )
    
    # Periodically log summary
    now = time.time()
    if now - _last_eval_ts[0] > _eval_log_interval:
        _log_harvest_summary()
        _last_eval_ts[0] = now


def _log_harvest_summary() -> None:
    """Log current harvest composition stats."""
    total = sum(_exit_eval_counts.values())
    if total == 0:
        return
    
    harvest_exits = (
        _exit_eval_counts["micro_tp"]
        + _exit_eval_counts["breakeven"]
        + _exit_eval_counts["partial_25"]
        + _exit_eval_counts["partial_50"]
        + _exit_eval_counts["partial_75"]
        + _exit_eval_counts["trail"]
    )
    
    log.info(
        f"[EXIT_SUMMARY] total_evals={total} "
        f"harvest={harvest_exits} ({harvest_exits/total*100:.1f}%) "
        f"[micro={_exit_eval_counts['micro_tp']} "
        f"be={_exit_eval_counts['breakeven']} "
        f"p25={_exit_eval_counts['partial_25']} "
        f"p50={_exit_eval_counts['partial_50']} "
        f"p75={_exit_eval_counts['partial_75']} "
        f"trail={_exit_eval_counts['trail']} "
        f"scratch={_exit_eval_counts['scratch']} "
        f"stag={_exit_eval_counts['stagnation']} "
        f"none={_exit_eval_counts['no_exit']}]"
    )


def get_harvest_stats() -> Dict[str, Any]:
    """Get current harvest statistics for dashboard."""
    total = sum(_exit_eval_counts.values())
    if total == 0:
        return {"total": 0, "harvest_rate": 0.0, "breakdown": {}}
    
    harvest_exits = (
        _exit_eval_counts["micro_tp"]
        + _exit_eval_counts["breakeven"]
        + _exit_eval_counts["partial_25"]
        + _exit_eval_counts["partial_50"]
        + _exit_eval_counts["partial_75"]
        + _exit_eval_counts["trail"]
    )
    
    return {
        "total_evals": total,
        "harvest_exits": harvest_exits,
        "harvest_rate": harvest_exits / total if total > 0 else 0.0,
        "breakdown": dict(_exit_eval_counts),
    }


def reset_stats() -> None:
    """Reset statistics (for testing or cycle reset)."""
    global _exit_eval_counts
    _exit_eval_counts = {k: 0 for k in _exit_eval_counts}
