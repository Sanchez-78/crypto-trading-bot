"""
Exit Optimizer Module (V5.1 Patch)

Prevents timeout exits by forcing position closure when trade is open too long.
Reduces "waiting forever" scenarios that dominate the exit distribution.

Logic:
  - Duration > 10 bars: Reduce TP by 30% (force exit faster)
  - Duration > 20 bars: Force immediate exit (no more waiting)
  - Duration > 30 bars: Critical exit (close at market)

This ensures:
  ✅ No trades stuck for hours
  ✅ Faster feedback for learning
  ✅ Capital freed for new signals
"""

import logging
from typing import Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ExitDecision(Enum):
    """Exit decision types."""
    HOLD = "HOLD"
    TIGHTEN_TP = "TIGHTEN_TP"
    CLOSE_SLOW = "CLOSE_SLOW"
    FORCE_EXIT = "FORCE_EXIT"
    MARKET_CLOSE = "MARKET_CLOSE"


class ExitOptimizer:
    """
    Optimize exit timing to prevent indefinite holds.
    
    Purpose:
        - Reduce timeout exits (85% → <40%)
        - Ensure faster feedback for learning
        - Free capital for new opportunities
    """
    
    def __init__(
        self,
        tight_duration: int = 10,    # Bars: tighten TP
        close_duration: int = 20,    # Bars: force exit
        market_duration: int = 30,   # Bars: market close
    ):
        """
        Initialize exit optimizer.
        
        Args:
            tight_duration: Duration to tighten TP (default 10 bars)
            close_duration: Duration to force exit (default 20 bars)
            market_duration: Duration to market close (default 30 bars)
        """
        self.tight_duration = tight_duration
        self.close_duration = close_duration
        self.market_duration = market_duration
    
    def analyze_trade(self, trade: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze trade for exit optimization.
        
        Args:
            trade: Trade dict with:
                - duration_bars: Bars since entry
                - entry_price: Entry price
                - tp_price: Take-profit price
                - sl_price: Stop-loss price
                - current_price: Current price
                
        Returns:
            Analysis dict with recommendation
        """
        duration = trade.get("duration_bars", 0)
        entry = trade.get("entry_price", 0)
        tp = trade.get("tp_price", 0)
        sl = trade.get("sl_price", 0)
        current = trade.get("current_price", 0)
        
        analysis = {
            "duration_bars": duration,
            "entry_price": entry,
            "tp_price": tp,
            "sl_price": sl,
            "current_price": current,
            "exit_decision": ExitDecision.HOLD,
            "adjusted_tp": tp,
            "reason": "NORMAL",
        }
        
        # GREEN ZONE: Trade is working
        if current > entry:
            # Market is moving our direction
            analysis["reason"] = "PROFITABLE"
            analysis["exit_decision"] = ExitDecision.HOLD
            return analysis
        
        # YELLOW ZONE: Trade duration
        if duration >= self.market_duration:
            logger.warning(f"🔴 CRITICAL EXIT: Trade open {duration} bars")
            analysis["exit_decision"] = ExitDecision.MARKET_CLOSE
            analysis["reason"] = "CRITICAL_DURATION"
            return analysis
        
        if duration >= self.close_duration:
            logger.warning(f"🟠 FORCE EXIT: Trade open {duration} bars")
            analysis["exit_decision"] = ExitDecision.FORCE_EXIT
            analysis["reason"] = "FORCE_DURATION"
            return analysis
        
        if duration >= self.tight_duration:
            # Tighten TP: move closer to current price
            tight_tp = current + (tp - current) * 0.7  # 70% of original TP
            logger.info(f"🟡 TIGHTEN TP: {tp:.8f} → {tight_tp:.8f}")
            analysis["exit_decision"] = ExitDecision.TIGHTEN_TP
            analysis["adjusted_tp"] = tight_tp
            analysis["reason"] = "TIGHTEN_DURATION"
            return analysis
        
        # RED ZONE: Negative trade
        if current < sl:
            logger.info(f"📍 SL HIT: {current:.8f} < {sl:.8f}")
            analysis["exit_decision"] = ExitDecision.CLOSE_SLOW
            analysis["reason"] = "SL_HIT"
            return analysis
        
        return analysis
    
    def get_exit_action(self, trade: Dict[str, Any]) -> str:
        """
        Get exit action recommendation.
        
        Args:
            trade: Trade dict
            
        Returns:
            Action: "HOLD", "TIGHTEN_TP", "CLOSE", or "MARKET_CLOSE"
        """
        analysis = self.analyze_trade(trade)
        decision = analysis["exit_decision"]
        
        action_map = {
            ExitDecision.HOLD: "HOLD",
            ExitDecision.TIGHTEN_TP: "TIGHTEN_TP",
            ExitDecision.CLOSE_SLOW: "CLOSE",
            ExitDecision.FORCE_EXIT: "CLOSE",
            ExitDecision.MARKET_CLOSE: "MARKET_CLOSE",
        }
        
        return action_map.get(decision, "HOLD")
    
    def should_close_immediately(self, trade: Dict[str, Any]) -> bool:
        """
        Check if trade should be closed immediately.
        
        Args:
            trade: Trade dict
            
        Returns:
            True if should close immediately
        """
        decision = self.analyze_trade(trade)["exit_decision"]
        return decision in (ExitDecision.FORCE_EXIT, ExitDecision.MARKET_CLOSE)
    
    def get_adjusted_targets(self, trade: Dict[str, Any]) -> tuple:
        """
        Get adjusted exit targets.
        
        Args:
            trade: Trade dict
            
        Returns:
            Tuple[tp, sl] with any adjustments
        """
        analysis = self.analyze_trade(trade)
        
        return (
            analysis["adjusted_tp"],
            trade.get("sl_price", 0),  # SL unchanged
        )
    
    def describe_decision(self, trade: Dict[str, Any]) -> str:
        """
        Get human-readable exit decision.
        
        Args:
            trade: Trade dict
            
        Returns:
            Description string
        """
        analysis = self.analyze_trade(trade)
        decision = analysis["exit_decision"].value
        reason = analysis["reason"]
        duration = analysis["duration_bars"]
        
        return f"{decision} | Duration={duration} | {reason}"


# Integration helpers
def should_force_exit(trade: Dict[str, Any]) -> bool:
    """Quick check if trade should be force-closed."""
    optimizer = ExitOptimizer()
    return optimizer.should_close_immediately(trade)


def analyze_exit(trade: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze exit for a trade."""
    optimizer = ExitOptimizer()
    return optimizer.analyze_trade(trade)
