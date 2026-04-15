"""
Strategy Learner v2 — Fixes: no routing intelligence → same strategy regardless of regime/performance.

Multi-armed bandit with context (regime × symbol_tier × session).
Uses UCB1 to balance exploration/exploitation.
"""

import numpy as np
import random
from collections import defaultdict, deque
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class StrategyLearner:
    """Learn which strategies work best in different market contexts."""

    EPSILON = 0.10  # Random exploration rate
    MIN_PULLS = 5  # Min trials before using UCB1
    TIERS = {
        "BTC": ["BTC"],
        "ETH": ["ETH"],
        "major": ["BNB", "SOL", "ADA", "DOT", "XRP"],
        "other": [],
    }
    SESSIONS = {
        "asia": (0, 8),
        "europe": (8, 16),
        "us": (13, 22),
    }

    def __init__(self, strategies: List[str]):
        self.strategies = strategies
        # Track returns per (context, strategy)
        self._arms: Dict = defaultdict(lambda: defaultdict(lambda: deque(maxlen=50)))
        # Pull count per (context, strategy)
        self._n: Dict = defaultdict(lambda: defaultdict(int))

    def __call__(self, o):
        """Called when outcome arrives."""
        ctx = self._ctx(o.regime, o.symbol, o.timestamp.hour)
        strat = o.features.get("strategy_used", "unknown")
        if strat in self.strategies:
            self._arms[ctx][strat].append(o.net_pnl_pct)
            self._n[ctx][strat] += 1

    def select(self, regime: str, symbol: str, hour: int) -> str:
        """Select strategy using epsilon-greedy UCB1."""
        ctx = self._ctx(regime, symbol, hour)

        # Explore randomly sometimes
        if random.random() < self.EPSILON:
            return random.choice(self.strategies)

        # Exploit: use UCB1 to pick best strategy
        total = sum(self._n[ctx].values()) + 1
        scores = {}

        for s in self.strategies:
            n = self._n[ctx][s]
            if n < self.MIN_PULLS:
                # Not enough data yet → use infinite score to explore
                scores[s] = float("inf")
            else:
                # UCB1 = mean + sqrt(2*ln(N)/n)
                mean = np.mean(self._arms[ctx][s])
                confidence = np.sqrt(2 * np.log(total) / n)
                scores[s] = mean + confidence

        return max(scores, key=scores.get)

    def _ctx(self, regime: str, symbol: str, hour: int) -> str:
        """Generate context key from regime, symbol tier, session."""
        tier = next((t for t, syms in self.TIERS.items() if symbol in syms), "other")
        sess = next(
            (s for s, (lo, hi) in self.SESSIONS.items() if lo <= hour < hi), "other"
        )
        return f"{regime}_{tier}_{sess}"
