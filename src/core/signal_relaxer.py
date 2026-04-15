"""
Signal Relaxer Module (V5.1 Patch)

Relaxes filter requirements when system health is low.
Allows more signals through to enable learning and exploration.

Logic:
  - High health (>0.5): 80% pass rate required (strict)
  - Medium health (0.3-0.5): 60% pass rate required (normal)
  - Low health (<0.3): 40% pass rate required (exploration mode)
  
This prevents the system from getting stuck in perpetual
"no trade" loops when market conditions change unexpectedly.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


class SignalRelaxer:
    """
    Relaxes filter requirements based on system health.
    
    Purpose:
        - Enable trading when filters are too strict
        - Force exploration when health is low
        - Learn from diverse market conditions
    """
    
    def __init__(
        self,
        strict_threshold: float = 0.8,    # 80% filter pass
        normal_threshold: float = 0.6,    # 60% filter pass
        relaxed_threshold: float = 0.4,   # 40% filter pass
        critical_threshold: float = 0.2,  # 20% filter pass (emergency)
    ):
        """
        Initialize signal relaxer.
        
        Args:
            strict_threshold: Pass rate required when health > 0.5
            normal_threshold: Pass rate required when 0.3 < health < 0.5
            relaxed_threshold: Pass rate required when health < 0.3
            critical_threshold: Pass rate in emergency mode
        """
        self.strict_threshold = strict_threshold
        self.normal_threshold = normal_threshold
        self.relaxed_threshold = relaxed_threshold
        self.critical_threshold = critical_threshold
        
        self.current_mode = "NORMAL"
    
    def get_required_pass_rate(self, health: float) -> float:
        """
        Get required filter pass rate based on health.
        
        Args:
            health: System health (0-1)
            
        Returns:
            Required pass rate (0-1)
            
        Logic:
            health > 0.5: 80% (strict - only good signals)
            0.3 < health ≤ 0.5: 60% (normal - standard filtering)
            0.1 < health ≤ 0.3: 40% (relaxed - allow exploration)
            health ≤ 0.1: 20% (critical - force trades)
        """
        if health > 0.5:
            self.current_mode = "STRICT"
            return self.strict_threshold
        elif health > 0.3:
            self.current_mode = "NORMAL"
            return self.normal_threshold
        elif health > 0.1:
            self.current_mode = "RELAXED"
            return self.relaxed_threshold
        else:
            self.current_mode = "CRITICAL"
            return self.critical_threshold
    
    def relax(
        self,
        filters_passed: int,
        total_filters: int,
        health: float
    ) -> bool:
        """
        Check if signal passes relaxed filter requirements.
        
        Args:
            filters_passed: Number of filters that passed
            total_filters: Total number of filters
            health: System health (0-1)
            
        Returns:
            True if pass_rate >= required_pass_rate
        """
        if total_filters <= 0:
            return True
        
        pass_rate = filters_passed / total_filters
        required = self.get_required_pass_rate(health)
        
        allowed = pass_rate >= required
        
        if not allowed:
            logger.debug(
                f"Signal rejected: {filters_passed}/{total_filters} "
                f"({pass_rate:.0%}) < {required:.0%} [{self.current_mode}]"
            )
        
        return allowed
    
    def get_pass_rate_percent(self, filters_passed: int, total_filters: int, health: float) -> tuple:
        """
        Get pass rate and required rate.
        
        Args:
            filters_passed: Number of filters passed
            total_filters: Total filters
            health: System health
            
        Returns:
            Tuple[actual_rate%, required_rate%, mode]
        """
        if total_filters <= 0:
            return 100.0, self.get_required_pass_rate(health) * 100, self.current_mode
        
        actual = (filters_passed / total_filters) * 100
        required = self.get_required_pass_rate(health) * 100
        
        return actual, required, self.current_mode
    
    def explain(self, filters_passed: int, total_filters: int, health: float) -> str:
        """
        Get human-readable explanation of filter decision.
        
        Args:
            filters_passed: Number of filters passed
            total_filters: Total filters
            health: System health
            
        Returns:
            Explanation string
        """
        actual, required, mode = self.get_pass_rate_percent(filters_passed, total_filters, health)
        
        decision = "✅ RELAXED" if actual >= required else "❌ BLOCKED"
        
        return (
            f"{decision} | {actual:.0f}% ≥ {required:.0f}% | "
            f"Health={health:.2f} ({mode})"
        )


# Integration helpers
def should_relax_filters(
    filters_passed: int,
    total_filters: int,
    health: float
) -> bool:
    """Quick function to check if filters should be relaxed."""
    relaxer = SignalRelaxer()
    return relaxer.relax(filters_passed, total_filters, health)


def get_relaxation_mode(health: float) -> str:
    """Get current relaxation mode based on health."""
    relaxer = SignalRelaxer()
    relaxer.get_required_pass_rate(health)
    return relaxer.current_mode
