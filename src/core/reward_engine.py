"""
PATCH: Reward Engine — Calculate RL rewards from trade outcomes.

Maps trade results (PnL, exit reason, duration) into
numerical rewards for RL learning.

Reward calculation:
- Base: PnL (profit/loss)
- Bonus: +0.0005 for fast take-profit
- Bonus: +0.0001 for quick exit
- Penalty: -50% loss for timeout (slow exit)
- Penalty: -30% loss for stop-loss
- Penalty: -0.0001 per bar held (discourages slow trades)

Result: Agents learn to:
1. Maximize profitability (base reward)
2. Exit quickly (bonus for TP)
3. Avoid timeout (penalty)
4. Avoid unnecessary holds (penalty per bar)
"""

import logging

logger = logging.getLogger(__name__)


class RewardEngine:
    """Calculate RL rewards from trade outcomes."""
    
    def __init__(self):
        """Initialize reward engine with parameters."""
        self.total_rewards = 0.0
        self.reward_count = 0
        self.avg_reward = 0.0

    def compute(self, trade: dict) -> float:
        """
        Compute reward for a closed trade.
        
        Args:
            trade: Trade dict with:
                - pnl: P&L in percent (0.05 = +5%)
                - exit_reason: "tp", "sl", "timeout", "manual"
                - duration_seconds: How long trade was open
                - bars_held: Number of candles (if available)
                
        Returns:
            Reward (scalar, typically -0.001 to +0.001)
        """
        try:
            pnl = float(trade.get('pnl', 0.0))
            exit_reason = str(trade.get('exit_reason', 'unknown')).lower()
            duration_s = float(trade.get('duration_seconds', 0))
            bars_held = int(trade.get('bars_held', 1))
            
            # ────────────────────────────────────────────────────────────
            # Base reward: PnL (primary signal)
            # ────────────────────────────────────────────────────────────
            reward = pnl
            
            # ────────────────────────────────────────────────────────────
            # Bonuses: encourage desired behavior
            # ────────────────────────────────────────────────────────────
            
            # Bonus for take-profit exit (disciplined, clear targets)
            if exit_reason == 'tp':
                reward += 0.0005
            
            # Bonus for quick exit (fast execution = less risk)
            if duration_s > 0 and duration_s < 300:  # < 5 min
                reward += 0.0001
            
            # ────────────────────────────────────────────────────────────
            # Penalties: discourage undesired behavior
            # ────────────────────────────────────────────────────────────
            
            # Penalty for timeout exit (indecisive, waiting too long)
            if exit_reason == 'timeout':
                reward -= abs(pnl) * 0.5
            
            # Penalty for stop-loss exit (defensive, but still bad)
            if exit_reason == 'sl':
                reward -= abs(pnl) * 0.3
            
            # Penalty for holding too long (per bar)
            if bars_held > 10:
                reward -= 0.0001 * (bars_held - 10)
            
            # Penalty for negative trades (doubles the pain)
            if pnl < -0.01:  # loss > 1%
                reward -= 0.0002
            
            # ────────────────────────────────────────────────────────────
            # Update statistics
            # ────────────────────────────────────────────────────────────
            self.total_rewards += reward
            self.reward_count += 1
            self.avg_reward = self.total_rewards / self.reward_count if self.reward_count > 0 else 0
            
            return reward
            
        except Exception as e:
            logger.warning(f"Reward computation error: {e}")
            return 0.0

    def compute_batch(self, trades: list) -> float:
        """
        Compute reward for batch of trades.
        
        Args:
            trades: List of trade dicts
            
        Returns:
            Total reward
        """
        total = 0.0
        for trade in trades:
            total += self.compute(trade)
        return total

    def get_stats(self) -> dict:
        """Get reward statistics."""
        return {
            'total_rewards': round(self.total_rewards, 5),
            'trades_rewarded': self.reward_count,
            'avg_reward': round(self.avg_reward, 5),
        }

    def reset_stats(self):
        """Reset statistics."""
        self.total_rewards = 0.0
        self.reward_count = 0
        self.avg_reward = 0.0

    def __repr__(self):
        return (
            f"RewardEngine(total={self.total_rewards:.5f}, "
            f"count={self.reward_count}, avg={self.avg_reward:.5f})"
        )


# ────────────────────────────────────────────────────────────────────────────
# Reward signal interpretation
# ────────────────────────────────────────────────────────────────────────────

reward_interpretation = {
    '>0.005': '🎉 EXCELLENT: High profit + fast exit',
    '0.0025-0.005': '✅ GOOD: Decent profit with bonus',
    '0-0.0025': '✓ OK: Small profit',
    '-0.001-0': '⚠️  SMALL_LOSS: Breaking even',
    '-0.005--0.001': '❌ LOSS: Acceptable loss',
    '<-0.005': '🔴 SEVERE: Big loss or timeout',
}
