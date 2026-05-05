"""
PATCH: Genetic Pool — Population of strategies with evolution.

Manages:
- Population of N strategies
- Selection of top performers
- Reproduction (create offspring)
- Mutation (add variation)
- Diversity control (prevent inbreeding)
- Anti-collapse safety (preserve best)

Evolution cycle:
1. Select top performers (elite)
2. Create offspring (clone + mutate)
3. Replace weakest with offspring
4. Check diversity; inject new if stagnant
5. Preserve global best
"""

import random
import logging
import copy
from typing import List

logger = logging.getLogger(__name__)


class GeneticPool:
    """Population of trading strategies with genetic operations."""
    
    def __init__(self, size: int = 20):
        """
        Initialize population.
        
        Args:
            size: Number of strategies in population (default 20)
        """
        from src.core.strategy_dna import StrategyDNA
        from src.core.strategy import Strategy
        
        self.population: List[Strategy] = [
            Strategy(dna=StrategyDNA(), generation=0)
            for _ in range(size)
        ]
        self.global_best: Strategy = None
        self.evolution_count = 0
        self.initial_size = size

    def select_top(self, k: int = 5) -> List:
        """
        Select top K performers by fitness.
        
        Args:
            k: Number of elite to select
            
        Returns:
            List of top K strategies sorted by fitness descending
        """
        return sorted(self.population, key=lambda s: s.fitness, reverse=True)[:k]

    def select_one_weighted(self):
        """
        Select a single strategy weighted by fitness.
        Higher fitness = higher probability of selection.
        
        Used for reproduction: fittest reproduce more often.
        """
        total_fitness = sum(s.fitness for s in self.population)
        
        if total_fitness <= 0:
            # All strategies have zero fitness; pick randomly
            return random.choice(self.population)
        
        # Weighted selection
        pick = random.uniform(0, total_fitness)
        current = 0.0
        
        for strategy in self.population:
            current += strategy.fitness
            if current >= pick:
                return strategy
        
        # Fallback (shouldn't reach here)
        return self.population[-1]

    def evolve(self):
        """
        Evolve population:
        1. Keep elite (top 25%)
        2. Create offspring from elite (75%)
        3. Mutate offspring
        4. Replace weakest with offspring
        5. Check diversity
        6. Preserve global best
        """
        self.evolution_count += 1
        
        # ────────────────────────────────────────────────────────────────
        # Step 1: Identify elite (top 25%)
        # ────────────────────────────────────────────────────────────────
        elite_count = max(1, len(self.population) // 4)
        elite = self.select_top(elite_count)
        
        logger.info(
            f"EVOLVE #{self.evolution_count}: "
            f"Population={len(self.population)}, Elite={len(elite)}, "
            f"Best fitness={elite[0].fitness:.3f}"
        )
        
        # ────────────────────────────────────────────────────────────────
        # Step 2: Create offspring pool
        # ────────────────────────────────────────────────────────────────
        new_population = []
        
        # Keep elites as-is
        new_population.extend(elite)
        
        # Create offspring to fill population
        while len(new_population) < len(self.population):
            # Select parent from elite weighted by fitness
            total_fit = sum(s.fitness for s in elite)
            if total_fit <= 0:
                parent = random.choice(elite)
            else:
                pick = random.uniform(0, total_fit)
                cumulative = 0.0
                parent = elite[-1]
                for s in elite:
                    cumulative += s.fitness
                    if cumulative >= pick:
                        parent = s
                        break
            
            # Clone DNA
            child_dna = copy.deepcopy(parent.dna)
            
            # Mutate
            child_dna.mutate()
            
            # Create new strategy
            from src.core.strategy import Strategy
            child = Strategy(
                dna=child_dna,
                generation=parent.generation + 1
            )
            child.fitness = parent.fitness * 0.5  # Inherited seed; overwritten after first trade

            new_population.append(child)
        
        # ────────────────────────────────────────────────────────────────
        # Step 3: Replace population
        # ────────────────────────────────────────────────────────────────
        self.population = new_population
        
        # ────────────────────────────────────────────────────────────────
        # Step 4: Diversity check (prevent inbreeding)
        # ────────────────────────────────────────────────────────────────
        # BUG-034 fix: scale diversity threshold with population size
        min_diversity = max(3, len(self.population) // 4)
        diversity = self._diversity_score()
        if diversity < min_diversity:
            logger.warning(f"Low diversity detected ({diversity}/{min_diversity}); injecting random strategies...")
            from src.core.strategy_dna import StrategyDNA
            from src.core.strategy import Strategy

            for _ in range(2):
                random_dna = StrategyDNA()
                random_strat = Strategy(dna=random_dna, generation=self.evolution_count)
                random_strat.fitness = 0.1  # Neutral seed so random strategies participate in selection
                # BUG-018 fix: find actual weakest strategy, not just last index
                weakest_idx = min(range(len(self.population)),
                                  key=lambda i: self.population[i].fitness)
                self.population[weakest_idx] = random_strat

            logger.info(f"Injected random strategies. New diversity={self._diversity_score()}")
        
        # ────────────────────────────────────────────────────────────────
        # Step 5: Preserve global best (anti-collapse safety)
        # ────────────────────────────────────────────────────────────────
        # BUG-019 fix: initialize global_best on first evolution, not skip it
        current_best = max(self.population, key=lambda s: s.fitness)
        if self.global_best is None or current_best.fitness > self.global_best.fitness:
            self.global_best = copy.deepcopy(current_best)
        else:
            # Restore global best — BUG-018 fix: replace actual weakest
            weakest_idx = min(range(len(self.population)),
                              key=lambda i: self.population[i].fitness)
            self.population[weakest_idx] = copy.deepcopy(self.global_best)
            logger.info(f"Restoring global best (fitness={self.global_best.fitness:.3f})")

    def _diversity_score(self) -> int:
        """
        Measure genetic diversity in population.
        
        Returns count of unique DNA configurations.
        """
        unique_dnas = set()
        for strat in self.population:
            # Create hash of DNA parameters
            dna_tuple = tuple(sorted(strat.dna.to_dict().items()))
            unique_dnas.add(dna_tuple)
        return len(unique_dnas)

    def get_stats(self) -> dict:
        """Get population statistics."""
        fitnesses = [s.fitness for s in self.population]
        trades = [s.trades_total for s in self.population]
        pnls = [s.pnl_total for s in self.population]
        
        return {
            'population_size': len(self.population),
            'evolution_count': self.evolution_count,
            'diversity': self._diversity_score(),
            'avg_fitness': sum(fitnesses) / len(fitnesses) if fitnesses else 0.0,
            'max_fitness': max(fitnesses) if fitnesses else 0.0,
            'min_fitness': min(fitnesses) if fitnesses else 0.0,
            'total_trades': sum(trades),
            'total_pnl': sum(pnls),
            'global_best_fitness': self.global_best.fitness if self.global_best else 0.0,
        }

    def __repr__(self):
        stats = self.get_stats()
        return (
            f"Pool(size={stats['population_size']}, "
            f"evolution={stats['evolution_count']}, "
            f"diversity={stats['diversity']}, "
            f"avg_fitness={stats['avg_fitness']:.3f})"
        )
