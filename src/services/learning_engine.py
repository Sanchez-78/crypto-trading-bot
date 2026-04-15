"""
Learning Engine v2 — Observer hub for outcome-driven learners.

Broken before: Signal→Filter→Trade→Outcome→(void)
Fixed: Signal→Filter→Trade→Outcome→LearningEngine→[4 learners update in parallel]

One-liner fix: call learning.update(outcome) after every trade close.
All learners automatically get notified and update their internal models.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List
import logging

logger = logging.getLogger(__name__)


@dataclass
class TradeOutcome:
    """Complete outcome record from closed trade."""
    trade_id: str
    symbol: str
    direction: str  # "LONG" or "SHORT"
    regime: str  # Market regime at entry (BULL_TREND, BEAR_TREND, etc.)
    won: bool  # Profitable or not
    net_pnl_pct: float  # P&L as % of position
    duration_s: int  # Seconds in trade
    features: dict = field(default_factory=dict)  # Signal features at entry
    filters_passed: list = field(default_factory=list)  # Which filters approved this
    timing_frac: float = 0.0  # Where in candle did signal arrive (0-1)
    conviction: float = 0.0  # Model confidence in signal
    mtf_score: float = 0.0  # Multi-timeframe alignment score
    obi: float = 0.0  # Order book imbalance at entry
    atr_regime: str = "normal"  # Volatility regime
    timestamp: datetime = field(default_factory=datetime.now)


class LearningEngine:
    """
    Central hub: register learners, broadcast outcomes to all.
    
    Usage:
        engine = LearningEngine()
        engine.register("features", feature_learner)
        engine.register("filters", filter_learner)
        ...
        engine.update(outcome)  # All learners notified
    """

    def __init__(self):
        self._learners: Dict[str, Callable] = {}
        self._log: List[TradeOutcome] = []
        self._s = {"n": 0, "wins": 0, "pnl": 0.0}

    def register(self, name: str, fn: Callable):
        """Register a learner (any callable that takes TradeOutcome)."""
        self._learners[name] = fn

    def update(self, o: TradeOutcome):
        """Broadcast outcome to all registered learners."""
        self._log.append(o)
        self._s["n"] += 1
        if o.won:
            self._s["wins"] += 1
        self._s["pnl"] += o.net_pnl_pct

        # Notify all learners
        for name, fn in self._learners.items():
            try:
                fn(o)
            except Exception as e:
                logger.error(f"Learner {name} crashed on outcome: {e}")

    def global_wr(self) -> float:
        """Global win rate across all trades."""
        n = self._s["n"]
        return self._s["wins"] / n if n > 0 else 0.0

    def outcomes_since(self, n: int) -> List[TradeOutcome]:
        """Get last n outcomes (for debugging)."""
        return self._log[-n:]

    def summary(self) -> dict:
        """High-level status."""
        n = self._s["n"]
        return {
            "n": n,
            "wr": f"{self.global_wr():.1%}",
            "pnl": f"{self._s['pnl']:+.2f}%",
            "learners": list(self._learners.keys()),
        }
