"""
PRIORITY 4: Exit Monetization Patch — TP Ladder, Delayed Scratch, Regime-Aware Stagnation

Problem: 81% scratch exits + single 25% partial TP prevents profit capture (PF 0.65x).
Solution: Multi-level TP ladder + delayed scratch for strong signals.

Strategy:
  1. TP Ladder (ATR-based, not fixed %):
     - TP1: at 0.7x ATR → 25% position
     - TP2: at 1.1x ATR → 25% position
     - Remainder: trail or final exit

  2. Scratch Delay (signal strength aware):
     - Weak signals (p < 0.60): activate scratch early (60s)
     - Normal signals (0.60 ≤ p < 0.75): standard scratch (105s)
     - Strong signals (p ≥ 0.75): delay scratch (150s), try for higher exits

  3. Regime-Aware Stagnation:
     - TRENDING: 240s stagnation timeout (let trades run longer)
     - RANGING: 180s (shorter patience, exit quicker)
     - VOLATILE: 120s (get out fast if stalled)

  4. Profit Reinvestment:
     - After TP1/TP2 exits, allow new entries in same cell (don't lock pair)

Usage:
  from src.services.exit_monetization import (
      get_tp_ladder, get_scratch_activation_age,
      get_stagnation_timeout, calculate_atr
  )

  atr = calculate_atr("BTCUSDT", "TRENDING")
  tp1_price = entry_price + atr * 0.7  # First target
  tp2_price = entry_price + atr * 1.1  # Second target

  scratch_age = get_scratch_activation_age(signal_probability=0.80)
  # Returns 150s for strong signal (delay scratch to try for TP)

  stagnation_timeout = get_stagnation_timeout("TRENDING")
  # Returns 240s for trending regime
"""

import logging
from typing import Dict, Optional, Tuple
import numpy as np

log = logging.getLogger(__name__)


def calculate_atr(sym: str, regime: str = None, period: int = 14) -> float:
    """
    Calculate Average True Range for (sym, regime).

    ATR used as basis for TP ladder targets:
      - TP1: entry + 0.7 * ATR
      - TP2: entry + 1.1 * ATR

    Args:
        sym: Symbol (e.g., "BTCUSDT")
        regime: Optional regime for regime-specific scaling
        period: ATR period (default 14)

    Returns:
        float: ATR value. Returns 0.001 if unavailable (fallback).
    """
    try:
        from src.services.price_service import get_klines
        klines = get_klines(sym, "1h", limit=period + 10)
        if not klines or len(klines) < period:
            return 0.001

        true_ranges = []
        for i in range(1, len(klines)):
            high = float(klines[i].get("high", 0))
            low = float(klines[i].get("low", 0))
            close_prev = float(klines[i-1].get("close", 0))

            tr = max(
                high - low,
                abs(high - close_prev),
                abs(low - close_prev)
            )
            true_ranges.append(tr)

        if true_ranges:
            atr = float(np.mean(true_ranges[-period:]))
            return max(atr, 0.001)
    except Exception as e:
        log.debug(f"[EXIT_MONETIZATION] ATR calc failed for {sym}: {e}")

    return 0.001


def get_tp_ladder(
    sym: str,
    entry_price: float,
    regime: str = "RANGING",
    direction: str = "BUY"
) -> Dict[str, float]:
    """
    Get TP ladder levels for position entry.

    Returns dict with:
      - tp1_price: First target (0.7x ATR)
      - tp1_size_fraction: 0.25 (25% of position)
      - tp2_price: Second target (1.1x ATR)
      - tp2_size_fraction: 0.25 (25% of position)
      - atr: Underlying ATR used

    Args:
        sym: Symbol
        entry_price: Entry price
        regime: Market regime ("BULL_TREND", "BEAR_TREND", "RANGING", etc.)
        direction: "BUY" or "SELL"

    Returns:
        Dict with TP levels and size fractions
    """
    atr = calculate_atr(sym, regime)

    # ATR-based targets (regime-adaptive scaling)
    if "TREND" in regime:
        tp1_multiplier = 0.7
        tp2_multiplier = 1.1
    else:  # RANGING/QUIET
        tp1_multiplier = 0.5
        tp2_multiplier = 0.85

    if direction.upper() == "BUY":
        tp1_price = entry_price + atr * tp1_multiplier
        tp2_price = entry_price + atr * tp2_multiplier
    else:  # SELL
        tp1_price = entry_price - atr * tp1_multiplier
        tp2_price = entry_price - atr * tp2_multiplier

    return {
        "tp1_price": tp1_price,
        "tp1_size_fraction": 0.25,
        "tp2_price": tp2_price,
        "tp2_size_fraction": 0.25,
        "atr": atr,
        "trailing_remainder_size_fraction": 0.50,
    }


def get_scratch_activation_age(
    signal_probability: float = 0.50,
    regime: str = "RANGING"
) -> int:
    """
    Get scratch activation age (seconds) based on signal strength.

    Scratch delay strategy:
      - Weak signals (p < 0.60): 60s (cut losses quickly)
      - Normal signals (0.60-0.75): 105s (standard)
      - Strong signals (p ≥ 0.75): 150s (delay, try for higher exits)

    Args:
        signal_probability: Raw signal probability (0.0-1.0)
        regime: Market regime (for regime-adaptive adjustment)

    Returns:
        int: Seconds until scratch exit becomes available
    """
    base_age = 105  # Standard scratch activation

    if signal_probability < 0.60:
        base_age = 60
    elif signal_probability >= 0.75:
        base_age = 150

    # Regime adjustment
    if "TREND" in regime:
        base_age += 30  # Delay scratch longer in trending markets
    elif "VOLATILE" in regime:
        base_age -= 20  # Shorter patience in volatile

    return max(30, min(180, base_age))


def get_scratch_max_pnl(regime: str = "RANGING") -> float:
    """
    Get scratch exit max PnL band (when to consider as "scratch").

    Varies by regime to adapt to typical profit levels:
      - RANGING: 0.0020 (tight band, normal markets)
      - TRENDING: 0.0030 (allow more room in trends)
      - VOLATILE: 0.0015 (exit faster in chop)

    Args:
        regime: Market regime

    Returns:
        float: Max PnL fraction for scratch classification
    """
    if "VOLATILE" in regime or "CHOP" in regime:
        return 0.0015
    elif "TREND" in regime:
        return 0.0030
    else:  # RANGING, QUIET
        return 0.0020


def get_stagnation_timeout(regime: str = "RANGING") -> int:
    """
    Get stagnation timeout (seconds) before forcing exit.

    Regime-aware timing:
      - BULL_TREND/BEAR_TREND: 240s (let trends develop)
      - BULL_RANGE/BEAR_RANGE: 180s (shorter patience in ranges)
      - RANGING/QUIET: 180s
      - VOLATILE: 120s (get out if stuck in noise)

    Args:
        regime: Market regime

    Returns:
        int: Stagnation timeout in seconds
    """
    if "TREND" in regime:
        return 240
    elif "VOLATILE" in regime or "CHOP" in regime:
        return 120
    else:  # RANGING, QUIET, other
        return 180


def get_exit_monetization_config(
    sym: str,
    regime: str,
    signal_probability: float,
    direction: str = "BUY",
    entry_price: float = None
) -> Dict:
    """
    Get complete exit monetization config for a trade.

    Combines TP ladder, scratch settings, and stagnation timeout.

    Args:
        sym: Symbol
        regime: Market regime
        signal_probability: Signal probability (0.0-1.0)
        direction: "BUY" or "SELL"
        entry_price: Entry price (required for TP ladder calculation)

    Returns:
        Dict with complete exit configuration
    """
    if entry_price is None:
        entry_price = 0.0

    tp_ladder = get_tp_ladder(sym, entry_price, regime, direction)
    scratch_age = get_scratch_activation_age(signal_probability, regime)
    scratch_pnl = get_scratch_max_pnl(regime)
    stagnation_timeout = get_stagnation_timeout(regime)

    return {
        "tp_ladder": tp_ladder,
        "scratch_activation_age_seconds": scratch_age,
        "scratch_max_pnl_fraction": scratch_pnl,
        "stagnation_timeout_seconds": stagnation_timeout,
        "metadata": {
            "signal_probability": signal_probability,
            "regime": regime,
            "scratch_tier": (
                "WEAK" if signal_probability < 0.60
                else "STRONG" if signal_probability >= 0.75
                else "NORMAL"
            ),
        }
    }


def estimate_profit_from_ladder(
    entry_price: float,
    position_size: float,
    symbol_precision: float = 0.01,
    regime: str = "RANGING"
) -> Dict[str, float]:
    """
    Estimate expected profit breakdown from TP ladder.

    Assumes:
      - TP1: 25% position at 0.7x ATR
      - TP2: 25% position at 1.1x ATR
      - Remainder: partial trailing exit

    Returns dict with:
      - expected_profit_tp1: P&L from first ladder
      - expected_profit_tp2: P&L from second ladder
      - expected_profit_total_ladder: Sum of TP1+TP2
      - ladder_profit_per_trade: P&L per trade from ladder
    """
    atr = calculate_atr("", regime)

    if "TREND" in regime:
        tp1_mult = 0.7
        tp2_mult = 1.1
    else:
        tp1_mult = 0.5
        tp2_mult = 0.85

    # Approximate profit per target
    tp1_move = atr * tp1_mult
    tp2_move = atr * tp2_mult

    # P&L in quote currency (simplified, no fees)
    profit_tp1 = position_size * tp1_move * 0.25
    profit_tp2 = position_size * tp2_move * 0.25

    return {
        "expected_profit_tp1": profit_tp1,
        "expected_profit_tp2": profit_tp2,
        "expected_profit_total_ladder": profit_tp1 + profit_tp2,
        "ladder_profit_per_trade": (profit_tp1 + profit_tp2) / max(position_size, 0.001),
    }
