"""
PATCH: Strategy Object — Individual trading strategy with fitness tracking.

Each strategy has:
- DNA (parameters)
- Fitness metrics (EV, stability, win rate)
- Trade history (for learning)
- Generation info (age, parent lineage)

Fitness = (Expected Value × 0.6) + (Stability × 0.3) + (Trade Count × 0.1)
"""

import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class Strategy:
    """Individual trading strategy in the genetic pool."""
    
    dna: object  # StrategyDNA object
    generation: int = 0
    trades_total: int = 0
    trades_wins: int = 0
    pnl_total: float = 0.0
    max_drawdown: float = 0.0
    fitness: float = 0.0
    
    # History for diagnostics
    trade_history: List[float] = field(default_factory=list)
    active_since: float = field(default_factory=lambda: __import__('time').time())
    last_updated: float = field(default_factory=lambda: __import__('time').time())
    
    def record_trade(self, trade):
        """
        Record a closed trade and update fitness.
        
        Args:
            trade: Trade object with pnl, net_pnl_pct, result, etc.
        """
        self.trades_total += 1
        pnl = trade.net_pnl_pct / 100 if hasattr(trade, 'net_pnl_pct') else (trade.pnl if hasattr(trade, 'pnl') else 0.0)
        
        self.pnl_total += pnl
        self.trade_history.append(pnl)
        
        # Track wins
        if pnl > 0.0:
            self.trades_wins += 1
        
        # Update max drawdown
        cumsum = sum(self.trade_history)
        peak = max(self.trade_history) if self.trade_history else 0
        dd = abs(min(0, cumsum - peak)) if peak > 0 else 0
        self.max_drawdown = max(self.max_drawdown, dd)
        
        # Recalculate fitness
        self._update_fitness()
        
        self.last_updated = __import__('time').time()

    def _update_fitness(self):
        """
        Calculate fitness score: survival metric for genetic algorithm.
        
        Fitness components:
        - Expected Value (EV): avg PnL per trade × 0.60
        - Stability: inverse of max drawdown × 0.30
        - Trade Count: more trades = more confidence × 0.10
        """
        if self.trades_total == 0:
            self.fitness = 0.0
            return
        
        # Component 1: Expected Value (EV)
        ev = self.pnl_total / self.trades_total if self.trades_total > 0 else 0.0
        ev_score = min(ev, 0.1) / 0.1  # Normalize to [0, 1], cap at 10% EV
        
        # Component 2: Win Rate
        winrate = self.trades_wins / self.trades_total
        wr_score = winrate  # [0, 1]
        
        # Component 3: Stability (inverse of drawdown)
        dd_score = 1.0 / (1.0 + self.max_drawdown) if self.max_drawdown >= 0 else 1.0
        
        # Component 4: Trade Count (more samples = higher confidence)
        tc_score = min(self.trades_total / 100, 1.0)  # Cap at 100 trades
        
        # Weighted combination
        self.fitness = (
            ev_score * 0.35 +        # EV (primary)
            wr_score * 0.35 +        # Win rate (primary)
            dd_score * 0.20 +        # Stability (secondary)
            tc_score * 0.10          # Sample size (tertiary)
        )

    def to_dict(self):
        """Serialize to dict for logging."""
        return {
            'dna': str(self.dna),
            'generation': self.generation,
            'trades_total': self.trades_total,
            'trades_wins': self.trades_wins,
            'winrate': self.trades_wins / max(self.trades_total, 1),
            'pnl_total': round(self.pnl_total, 4),
            'max_drawdown': round(self.max_drawdown, 4),
            'fitness': round(self.fitness, 4),
        }

    def __repr__(self):
        wr = 100 * self.trades_wins / max(self.trades_total, 1)
        return f"Strat(gen={self.generation} trades={self.trades_total} wr={wr:.0f}% pnl={self.pnl_total:+.2%} fit={self.fitness:.3f})"
