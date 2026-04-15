"""
Learning System v2 — Assembly point for all 4 learners.

Single entry point. One call (ls.update(outcome)) updates all learners in parallel.
Provides unified query interface (feature weights, filter adjustments, strategy selection, position sizing).

Usage:
    ls = LearningSystem()
    ls.update(outcome)  # After every trade close
    
    # Query learned models:
    w = ls.feature_weight("ofi")
    adj = ls.filter_adj("TIMING")
    strat = ls.select_strategy(regime, symbol, hour)
    size = ls.pos_size(conviction)
    score = ls.score()
    diag = ls.diagnose()
"""

import numpy as np
from learning_engine import LearningEngine, TradeOutcome
from feature_learner import FeatureLearner
from filter_learner import FilterLearner
from strategy_learner import StrategyLearner
from conviction_learner import ConvictionCalibrator
import logging

logger = logging.getLogger(__name__)

STRATEGIES = [
    "SupertrendMACD",
    "EMABreakout",
    "BBRSIReversion",
    "ZScoreReversion",
    "FundingArb",
    "StatArb",
]


class LearningSystem:
    """
    Unified learning hub. Manages all 4 outcome-driven learners.
    """

    def __init__(self):
        # Central engine + 4 learners
        self.engine = LearningEngine()
        self.features = FeatureLearner()
        self.filters = FilterLearner()
        self.strategies = StrategyLearner(STRATEGIES)
        self.conviction = ConvictionCalibrator()

        # Register all learners
        for name, obj in [
            ("features", self.features),
            ("filters", self.filters),
            ("strategies", self.strategies),
            ("conviction", self.conviction),
        ]:
            self.engine.register(name, obj)

    def update(self, o: TradeOutcome):
        """
        Broadcast outcome to all learners.
        Call this ONCE after every trade closes.
        """
        self.engine.update(o)

    # ────────────────────────────────────────────────────────────────────────
    # QUERY INTERFACE: use learned models in decisions
    # ────────────────────────────────────────────────────────────────────────

    def feature_weight(self, k: str) -> float:
        """Get learned weight multiplier for feature k."""
        return self.features.weight(k)

    def filter_adj(self, f: str) -> float:
        """Get learned threshold adjustment for filter f."""
        return self.filters.adjustment(f)

    def select_strategy(self, regime: str, symbol: str, hour: int) -> str:
        """Select strategy using learned UCB1 policy."""
        return self.strategies.select(regime, symbol, hour)

    def pos_size(self, conviction: float) -> float:
        """Get Kelly-sized position based on calibrated win rate."""
        return self.conviction.kelly_size(conviction)

    # ────────────────────────────────────────────────────────────────────────
    # SCORING & DIAGNOSTICS
    # ────────────────────────────────────────────────────────────────────────

    def score(self) -> float:
        """
        Combined learning score (0-100).
        
        Factors:
        - Win rate (40%)
        - Feature quality (35%)
        - Calibration (25%)
        """
        n = self.engine._s["n"]
        wr = self.engine.global_wr()

        if n < 5:
            return 0.0

        # Win rate component (40%)
        wr_s = np.clip((wr - 0.45) / 0.20, 0, 1)

        # Feature quality component (35%)
        fr = self.features.report()
        feat_s = sum(1 for f in fr.values() if f["status"] in ("OK", "BOOST")) / max(
            len(fr), 1
        )

        # Calibration component (25%)
        cal_s = max(0, 1 - self.conviction.ece() * 5)

        score = min((wr_s * 0.40 + feat_s * 0.35 + cal_s * 0.25) * 100, n * 1.5)
        return round(score, 1)

    def diagnose(self) -> dict:
        """Comprehensive diagnostic report."""
        n = self.engine._s["n"]
        phase = (
            "BOOT" if n < 20 else "CAL" if n < 100 else "PROD"
        )

        return {
            "n": n,
            "wr": f"{self.engine.global_wr():.1%}",
            "score": self.score(),
            "phase": phase,
            "active_features": self.features.active(),
            "dropped_features": list(self.features._dropped),
            "filter_adjustments": {
                k: f"{v:+.2f}" for k, v in self.filters._adj.items() if abs(v) > 0.01
            },
            "ece": self.conviction.ece(),
        }
