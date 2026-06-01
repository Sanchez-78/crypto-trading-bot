"""Strategy selection from available policies based on market regime."""

import logging
from typing import Optional, Tuple, List
from .candidate import StrategyCandidate, StrategyRegistry
from .baseline_policies import (
    MomentumPolicy, MeanReversionPolicy, VolatilityBreakPolicy,
    BootstrapSpreadPolicy
)
from .feature_engine import MarketFeatures

log = logging.getLogger(__name__)


class PolicySelector:
    """Selects and evaluates strategies based on features and learning feedback."""

    def __init__(self, registry: Optional[StrategyRegistry] = None, policy_state_tracker=None):
        self.registry = registry or StrategyRegistry()
        self.policy_state_tracker = policy_state_tracker  # Phase 4A: Optional learning feedback
        self.policies = {
            "baseline_momentum_01": MomentumPolicy(),
            "baseline_mean_reversion_01": MeanReversionPolicy(),
            "baseline_volatility_break_01": VolatilityBreakPolicy(),
            "bootstrap_spread_01": BootstrapSpreadPolicy(),
        }

        # Register all baseline policies
        for policy in self.policies.values():
            self.registry.register(policy.candidate)

    def set_policy_state_tracker(self, tracker) -> None:
        """Wire PolicyStateTracker for learning feedback (Phase 4A)."""
        self.policy_state_tracker = tracker

    def select_for_regime(self, regime: str) -> List[StrategyCandidate]:
        """
        Select strategies applicable to current regime.

        Args:
            regime: Market regime string (e.g., "trending_up_high_vol")

        Returns:
            List of applicable strategy candidates
        """
        # Parse regime string to StrategyRegime enum
        if "trending_up" in regime:
            from .candidate import StrategyRegime
            applicable = self.registry.get_for_regime(StrategyRegime.TRENDING_UP)
        elif "trending_down" in regime:
            from .candidate import StrategyRegime
            applicable = self.registry.get_for_regime(StrategyRegime.TRENDING_DOWN)
        elif "ranging" in regime:
            from .candidate import StrategyRegime
            applicable = self.registry.get_for_regime(StrategyRegime.RANGING)
        else:
            applicable = self.registry.get_enabled()

        return applicable

    def evaluate_signal(self, features: MarketFeatures) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Evaluate all applicable strategies and return best signal.
        Phase 4A: Apply learning feedback as soft ranking (not hard blocker).

        Args:
            features: Market features (must include symbol, regime, side)

        Returns:
            (strategy_id, signal_reason, should_enter)
        """
        if not features.regime:
            return None, "no_regime", False

        applicable = self.select_for_regime(features.regime)

        # Phase 4A: Apply learning feedback as soft ranking
        best_candidate = None
        best_score = -1.0
        best_reason = None

        for candidate in applicable:
            policy = self.policies.get(candidate.strategy_id)
            if not policy:
                continue

            should_enter, reason = policy.should_enter(features)
            if not should_enter:
                continue

            # Phase 4A: Apply learning weight as soft ranking
            learning_weight = 1.0
            segment_key = None
            segment_stats = None

            if self.policy_state_tracker and hasattr(features, "symbol") and hasattr(features, "side"):
                # Build segment key from available features
                side = getattr(features, "side", "LONG")
                symbol = getattr(features, "symbol", "")
                regime = features.regime or "unknown"
                segment_key = f"{symbol}:{regime}:{side}:{candidate.strategy_id}"
                learning_weight = self.policy_state_tracker.get_segment_learning_weight(segment_key)
                segment_stats = self.policy_state_tracker.get_segment(segment_key)

            # Score = base signal (1.0) * learning weight
            score = 1.0 * learning_weight

            # Log decision provenance
            log_msg = (
                f"[POLICY_SELECTOR] symbol={getattr(features, 'symbol', 'N/A')} "
                f"regime={features.regime} policy={candidate.strategy_id} "
                f"should_enter={should_enter} reason={reason}"
            )
            if segment_key and segment_stats:
                log_msg += (
                    f" segment_key={segment_key} n={segment_stats.eligible_closes} "
                    f"pf={segment_stats.profit_factor:.2f} "
                    f"expectancy={segment_stats.net_expectancy_bps:.2f}bps "
                    f"win_rate={segment_stats.win_rate() or 0:.2f} "
                    f"learning_weight={learning_weight:.2f} score={score:.2f}"
                )
            log.debug(log_msg)

            # Track best candidate by score
            if score > best_score:
                best_score = score
                best_candidate = candidate
                best_reason = reason

        if best_candidate:
            return best_candidate.strategy_id, best_reason, True

        return None, "no_signal", False

    def get_entry_params(self, strategy_id: str) -> Optional[dict]:
        """Get entry parameters for a strategy."""
        policy = self.policies.get(strategy_id)
        if not policy:
            return None

        return {
            "side": policy.get_side(),
            "target_pct": policy.get_target_pct(),
            "stop_loss_pct": policy.get_stop_loss_pct(),
        }
