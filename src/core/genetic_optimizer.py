"""
Genetic Optimizer Module

Implements evolutionary strategy adaptation for market-driven parameter tuning.
Used by Self-Healing Engine to mutate strategy parameters after loss streaks.

Genetic operations:
  - MUTATE: Random parameter perturbation
  - CROSSOVER: Blend two strategies
  - SELECTION: Fitness-based filtering
"""

import random
import copy
import logging
from typing import Dict, List, Tuple, Any

logger = logging.getLogger(__name__)


class GeneticOptimizer:
    """Evolutionary strategy for dynamic parameter tuning."""
    
    def __init__(self):
        """Initialize genetic optimizer with mutation ranges."""
        # Mutation ranges (parameter_name -> (min_delta, max_delta, step))
        self.mutation_ranges = {
            "ema_fast": (-2, 2, 1),      # ±2 candles
            "ema_slow": (-5, 5, 1),      # ±5 candles
            "rsi_overbought": (-5, 5, 1),  # ±5
            "rsi_oversold": (-5, 5, 1),    # ±5
            "atr_multiplier": (-0.2, 0.2, 0.05),  # ±0.2
            "bb_period": (-2, 2, 1),      # ±2 candles
            "bb_std_dev": (-0.5, 0.5, 0.1),  # ±0.5
        }
    
    def mutate(self, strategy: Dict[str, Any], mutation_rate: float = 0.3) -> Dict[str, Any]:
        """
        Apply random mutations to strategy parameters.
        
        Args:
            strategy: Original strategy dict (not modified)
            mutation_rate: Probability of mutating each parameter (default 0.3)
            
        Returns:
            New mutated strategy (deep copy)
            
        Example:
            >>> orig = {"ema_fast": 12, "ema_slow": 26}
            >>> mutant = optimizer.mutate(orig)
            >>> # mutant might be {"ema_fast": 13, "ema_slow": 25}
        """
        mutant = copy.deepcopy(strategy)
        
        for param in mutant:
            if param not in self.mutation_ranges:
                continue
            
            if random.random() > mutation_rate:
                continue
            
            min_delta, max_delta, step = self.mutation_ranges[param]
            
            # Random perturbation
            delta = random.randint(int(min_delta / step), int(max_delta / step)) * step
            
            old_val = mutant[param]
            new_val = old_val + delta
            
            # Bounds checking (basic)
            if param == "ema_fast":
                new_val = max(2, min(50, new_val))
            elif param == "ema_slow":
                new_val = max(20, min(200, new_val))
            elif param in ("rsi_overbought", "rsi_oversold"):
                new_val = max(0, min(100, new_val))
            elif param == "atr_multiplier":
                new_val = max(0.5, min(3.0, new_val))
            
            mutant[param] = new_val
            logger.debug(f"Mutated {param}: {old_val} → {new_val}")
        
        return mutant
    
    def crossover(
        self,
        parent1: Dict[str, Any],
        parent2: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Blend two strategies (uniform crossover).
        
        Each parameter is randomly chosen from parent1 or parent2.
        
        Args:
            parent1: First parent strategy
            parent2: Second parent strategy
            
        Returns:
            Tuple of two offspring strategies
            
        Example:
            >>> p1 = {"ema_fast": 12, "ema_slow": 26}
            >>> p2 = {"ema_fast": 14, "ema_slow": 24}
            >>> c1, c2 = optimizer.crossover(p1, p2)
            >>> # c1 might be {"ema_fast": 12, "ema_slow": 24}
        """
        child1 = {}
        child2 = {}
        
        keys = set(parent1.keys()) | set(parent2.keys())
        
        for key in keys:
            if random.random() < 0.5:
                child1[key] = copy.deepcopy(parent1.get(key, parent2[key]))
                child2[key] = copy.deepcopy(parent2.get(key, parent1[key]))
            else:
                child1[key] = copy.deepcopy(parent2.get(key, parent1[key]))
                child2[key] = copy.deepcopy(parent1.get(key, parent2[key]))
        
        return child1, child2
    
    def evolve_population(
        self,
        population: List[Tuple[Dict[str, Any], float]],
        generations: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Evolve a population of strategies over multiple generations.
        
        Population should be list of (strategy, fitness) tuples.
        Fitness is a scalar (higher = better).
        
        Args:
            population: List of (strategy, fitness) tuples
            generations: Number of evolution rounds (default 3)
            
        Returns:
            Evolved population of strategies (top 50%)
            
        Algorithm:
            1. Sort by fitness (survival of fittest)
            2. Keep top 50%
            3. Mutate & crossover to reach original size
            4. Repeat for N generations
        """
        if not population:
            return []
        
        current_pop = copy.deepcopy(population)
        
        for gen in range(generations):
            # Sort by fitness (descending)
            current_pop.sort(key=lambda x: x[1], reverse=True)
            
            # Keep top 50%
            elite_count = max(1, len(current_pop) // 2)
            elite = [s for s, _ in current_pop[:elite_count]]
            
            logger.debug(f"Gen {gen}: Elite size {len(elite)}, avg fitness {sum(f for _, f in current_pop[:elite_count]) / elite_count:.4f}")
            
            # Regenerate population
            next_pop = [(s, 0.0) for s in elite]  # Keep elite
            
            while len(next_pop) < len(current_pop):
                if random.random() < 0.5 and len(elite) > 1:
                    # Crossover
                    p1, p2 = random.sample(elite, 2)
                    c1, c2 = self.crossover(p1, p2)
                    next_pop.extend([(c1, 0.0), (c2, 0.0)])
                else:
                    # Mutate
                    parent = random.choice(elite)
                    child = self.mutate(parent)
                    next_pop.append((child, 0.0))
            
            current_pop = next_pop[:len(population)]
        
        return [s for s, _ in current_pop]
    
    @staticmethod
    def fitness_score(
        winrate: float,
        expectancy: float,
        sharpe_ratio: float,
        max_drawdown: float
    ) -> float:
        """
        Compute composite fitness score.
        
        Combines multiple metrics into single fitness value.
        
        Args:
            winrate: Win rate (0-1)
            expectancy: Average trade profit (positive = good)
            sharpe_ratio: Risk-adjusted return
            max_drawdown: Maximum drawdown (negative = bad)
            
        Returns:
            Composite fitness score (higher = better)
            
        Formula: F = winrate + expectancy + (sharpe_ratio * 0.5) - (max_drawdown * 2)
        """
        fitness = (
            winrate +  # [0-1]
            expectancy +  # Typically [-1, 1]
            (sharpe_ratio * 0.5) +  # Risk-adjusted
            (-max_drawdown * 2)  # Penalize drawdowns
        )
        return fitness


def mutate(strategy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function for single mutation.
    
    Args:
        strategy: Strategy dict
        
    Returns:
        Mutated strategy
    """
    optimizer = GeneticOptimizer()
    return optimizer.mutate(strategy)


def crossover(
    parent1: Dict[str, Any],
    parent2: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Convenience function for crossover.
    
    Args:
        parent1: First parent
        parent2: Second parent
        
    Returns:
        Tuple of two offspring
    """
    optimizer = GeneticOptimizer()
    return optimizer.crossover(parent1, parent2)
