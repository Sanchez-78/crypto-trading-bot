"""Strategy selection from available policies based on market regime."""

from typing import Optional, Tuple, List
from .candidate import StrategyCandidate, StrategyRegistry
from .baseline_policies import (
    MomentumPolicy, MeanReversionPolicy, VolatilityBreakPolicy
)
from .feature_engine import MarketFeatures


class PolicySelector:
    """Selects and evaluates strategies based on features."""

    def __init__(self, registry: Optional[StrategyRegistry] = None):
        self.registry = registry or StrategyRegistry()
        self.policies = {
            "baseline_momentum_01": MomentumPolicy(),
            "baseline_mean_reversion_01": MeanReversionPolicy(),
            "baseline_volatility_break_01": VolatilityBreakPolicy(),
        }

        # Register all baseline policies
        for policy in self.policies.values():
            self.registry.register(policy.candidate)

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

        Args:
            features: Market features

        Returns:
            (strategy_id, signal_reason, should_enter)
        """
        if not features.regime:
            return None, "no_regime", False

        applicable = self.select_for_regime(features.regime)

        for candidate in applicable:
            policy = self.policies.get(candidate.strategy_id)
            if not policy:
                continue

            should_enter, reason = policy.should_enter(features)
            if should_enter:
                return candidate.strategy_id, reason, True

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
