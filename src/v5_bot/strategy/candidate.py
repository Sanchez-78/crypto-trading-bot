"""Strategy candidate definition and registry."""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum


class StrategyType(Enum):
    """Strategy classification."""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    VOLATILITY_BREAK = "volatility_break"


class StrategyRegime(Enum):
    """Market regime classification."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


@dataclass
class StrategyCandidate:
    """One strategy candidate with configuration."""
    strategy_id: str
    name: str
    strategy_type: StrategyType
    enabled: bool = True

    # Parameters (specific to strategy type)
    params: Dict[str, Any] = field(default_factory=dict)

    # Regime applicability
    applicable_regimes: List[StrategyRegime] = field(default_factory=list)

    # Performance tracking
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0  # Break-even or minimal loss

    # Historical expectancy (cost-adjusted expected value in basis points)
    historical_net_expectancy_bps: float = 0.0
    historical_profit_factor: float = 1.0
    historical_max_drawdown_pct: float = 0.0

    # Learning eligibility
    min_eligible_closes: int = 0
    eligible_closes_current: int = 0

    def get_param(self, key: str, default: Any = None) -> Any:
        """Get strategy parameter safely."""
        return self.params.get(key, default)

    def set_param(self, key: str, value: Any) -> None:
        """Set strategy parameter."""
        self.params[key] = value

    def is_applicable_to_regime(self, regime: StrategyRegime) -> bool:
        """Check if this strategy applies to given regime."""
        return regime in self.applicable_regimes

    def win_rate(self) -> Optional[float]:
        """Win rate as decimal (0-1)."""
        total = self.wins + self.losses + self.flats
        if total == 0:
            return None
        return self.wins / total

    def to_dict(self) -> Dict[str, Any]:
        """Export as dict."""
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "strategy_type": self.strategy_type.value,
            "enabled": self.enabled,
            "params": self.params,
            "applicable_regimes": [r.value for r in self.applicable_regimes],
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "flats": self.flats,
            "historical_net_expectancy_bps": self.historical_net_expectancy_bps,
            "historical_profit_factor": self.historical_profit_factor,
            "win_rate": self.win_rate(),
        }


class StrategyRegistry:
    """Registry of available strategy candidates."""

    def __init__(self):
        self.strategies: Dict[str, StrategyCandidate] = {}

    def register(self, candidate: StrategyCandidate) -> None:
        """Register a strategy candidate."""
        self.strategies[candidate.strategy_id] = candidate

    def get(self, strategy_id: str) -> Optional[StrategyCandidate]:
        """Get strategy by ID."""
        return self.strategies.get(strategy_id)

    def get_enabled(self) -> List[StrategyCandidate]:
        """Get all enabled strategies."""
        return [s for s in self.strategies.values() if s.enabled]

    def get_for_regime(self, regime: StrategyRegime) -> List[StrategyCandidate]:
        """Get all strategies applicable to a regime."""
        return [s for s in self.strategies.values()
                if s.enabled and s.is_applicable_to_regime(regime)]

    def all(self) -> List[StrategyCandidate]:
        """Get all registered strategies."""
        return list(self.strategies.values())

    def summary(self) -> Dict[str, Any]:
        """Summary of registry."""
        enabled = self.get_enabled()
        return {
            "total_strategies": len(self.strategies),
            "enabled_strategies": len(enabled),
            "strategies": {s.strategy_id: s.to_dict() for s in enabled},
        }
