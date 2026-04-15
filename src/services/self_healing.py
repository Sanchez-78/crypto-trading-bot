"""
Enhanced Self-Healing Engine

Monitors system health and triggers recovery:
  - Loss streak detection (N consecutive losses)
  - Automatic strategy mutation (genetic evolution)
  - Risk scaling (reduce exposure during degradation)
  - Gradual recovery (restore to normal operations)
"""

import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class EnhancedSelfHealing:
    """Self-healing system with loss streak tracking and genetic mutation."""
    
    def __init__(
        self,
        loss_streak_threshold: int = 5,
        heal_cooldown: float = 120,
        recovery_duration: float = 300
    ):
        """
        Initialize self-healing engine.
        
        Args:
            loss_streak_threshold: Trigger mutation after N losses (default 5)
            heal_cooldown: Minimum seconds between heals (default 120)
            recovery_duration: Time to fully recover (default 300s)
        """
        self.mode = "NORMAL"
        self.loss_streak = 0
        self.last_heal = 0
        self.cooldown = heal_cooldown
        self.recovery_start = None
        self.recovery_duration = recovery_duration
        self.loss_threshold = loss_streak_threshold
        
        # Metrics tracking
        self.trades_since_heal = 0
        self.heal_count = 0
    
    def update_trade(self, trade: Dict[str, Any]) -> None:
        """
        Update loss streak with trade result.
        
        Args:
            trade: Trade dict with pnl or result field
            
        Logic:
            - If trade profitable: reset streak
            - If trade loss: increment streak
            - If streak >= threshold: trigger heal
        """
        pnl = trade.get("pnl", 0)
        result = trade.get("result", "LOSS" if pnl < 0 else "WIN")
        
        if result == "WIN" or pnl >= 0:
            if self.loss_streak > 0:
                logger.info(f"Loss streak broken: was {self.loss_streak}, now 0")
            self.loss_streak = 0
        else:
            self.loss_streak += 1
            logger.warning(f"Loss #{self.loss_streak} - trade PnL: {pnl:.6f}")
        
        self.trades_since_heal += 1
    
    def should_mutate(self) -> bool:
        """
        Check if genetic mutation should be triggered.
        
        Returns:
            True if loss streak >= threshold and cooldown expired
        """
        if self.loss_streak < self.loss_threshold:
            return False
        
        now = time.time()
        if now - self.last_heal < self.cooldown:
            return False
        
        return True
    
    def should_heal(self, metrics: Dict[str, Any]) -> Optional[str]:
        """
        Determine if system needs healing.
        
        Args:
            metrics: Dict with health metrics
            
        Returns:
            Heal reason string or None:
            - "CRITICAL": System malfunction
            - "DRAWDOWN": Max drawdown exceeded
            - "LOSS_STREAK": Consecutive losses
            - "LEARNING": Model degradation
            - None: No healing needed
        """
        health = metrics.get("health", {})
        learning = metrics.get("learning", {})
        equity = metrics.get("equity", {})
        
        status = health.get("status")
        trend = learning.get("state")
        dd = equity.get("drawdown", 0)
        
        # Check critical status
        if status == "BROKEN":
            logger.error("🚨 CRITICAL FAILURE DETECTED")
            return "CRITICAL"
        
        # Check severe drawdown
        if dd > 0.25:
            logger.warning(f"⚠️ SEVERE DRAWDOWN: {dd:.2%}")
            return "DRAWDOWN"
        
        # Check loss streak
        if self.should_mutate():
            logger.warning(f"🔄 LOSS STREAK DETECTED: {self.loss_streak} losses")
            return "LOSS_STREAK"
        
        # Check learning degradation
        if trend == "DEGRADING":
            logger.warning("📉 LEARNING DEGRADATION DETECTED")
            return "LEARNING"
        
        return None
    
    def apply_heal(
        self,
        reason: str,
        auto_control: Any
    ) -> Dict[str, Any]:
        """
        Apply healing action.
        
        Args:
            reason: Type of healing needed
            auto_control: Control object to modify
            
        Returns:
            Healing summary dict
            
        Healing actions:
            - CRITICAL: Pause trading, 20% risk
            - DRAWDOWN: 50% risk cap
            - LOSS_STREAK: 70% risk, mutation signal
            - LEARNING: 70% risk, retraining signal
        """
        now = time.time()
        
        if now - self.last_heal < self.cooldown:
            logger.debug(f"Heal cooldown active ({now - self.last_heal:.0f}s)")
            return {"status": "COOLDOWN"}
        
        self.last_heal = now
        self.heal_count += 1
        self.trades_since_heal = 0
        
        heal_action = {
            "type": reason,
            "timestamp": now,
            "risk_multiplier": 1.0,
            "trading_enabled": True,
            "mutation_requested": False,
        }
        
        if reason == "CRITICAL":
            logger.error(f"🚨 HEAL #{self.heal_count}: CRITICAL - PAUSING")
            auto_control.trading_enabled = False
            auto_control.risk_multiplier = 0.2
            self.mode = "PAUSED"
            heal_action["risk_multiplier"] = 0.2
            heal_action["trading_enabled"] = False
        
        elif reason == "DRAWDOWN":
            logger.warning(f"🔧 HEAL #{self.heal_count}: DRAWDOWN - RISK 50%")
            auto_control.risk_multiplier = 0.5
            self.mode = "SAFE"
            heal_action["risk_multiplier"] = 0.5
        
        elif reason == "LOSS_STREAK":
            logger.warning(f"🧬 HEAL #{self.heal_count}: LOSS STREAK ({self.loss_streak}) - MUTATING")
            auto_control.risk_multiplier = 0.7
            self.mode = "ADAPT"
            heal_action["risk_multiplier"] = 0.7
            heal_action["mutation_requested"] = True
            self.loss_streak = 0  # Reset after mutation signal
        
        elif reason == "LEARNING":
            logger.warning(f"🧠 HEAL #{self.heal_count}: LEARNING - RISK 70%")
            auto_control.risk_multiplier = 0.7
            self.mode = "ADAPT"
            heal_action["risk_multiplier"] = 0.7
        
        self.recovery_start = time.time()
        return heal_action
    
    def check_recovery(self, auto_control: Any) -> Optional[Dict[str, Any]]:
        """
        Check if system should recover to normal operations.
        
        Args:
            auto_control: Control object to modify
            
        Returns:
            Recovery summary or None
            
        Recovery timeline:
            - 0-60s: Pause (if critical)
            - 60-180s: Gradual risk increase
            - 180s+: Full recovery to normal
        """
        if not self.recovery_start:
            return None
        
        elapsed = time.time() - self.recovery_start
        
        recovery_status = {
            "elapsed_seconds": elapsed,
            "recovery_duration": self.recovery_duration,
            "progress": min(100, (elapsed / self.recovery_duration) * 100),
        }
        
        # Phase 1: Resume trading (after 60s)
        if elapsed > 60 and not auto_control.trading_enabled:
            logger.info(f"🟡 Recovery Phase 1 (60s): Re-enabling trading")
            auto_control.trading_enabled = True
            auto_control.risk_multiplier = 0.5
            self.mode = "RECOVERING"
            recovery_status["phase"] = "RESUME_TRADING"
        
        # Phase 2: Increase risk (after 180s)
        elif elapsed > 180 and auto_control.risk_multiplier < 0.9:
            logger.info(f"🟢 Recovery Phase 2 (180s): Restoring full risk")
            auto_control.risk_multiplier = 1.0
            self.mode = "NORMAL"
            self.recovery_start = None
            recovery_status["phase"] = "FULL_RECOVERY"
            recovery_status["status"] = "COMPLETE"
        
        return recovery_status
    
    def update(self, metrics: Dict[str, Any], auto_control: Any) -> Dict[str, Any]:
        """
        Full update cycle: check health → heal → recover.
        
        Args:
            metrics: System metrics
            auto_control: Control object
            
        Returns:
            Update summary dict
        """
        reason = self.should_heal(metrics)
        heal_result = None
        recovery_result = None
        
        if reason:
            heal_result = self.apply_heal(reason, auto_control)
        
        recovery_result = self.check_recovery(auto_control)
        
        return {
            "mode": self.mode,
            "loss_streak": self.loss_streak,
            "heal": heal_result,
            "recovery": recovery_result,
            "heal_count": self.heal_count,
            "trades_since_heal": self.trades_since_heal,
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current system status."""
        return {
            "mode": self.mode,
            "loss_streak": self.loss_streak,
            "healing": self.recovery_start is not None,
            "heal_count": self.heal_count,
            "trades_since_heal": self.trades_since_heal,
        }
    
    def reset(self):
        """Reset healing state (after manual intervention)."""
        self.mode = "NORMAL"
        self.loss_streak = 0
        self.recovery_start = None
        self.heal_count = 0
        logger.info("🔄 Self-healing engine reset")


# Global instance (backward compatible)
self_healing = EnhancedSelfHealing()