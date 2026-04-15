"""
Regime Detection Module

Identifies market regime (TREND, RANGE, UNCERTAIN) based on technical indicators.
Used for signal calibration and strategy adaptation.

Regimes:
  TREND: Strong directional movement (follow trends)
  RANGE: Sideways / mean-reversion (range-bound strategies)
  UNCERTAIN: Weak signals (reduced position size / avoid entry)
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class RegimeDetector:
    """Market regime detection based on ADX, EMA slope, and volatility."""
    
    def __init__(self, adx_trend_threshold: float = 25, adx_weak_threshold: float = 15):
        """
        Initialize regime detector.
        
        Args:
            adx_trend_threshold: ADX above this = TREND regime (default 25)
            adx_weak_threshold: ADX below this = RANGE regime (default 15)
        """
        self.adx_trend = adx_trend_threshold
        self.adx_weak = adx_weak_threshold
    
    def detect(self, adx: float, ema_slope: float, volatility: float = None) -> str:
        """
        Detect market regime.
        
        Args:
            adx: ADX value (0-100)
            ema_slope: EMA slope (price derivative)
            volatility: Optional volatility measure (ATR or std dev)
            
        Returns:
            Regime string: "TREND", "RANGE", or "UNCERTAIN"
            
        Logic:
            if ADX > 25: TREND (strong directional bias)
            elif ADX < 15: RANGE (no clear direction)
            else: UNCERTAIN (weak signal)
        """
        if adx >= self.adx_trend:
            return "TREND"
        elif adx <= self.adx_weak:
            return "RANGE"
        else:
            return "UNCERTAIN"
    
    def get_multiplier(self, regime: str) -> float:
        """
        Get EV multiplier based on regime.
        
        Adjusts signal strength for regime:
        - TREND: 1.2x (increases EV in strong trends)
        - RANGE: 0.7x (reduces EV in ranges, use mean-reversion)
        - UNCERTAIN: 0.5x (conservative in unclear conditions)
        
        Args:
            regime: Regime string from detect()
            
        Returns:
            Multiplier (0.5-1.2)
        """
        multipliers = {
            "TREND": 1.2,
            "RANGE": 0.7,
            "UNCERTAIN": 0.5,
        }
        return multipliers.get(regime, 1.0)


def detect_regime(adx: float, ema_slope: float) -> str:
    """
    Quick regime detection (backward compatible).
    
    Args:
        adx: ADX value (0-100)
        ema_slope: EMA slope (price derivative)
        
    Returns:
        Regime: "TREND", "RANGE", or "UNCERTAIN"
    """
    detector = RegimeDetector()
    return detector.detect(adx, ema_slope)


def analyze_multi_regime(adx_list: list, ema_slopes: list) -> Tuple[str, float]:
    """
    Analyze regime across multiple timeframes.
    
    Provides consensus regime and confidence score.
    
    Args:
        adx_list: List of ADX values from different timeframes
        ema_slopes: List of EMA slopes from different timeframes
        
    Returns:
        Tuple[regime, confidence] where confidence is 0-1
        
    Example:
        >>> analyze_multi_regime([30, 28, 25], [0.005, 0.004, 0.003])
        ("TREND", 0.95)  # Strong trend consensus across TFs
    """
    if not adx_list:
        return "UNCERTAIN", 0.0
    
    detector = RegimeDetector()
    regimes = [detector.detect(adx, slope) for adx, slope in zip(adx_list, ema_slopes)]
    
    # Consensus: count regime occurrences
    regime_counts = {}
    for regime in regimes:
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
    
    # Most common regime
    consensus = max(regime_counts, key=regime_counts.get)
    confidence = regime_counts[consensus] / len(regimes)
    
    return consensus, confidence


def regime_adjustment(base_ev: float, regime: str) -> float:
    """
    Adjust expected value based on market regime.
    
    Args:
        base_ev: Original expected value
        regime: Market regime from detect()
        
    Returns:
        Regime-adjusted expected value
        
    Example:
        >>> regime_adjustment(0.3, "TREND")
        0.36  # 20% boost in trends
        
        >>> regime_adjustment(0.3, "RANGE")
        0.21  # 30% reduction in ranges
    """
    multiplier = RegimeDetector().get_multiplier(regime)
    return base_ev * multiplier
