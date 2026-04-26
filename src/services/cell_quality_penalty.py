"""
PRIORITY 3: Cell Quality Penalty — Dynamically reduce/block allocation to weak (sym, regime) cells.

Problem: BNB/BEAR at 12% WR, DOT/BEAR at 0% still receive allocation, dragging down overall results.
Solution: Track empirical WR per cell, apply penalty multiplier based on statistical weakness.

Penalty tiers (based on win rate vs baseline):
  Tier 1 (WR < 40%): 0.30x sizing (reduce to 30% of normal)
  Tier 2 (WR 40-50%): 0.60x sizing
  Tier 3 (WR 50-55%): 0.85x sizing
  Tier 4 (WR 55%+): 1.00x sizing (no penalty)

Evidence threshold:
  - Require ≥ 20 trades to apply penalty (statistical confidence)
  - Require ≥ 5 trades to block entirely (<0.25 baseline WR)

Recovery mechanism:
  - If cell improves to Tier 4, resume normal sizing
  - If cell stays in Tier 1 for 100+ trades, consider removing pair

Usage:
  from src.services.cell_quality_penalty import (
      get_cell_quality_multiplier, get_weak_cells,
      get_quality_penalty_report
  )

  mult = get_cell_quality_multiplier("BNB", "BEAR")
  # Returns 0.30 if BNB/BEAR has 12% WR

  weak = get_weak_cells(threshold=0.50)
  # Returns [("BNB", "BEAR"), ("DOT", "BEAR"), ...]

  report = get_quality_penalty_report()
  # Detailed breakdown of penalties applied
"""

import logging
from typing import Dict, List, Tuple, Optional
import numpy as np

log = logging.getLogger(__name__)


def _get_cell_win_rate(sym: str, regime: str) -> Tuple[float, int]:
    """
    Get empirical win rate and trade count for (sym, regime) cell.

    Returns:
        Tuple of (win_rate: 0.0-1.0, trade_count: int)
    """
    try:
        from src.services.learning_monitor import lm_wr_hist, lm_count
        key = (sym, regime)

        wr = 0.5
        wr_hist = lm_wr_hist.get(key, [])
        if wr_hist:
            wr = wr_hist[-1]

        count = lm_count.get(key, 0)
        return wr, count
    except Exception:
        return 0.5, 0


def _get_baseline_win_rate() -> float:
    """
    Get overall baseline win rate across all pairs/regimes.

    Used as reference for computing relative weakness.
    Typical range: 0.50-0.75 for healthy system.
    """
    try:
        from src.services.canonical_metrics import canonical_win_rate
        return canonical_win_rate()
    except Exception:
        return 0.55


def _classify_cell_quality(win_rate: float, baseline_wr: float) -> str:
    """
    Classify cell quality into tiers.

    Args:
        win_rate: Empirical WR for cell (0.0-1.0)
        baseline_wr: Overall baseline WR (e.g., 0.55)

    Returns:
        Tier string ("EXCELLENT", "GOOD", "WEAK", "VERY_WEAK")
    """
    min_acceptable = max(0.40, baseline_wr - 0.10)

    if win_rate >= baseline_wr:
        return "EXCELLENT"
    elif win_rate >= (baseline_wr - 0.05):
        return "GOOD"
    elif win_rate >= min_acceptable:
        return "WEAK"
    else:
        return "VERY_WEAK"


def get_cell_quality_multiplier(sym: str, regime: str, min_trades: int = 20) -> float:
    """
    Get sizing multiplier for (sym, regime) cell based on quality.

    Penalty tiers:
      VERY_WEAK (WR < 40%):  0.30x (reduce to 30%)
      WEAK (WR 40-50%):      0.60x (reduce to 60%)
      GOOD (WR ~baseline):   0.85x (mild penalty)
      EXCELLENT:             1.00x (no penalty)

    Args:
        sym: Symbol (e.g., "BTCUSDT")
        regime: Regime (e.g., "TRENDING", "RANGING")
        min_trades: Minimum trades required to apply penalty (default 20 for confidence)

    Returns:
        float: Multiplier (0.30 to 1.00) to apply to standard sizing
    """
    win_rate, trade_count = _get_cell_win_rate(sym, regime)
    baseline_wr = _get_baseline_win_rate()

    # Insufficient data: no penalty yet
    if trade_count < min_trades:
        return 1.00

    tier = _classify_cell_quality(win_rate, baseline_wr)

    if tier == "EXCELLENT":
        return 1.00
    elif tier == "GOOD":
        return 0.85
    elif tier == "WEAK":
        return 0.60
    else:  # VERY_WEAK
        return 0.30


def should_block_cell(sym: str, regime: str, min_trades: int = 5) -> bool:
    """
    Determine if cell should be completely blocked (no allocation).

    Block criteria:
      - Trade count ≥ min_trades (statistical confidence)
      - Win rate < 0.25 (complete failure)

    Args:
        sym: Symbol
        regime: Regime
        min_trades: Minimum trades before considering block (default 5)

    Returns:
        bool: True if cell should be blocked
    """
    win_rate, trade_count = _get_cell_win_rate(sym, regime)

    if trade_count < min_trades:
        return False

    if win_rate < 0.25:
        return True

    return False


def get_weak_cells(
    threshold: float = 0.50,
    min_trades: int = 20
) -> List[Tuple[str, str]]:
    """
    Get list of (sym, regime) pairs below quality threshold.

    Args:
        threshold: WR threshold (default 0.50, return pairs below this)
        min_trades: Minimum trades for a cell to be considered (default 20)

    Returns:
        List of (sym, regime) tuples sorted by WR (worst first)
    """
    try:
        from src.services.learning_monitor import lm_wr_hist, lm_count
    except Exception:
        return []

    weak_cells = []

    for (sym, regime), wr_hist in lm_wr_hist.items():
        if not wr_hist:
            continue

        current_wr = wr_hist[-1]
        trade_count = lm_count.get((sym, regime), 0)

        if trade_count >= min_trades and current_wr < threshold:
            weak_cells.append((sym, regime, current_wr, trade_count))

    # Sort by WR (worst first)
    weak_cells.sort(key=lambda x: x[2])

    return [(sym, regime) for sym, regime, _, _ in weak_cells]


def get_quality_penalty_report() -> Dict:
    """
    Generate comprehensive quality penalty report.

    Returns dict with:
      - total_cells: Total unique (sym, regime) pairs tracked
      - excellent_cells: Count of EXCELLENT tier cells
      - good_cells: Count of GOOD tier cells
      - weak_cells: Count of WEAK tier cells
      - very_weak_cells: Count of VERY_WEAK tier cells
      - blocked_cells: Count of completely blocked cells
      - avg_penalty: Average penalty multiplier across all cells
      - worst_cells: Top 5 worst-performing cells with details
    """
    try:
        from src.services.learning_monitor import lm_wr_hist, lm_count
    except Exception:
        return {
            "total_cells": 0,
            "excellent_cells": 0,
            "good_cells": 0,
            "weak_cells": 0,
            "very_weak_cells": 0,
            "blocked_cells": 0,
            "avg_penalty": 1.00,
            "worst_cells": [],
        }

    baseline_wr = _get_baseline_win_rate()

    cells_by_tier = {
        "EXCELLENT": 0,
        "GOOD": 0,
        "WEAK": 0,
        "VERY_WEAK": 0,
        "BLOCKED": 0,
    }

    multipliers = []
    cell_details = []

    for (sym, regime), wr_hist in lm_wr_hist.items():
        if not wr_hist:
            continue

        current_wr = wr_hist[-1]
        trade_count = lm_count.get((sym, regime), 0)

        if trade_count >= 5:
            if should_block_cell(sym, regime):
                cells_by_tier["BLOCKED"] += 1
                mult = 0.0
            else:
                tier = _classify_cell_quality(current_wr, baseline_wr)
                cells_by_tier[tier] += 1

                if tier == "EXCELLENT":
                    mult = 1.00
                elif tier == "GOOD":
                    mult = 0.85
                elif tier == "WEAK":
                    mult = 0.60
                else:  # VERY_WEAK
                    mult = 0.30

            multipliers.append(mult)
            cell_details.append((sym, regime, current_wr, trade_count, mult))

    avg_mult = float(np.mean(multipliers)) if multipliers else 1.00

    # Top 5 worst cells
    cell_details.sort(key=lambda x: x[2])
    worst_cells = [
        {
            "sym": sym,
            "regime": regime,
            "wr": wr,
            "trades": count,
            "multiplier": mult,
        }
        for sym, regime, wr, count, mult in cell_details[:5]
    ]

    return {
        "total_cells": len(cell_details),
        "excellent_cells": cells_by_tier["EXCELLENT"],
        "good_cells": cells_by_tier["GOOD"],
        "weak_cells": cells_by_tier["WEAK"],
        "very_weak_cells": cells_by_tier["VERY_WEAK"],
        "blocked_cells": cells_by_tier["BLOCKED"],
        "avg_penalty": avg_mult,
        "worst_cells": worst_cells,
        "baseline_wr": baseline_wr,
    }
