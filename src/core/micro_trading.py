"""
Micro Trading Module (V5.1 Patch)

Enables small trades during idle periods to keep system active and learning.
Reduces "zero activity" scenarios by taking smaller, lower-risk trades.

Logic:
  - Idle > 600s: Enable micro trades at 50% size
  - Idle > 900s: Enable micro trades at 20% size
  - Idle > 1200s: Enable micro trades at 10% size
  
This ensures:
  ✅ Continuous learning signal
  ✅ System stays active
  ✅ Low risk capital deployment
  ✅ Feedback for feature learning
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class MicroTrading:
    """
    Enable small trades during idle periods.
    
    Purpose:
        - Keep system active and learning
        - Reduce "zero trades" scenarios
        - Lower capital at risk during learning
    """
    
    def __init__(
        self,
        idle_short: float = 600,      # 10 minutes
        idle_medium: float = 900,     # 15 minutes
        idle_long: float = 1200,      # 20 minutes
        size_short: float = 0.5,      # 50% size
        size_medium: float = 0.2,     # 20% size
        size_long: float = 0.1,       # 10% size
    ):
        """
        Initialize micro trading controller.
        
        Args:
            idle_short: Idle threshold for 50% size (default 600s)
            idle_medium: Idle threshold for 20% size (default 900s)
            idle_long: Idle threshold for 10% size (default 1200s)
            size_short: Position size at idle_short (default 0.5 = 50%)
            size_medium: Position size at idle_medium (default 0.2 = 20%)
            size_long: Position size at idle_long (default 0.1 = 10%)
        """
        self.idle_short = idle_short
        self.idle_medium = idle_medium
        self.idle_long = idle_long
        
        self.size_short = size_short
        self.size_medium = size_medium
        self.size_long = size_long
        
        self.is_micro_mode = False
        self.current_size_multiplier = 1.0
    
    def should_micro_trade(self, idle_time: float) -> bool:
        """
        Check if micro trading should be enabled.
        
        Args:
            idle_time: Seconds since last successful trade
            
        Returns:
            True if idle > minimum threshold
        """
        return idle_time > self.idle_short
    
    def get_size_multiplier(self, idle_time: float) -> float:
        """
        Get position size multiplier based on idle time.
        
        Args:
            idle_time: Seconds since last successful trade
            
        Returns:
            Size multiplier (0.1 to 1.0)
            
        Logic:
            idle < 600s: 1.0 (full size)
            600-900s: 0.5 (micro - 50%)
            900-1200s: 0.2 (micro - 20%)
            1200s+: 0.1 (ultra-micro - 10%)
        """
        if idle_time < self.idle_short:
            self.is_micro_mode = False
            multiplier = 1.0
        elif idle_time < self.idle_medium:
            self.is_micro_mode = True
            multiplier = self.size_short
        elif idle_time < self.idle_long:
            self.is_micro_mode = True
            multiplier = self.size_medium
        else:
            self.is_micro_mode = True
            multiplier = self.size_long
        
        self.current_size_multiplier = multiplier
        return multiplier
    
    def adjust_position_size(
        self,
        base_size: float,
        idle_time: float
    ) -> float:
        """
        Adjust position size for micro trading.
        
        Args:
            base_size: Base position size
            idle_time: Seconds since last trade
            
        Returns:
            Adjusted position size
        """
        multiplier = self.get_size_multiplier(idle_time)
        adjusted_size = base_size * multiplier
        
        if self.is_micro_mode:
            logger.info(
                f"💰 Micro trade: {base_size:.2f} × {multiplier:.0%} "
                f"= {adjusted_size:.2f} (idle {idle_time:.0f}s)"
            )
        
        return adjusted_size
    
    def adjust_trade_params(
        self,
        trade: Dict[str, Any],
        idle_time: float
    ) -> Dict[str, Any]:
        """
        Adjust trade parameters for micro trading.
        
        Args:
            trade: Trade dict with size, tp, sl, etc.
            idle_time: Seconds since last trade
            
        Returns:
            Adjusted trade dict
        """
        adjusted = trade.copy()
        multiplier = self.get_size_multiplier(idle_time)
        
        # Adjust size
        if "size" in adjusted:
            adjusted["size"] = adjusted["size"] * multiplier
        
        # Keep targets the same (same RR)
        # Keep SL the same (same risk in pips)
        
        return adjusted
    
    def get_tier(self, idle_time: float) -> str:
        """
        Get micro trading tier.
        
        Args:
            idle_time: Seconds since last trade
            
        Returns:
            Tier name: "NORMAL", "MICRO_50", "MICRO_20", "ULTRA_MICRO"
        """
        if idle_time < self.idle_short:
            return "NORMAL"
        elif idle_time < self.idle_medium:
            return "MICRO_50"
        elif idle_time < self.idle_long:
            return "MICRO_20"
        else:
            return "ULTRA_MICRO"
    
    def describe(self, idle_time: float) -> str:
        """
        Get description of micro trading state.
        
        Args:
            idle_time: Seconds since last trade
            
        Returns:
            Description string
        """
        tier = self.get_tier(idle_time)
        multiplier = self.get_size_multiplier(idle_time)
        
        return f"{tier} | Size × {multiplier:.0%} | Idle {idle_time:.0f}s"


# Integration helpers
def should_enable_micro_trading(idle_time: float) -> bool:
    """Quick check if micro trading should be enabled."""
    micro = MicroTrading()
    return micro.should_micro_trade(idle_time)


def get_micro_size_multiplier(idle_time: float) -> float:
    """Quick function to get size multiplier."""
    micro = MicroTrading()
    return micro.get_size_multiplier(idle_time)
