"""
EV (Expected Value) Normalization Module

Computes normalized expected value for trade signals.
Used by Decision Engine for signal calibration and gating.

EV = P * RR - (1 - P)
Normalized = EV / ATR (volatility scaling)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def compute_ev(p: float, rr: float, atr: float = 0.01) -> float:
    """
    Compute normalized expected value for a trade signal.
    
    Expected Value (EV) measures the average profit per trade.
    EV = (Win Probability × Risk-Reward Ratio) - (Loss Probability)
    
    Normalized EV scales by ATR to control for market volatility.
    
    Formula:
        raw_ev = p * rr - (1 - p)
        normalized_ev = raw_ev / max(atr, eps)
    
    Args:
        p: Win probability (0-1, e.g., 0.6 = 60% win rate)
        rr: Risk-Reward ratio (e.g., 1.5 = 1:1.5 SL:TP)
        atr: Average True Range (volatility). Defaults to 0.01
        
    Returns:
        Normalized expected value (float).
        - Positive: Expected profit
        - Negative: Expected loss
        - Zero: Break-even
        
    Examples:
        >>> compute_ev(0.6, 1.5, 0.01)  # 60% win, 1:1.5 RR, ATR=0.01
        0.4 / 0.01 = 40.0
        
        >>> compute_ev(0.5, 1.0, 0.01)  # 50% win, 1:1 RR (break-even)
        0.0 / 0.01 = 0.0
        
        >>> compute_ev(0.45, 1.5, 0.02)  # 45% win, 1:1.5 RR, ATR=0.02
        (-0.175) / 0.02 = -8.75
    """
    if atr <= 0:
        atr = 1e-6  # Prevent division by zero
    
    if not (0 <= p <= 1):
        logger.warning(f"Probability {p} outside valid range [0,1]. Clamping.")
        p = max(0, min(1, p))
    
    if rr <= 0:
        logger.warning(f"Risk-Reward ratio {rr} must be positive. Defaulting to 1.0")
        rr = 1.0
    
    # Raw expected value
    raw_ev = p * rr - (1 - p)
    
    # Volatility-normalized EV
    normalized_ev = raw_ev / max(atr, 1e-6)
    
    return normalized_ev


def is_positive_ev(p: float, rr: float, atr: float = 0.01, min_threshold: float = 0.0) -> bool:
    """
    Check if signal has positive expected value above threshold.
    
    Args:
        p: Win probability (0-1)
        rr: Risk-Reward ratio
        atr: Average True Range (volatility)
        min_threshold: Minimum EV threshold for acceptance (default 0.0)
        
    Returns:
        True if normalized EV > min_threshold, else False
        
    Examples:
        >>> is_positive_ev(0.6, 1.5, 0.01, 0.0)
        True
        
        >>> is_positive_ev(0.45, 1.0, 0.01, 0.0)
        False
    """
    ev = compute_ev(p, rr, atr)
    return ev > min_threshold


def compute_break_even_probability(rr: float) -> float:
    """
    Calculate the minimum win probability needed for break-even.
    
    Break-even occurs when: P * RR = 1 - P
    Solving: P = 1 / (1 + RR)
    
    Args:
        rr: Risk-Reward ratio
        
    Returns:
        Probability needed for break-even (0-1)
        
    Examples:
        >>> compute_break_even_probability(1.0)
        0.5  # Need 50% to break even with 1:1 RR
        
        >>> compute_break_even_probability(2.0)
        0.333...  # Need ~33% to break even with 1:2 RR
    """
    if rr <= 0:
        return 1.0
    return 1.0 / (1.0 + rr)


def safety_margin(p: float, rr: float) -> float:
    """
    Compute safety margin above break-even probability.
    
    Positive margin means signal has edge; negative means it doesn't.
    
    Args:
        p: Actual win probability
        rr: Risk-Reward ratio
        
    Returns:
        Margin = (p - break_even_p) * 100 (in percentage points)
        
    Examples:
        >>> safety_margin(0.6, 1.0)
        10.0  # 10% above break-even (50%)
        
        >>> safety_margin(0.45, 1.0)
        -5.0  # 5% below break-even (not profitable)
    """
    be_p = compute_break_even_probability(rr)
    return (p - be_p) * 100
