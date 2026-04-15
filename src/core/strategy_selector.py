"""
PATCH: Strategy Selector — Choose strategy weighted by fitness + regime.

Two modes:
1. Random weighted by fitness (normal): Higher fitness = higher probability
2. Deterministic best (safety mode): Always use best strategy

Also includes regime-specific strategy adaptation.
"""

import random
import logging

logger = logging.getLogger(__name__)


class StrategySelector:
    """Selects strategies from pool weighted by fitness and regime."""
    
    def __init__(self, pool):
        """
        Initialize selector.
        
        Args:
            pool: GeneticPool instance
        """
        self.pool = pool
        self.selection_count = 0
        self.strategy_usage = {}

    def select(self, regime: str = "RANGING", force_best: bool = False):
        """
        Select a strategy from the pool.
        
        Args:
            regime: Market regime (UPTREND, DOWNTREND, RANGING)
            force_best: If True, always return best strategy (safety mode)
            
        Returns:
            Strategy object
        """
        # ────────────────────────────────────────────────────────────────
        # Safety mode: always use best
        # ────────────────────────────────────────────────────────────────
        if force_best:
            best = max(self.pool.population, key=lambda s: s.fitness)
            self.selection_count += 1
            self.strategy_usage[id(best)] = self.strategy_usage.get(id(best), 0) + 1
            logger.info(f"STRATEGY: Selected best (fitness={best.fitness:.3f}) [FORCE_BEST]")
            return best
        
        # ────────────────────────────────────────────────────────────────
        # Normal mode: weighted selection by fitness
        # ────────────────────────────────────────────────────────────────
        total_fitness = sum(s.fitness for s in self.pool.population)
        
        if total_fitness <= 0:
            # Cold start: all strategies have zero fitness
            strategy = random.choice(self.pool.population)
            logger.debug(f"STRATEGY: Cold start (random selection)")
        else:
            # Weighted by fitness
            pick = random.uniform(0, total_fitness)
            current = 0.0
            
            strategy = None
            for s in self.pool.population:
                current += s.fitness
                if current >= pick:
                    strategy = s
                    break
            
            if strategy is None:
                strategy = self.pool.population[-1]
        
        # ────────────────────────────────────────────────────────────────
        # Regime adaptation (optional: adjust parameters based on regime)
        # ────────────────────────────────────────────────────────────────
        # (Could apply regime-specific multipliers here)
        # For now, just track usage
        
        self.selection_count += 1
        strat_id = id(strategy)
        self.strategy_usage[strat_id] = self.strategy_usage.get(strat_id, 0) + 1
        
        return strategy

    def get_usage_stats(self) -> dict:
        """Get per-strategy usage statistics."""
        stats = {}
        for strat in self.pool.population:
            sid = id(strat)
            usage = self.strategy_usage.get(sid, 0)
            stats[str(strat.dna)] = {
                'usage_count': usage,
                'fitness': strat.fitness,
                'trades': strat.trades_total,
                'pnl': strat.pnl_total,
            }
        return stats

    def __repr__(self):
        return f"Selector(selections={self.selection_count}, pool_size={len(self.pool.population)})"


def select_strategy(pool, regime: str = "RANGING", force_best: bool = False):
    """
    Standalone function to select strategy (for convenience).
    
    Args:
        pool: GeneticPool instance
        regime: Market regime
        force_best: Force best strategy (safety mode)
        
    Returns:
        Strategy object
    """
    selector = StrategySelector(pool)
    return selector.select(regime, force_best)
