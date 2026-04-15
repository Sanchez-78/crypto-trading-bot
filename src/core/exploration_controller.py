"""
Exploration Controller Module (V5.1 Patch)

Dynamically adjusts RL agent exploration (epsilon) based on system state.
Forces the agent to explore when trading is frozen or health is low.

Logic:
  - Normal: epsilon = 0.05 (5% exploration)
  - Idle > 900s: epsilon = 0.6 (60% exploration - force trades)
  - Health < 0.2: epsilon = 0.3 (30% exploration - try new things)
  - Idle > 1200s: epsilon = 0.9 (90% exploration - emergency mode)

This prevents the RL agent from getting stuck in "always HOLD" patterns.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ExplorationController:
    """
    Dynamically control RL exploration based on system state.
    
    Purpose:
        - Prevent HOLD-only policies (no exploration)
        - Force exploration when trading is stuck
        - Learn new strategies when current one fails
    """
    
    def __init__(
        self,
        base_epsilon: float = 0.05,
        idle_timeout_1: float = 900,    # 15 minutes
        idle_timeout_2: float = 1200,   # 20 minutes
        health_threshold: float = 0.2,
    ):
        """
        Initialize exploration controller.
        
        Args:
            base_epsilon: Base exploration rate (default 0.05 = 5%)
            idle_timeout_1: First idle threshold in seconds (default 900s)
            idle_timeout_2: Critical idle threshold in seconds (default 1200s)
            health_threshold: Health below this increases exploration (default 0.2)
        """
        self.base_epsilon = base_epsilon
        self.idle_timeout_1 = idle_timeout_1
        self.idle_timeout_2 = idle_timeout_2
        self.health_threshold = health_threshold
        
        self.current_epsilon = base_epsilon
        self.current_mode = "NORMAL"
    
    def adjust(
        self,
        idle_time: float,
        health: float,
        trade_count: int = 0,
        recent_winrate: float = 0.5
    ) -> float:
        """
        Adjust exploration rate based on system state.
        
        Args:
            idle_time: Seconds since last successful trade
            health: System health (0-1)
            trade_count: Number of trades with current policy
            recent_winrate: Win rate in last N trades
            
        Returns:
            Adjusted epsilon (exploration rate)
            
        Logic:
            1. If idle > 1200s: 0.9 (emergency - try everything)
            2. If idle > 900s: 0.6 (exploration mode)
            3. If health < 0.2: 0.3 (low confidence exploration)
            4. If health < 0.1: 0.7 (critical exploration)
            5. If winrate < 0.40: 0.2 (strategy failing, explore)
            6. Otherwise: 0.05 (normal)
        """
        
        # Start with base
        new_epsilon = self.base_epsilon
        reason = "NORMAL"
        
        # CRITICAL: Idle too long
        if idle_time > self.idle_timeout_2:
            new_epsilon = 0.9
            reason = f"CRITICAL_IDLE ({idle_time:.0f}s)"
        
        # URGENT: Idle for threshold time
        elif idle_time > self.idle_timeout_1:
            new_epsilon = 0.6
            reason = f"IDLE ({idle_time:.0f}s)"
        
        # LOW HEALTH: System struggling
        elif health < 0.1:
            new_epsilon = 0.7
            reason = f"CRITICAL_HEALTH ({health:.2f})"
        
        elif health < self.health_threshold:
            new_epsilon = 0.3
            reason = f"LOW_HEALTH ({health:.2f})"
        
        # BAD WINRATE: Current strategy failing
        elif recent_winrate < 0.40:
            new_epsilon = 0.2
            reason = f"BAD_WR ({recent_winrate:.1%})"
        
        # Clamp to valid range
        new_epsilon = max(0.0, min(1.0, new_epsilon))
        
        # Log state change
        if new_epsilon != self.current_epsilon:
            logger.warning(
                f"🔄 RL Epsilon adjusted: {self.current_epsilon:.2f} → {new_epsilon:.2f} | {reason}"
            )
        
        self.current_epsilon = new_epsilon
        self._update_mode(new_epsilon)
        
        return new_epsilon
    
    def _update_mode(self, epsilon: float):
        """Update exploration mode based on epsilon."""
        if epsilon < 0.1:
            self.current_mode = "EXPLOIT"
        elif epsilon < 0.3:
            self.current_mode = "BALANCED"
        elif epsilon < 0.7:
            self.current_mode = "EXPLORE"
        else:
            self.current_mode = "CRITICAL"
    
    def get_current_epsilon(self) -> float:
        """Get current epsilon value."""
        return self.current_epsilon
    
    def get_current_mode(self) -> str:
        """Get current exploration mode."""
        return self.current_mode
    
    def should_force_action(self) -> bool:
        """
        Check if we should force a non-HOLD action.
        
        Returns:
            True if epsilon is high enough to force action
        """
        # If epsilon > 0.5, we're in exploration mode
        return self.current_epsilon > 0.5
    
    def describe(self) -> dict:
        """Get description of current exploration state."""
        return {
            "epsilon": self.current_epsilon,
            "mode": self.current_mode,
            "force_action": self.should_force_action(),
            "exploration_rate": f"{self.current_epsilon*100:.0f}%",
        }
    
    def reset(self):
        """Reset to base exploration rate."""
        self.current_epsilon = self.base_epsilon
        self.current_mode = "NORMAL"
        logger.info("🔄 Exploration controller reset to base epsilon")


# Integration helpers
def create_exploration_controller(base_epsilon: float = 0.05) -> ExplorationController:
    """Create exploration controller with default settings."""
    return ExplorationController(base_epsilon)


def should_explore(
    idle_time: float,
    health: float,
    base_epsilon: float = 0.05
) -> bool:
    """Quick check if we should explore."""
    controller = ExplorationController(base_epsilon)
    epsilon = controller.adjust(idle_time, health)
    
    # Explore if epsilon > 0.1
    return epsilon > 0.1
