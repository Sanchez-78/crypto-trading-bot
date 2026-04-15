"""
Adaptive EV Gate Module (V5.1 Patch)

Relaxes EV threshold when system health is low or trading has been idle.
Prevents "frozen" state where all signals are rejected due to strict filtering.

Logic:
  - Normal state: Strict threshold (≥ 0.0)
  - Low health: Relaxed threshold (≥ -0.02)
  - Idle timeout: Very relaxed threshold (≥ -0.01)
  
This enables the system to:
  1. Explore more signals when learning is weak
  2. Step out of traps where all signals fail
  3. Force system to trade and learn
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AdaptiveEVGate:
    """
    Adaptive expected value gate that relaxes thresholds based on system state.
    
    Purpose:
        - Prevent system freeze (0 trades = 0 data = no learning)
        - Enable exploration when health is low
        - Force exit from bad states
    """
    
    def __init__(
        self,
        base_threshold: float = 0.0,
        min_threshold: float = -0.02,
        max_threshold: float = 0.05,
        idle_timeout: float = 600,  # 10 minutes
        health_threshold: float = 0.2,
    ):
        """
        Initialize adaptive EV gate.
        
        Args:
            base_threshold: Normal EV threshold (default 0.0)
            min_threshold: Minimum allowed threshold (default -0.02)
            max_threshold: Maximum allowed threshold (default 0.05)
            idle_timeout: Time in seconds before relaxing for idle (default 600)
            health_threshold: Health below this triggers relaxation (default 0.2)
        """
        self.base_threshold = base_threshold
        self.min_threshold = min_threshold
        self.max_threshold = max_threshold
        self.idle_timeout = idle_timeout
        self.health_threshold = health_threshold
        
        self.current_threshold = base_threshold
        self.was_relaxed = False
    
    def adjust(
        self,
        health: float,
        idle_time: float,
        filter_pass_rate: float = 1.0
    ) -> float:
        """
        Adjust EV threshold based on system state.
        
        Args:
            health: System health score (0-1)
            idle_time: Seconds since last successful trade
            filter_pass_rate: Percentage of signals passing filters (0-1)
            
        Returns:
            Adjusted EV threshold
            
        Logic:
            1. If health < 0.2: Use min_threshold (-0.02)
            2. If idle_time > 600s: Use -0.01 (very relaxed)
            3. If filter_pass_rate < 0.1: Use -0.01 (force trades)
            4. Otherwise: Use base_threshold (0.0)
        """
        
        # Start with base
        new_threshold = self.base_threshold
        reason = "NORMAL"
        
        # Check idle timeout (most important for unfreeze)
        if idle_time > self.idle_timeout:
            new_threshold = -0.01
            reason = f"IDLE ({idle_time:.0f}s)"
        
        # Check health
        elif health < self.health_threshold:
            new_threshold = self.min_threshold
            reason = f"LOW_HEALTH ({health:.2f})"
        
        # Check filter pass rate (critical)
        elif filter_pass_rate < 0.1:
            new_threshold = -0.01
            reason = f"FILTER_BLOCKED ({filter_pass_rate:.1%})"
        
        # Clamp to bounds
        new_threshold = max(self.min_threshold, min(self.max_threshold, new_threshold))
        
        # Log state change
        is_relaxed = new_threshold < self.base_threshold
        if is_relaxed != self.was_relaxed:
            status = "🔓 RELAXED" if is_relaxed else "🔒 NORMAL"
            logger.warning(f"{status} EV Gate: {reason} → threshold={new_threshold:.3f}")
            self.was_relaxed = is_relaxed
        
        self.current_threshold = new_threshold
        return new_threshold
    
    def allow_trade(self, ev: float, threshold: Optional[float] = None) -> bool:
        """
        Check if EV passes the gate.
        
        Args:
            ev: Expected value to check
            threshold: Optional threshold (uses last adjusted if None)
            
        Returns:
            True if ev >= threshold
        """
        if threshold is None:
            threshold = self.current_threshold
        
        return ev >= threshold
    
    def get_severity(self) -> str:
        """
        Get current gate severity level.
        
        Returns:
            String: "STRICT", "NORMAL", "RELAXED", "CRITICAL"
        """
        diff = self.base_threshold - self.current_threshold
        
        if diff < 0:
            return "STRICT"
        elif diff < 0.01:
            return "NORMAL"
        elif diff < 0.03:
            return "RELAXED"
        else:
            return "CRITICAL"
    
    def reset(self):
        """Reset to base threshold."""
        self.current_threshold = self.base_threshold
        self.was_relaxed = False
        logger.info("🔄 EV Gate reset to base threshold")


# Convenience function for integration
def create_adaptive_gate(
    base_threshold: float = 0.0,
    min_threshold: float = -0.02
) -> AdaptiveEVGate:
    """Create an adaptive EV gate with default settings."""
    return AdaptiveEVGate(base_threshold, min_threshold)
