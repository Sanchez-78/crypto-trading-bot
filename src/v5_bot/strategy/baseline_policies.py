"""Three baseline trading strategies."""

from typing import Tuple, Optional
from .candidate import StrategyCandidate, StrategyType, StrategyRegime
from .feature_engine import MarketFeatures


class BaselinePolicy:
    """Base class for baseline strategies."""

    def __init__(self, candidate: StrategyCandidate):
        self.candidate = candidate

    def should_enter(self, features: MarketFeatures) -> Tuple[bool, Optional[str]]:
        """
        Determine if entry signal should be generated.

        Args:
            features: Extracted market features

        Returns:
            (should_enter: bool, reason: Optional[str])
        """
        raise NotImplementedError

    def get_side(self) -> str:
        """Return trade side: BUY or SELL."""
        raise NotImplementedError

    def get_target_pct(self) -> float:
        """Return target profit as percentage of entry."""
        raise NotImplementedError

    def get_stop_loss_pct(self) -> float:
        """Return stop loss as percentage of entry."""
        raise NotImplementedError


class MomentumPolicy(BaselinePolicy):
    """
    Momentum strategy: Enter on trend continuation when SMA_5 > SMA_20 and positive RSI.
    """

    def __init__(self):
        candidate = StrategyCandidate(
            strategy_id="baseline_momentum_01",
            name="Baseline Momentum",
            strategy_type=StrategyType.MOMENTUM,
            params={
                "sma_fast": 5,
                "sma_slow": 20,
                "rsi_threshold_high": 70,
                "rsi_threshold_low": 30,
                "target_pct": 1.5,
                "stop_loss_pct": 1.0,
            },
            applicable_regimes=[
                StrategyRegime.TRENDING_UP,
                StrategyRegime.TRENDING_DOWN,
            ],
        )
        super().__init__(candidate)

    def should_enter(self, features: MarketFeatures) -> Tuple[bool, Optional[str]]:
        """Enter on trend following signal."""
        if not features.sma_5 or not features.sma_20 or features.rsi_14 is None:
            return False, "insufficient_data"

        # Uptrend: SMA_5 > SMA_20, RSI > 30 and < 70 (not overbought)
        if features.sma_5 > features.sma_20:
            if 30 < features.rsi_14 < 70:
                return True, "uptrend_momentum"
            else:
                return False, "rsi_extreme"

        # Downtrend: SMA_5 < SMA_20, RSI < 70 and > 30 (not oversold)
        if features.sma_5 < features.sma_20:
            if 30 < features.rsi_14 < 70:
                return True, "downtrend_momentum"
            else:
                return False, "rsi_extreme"

        return False, "no_trend"

    def get_side(self) -> str:
        """Always long for simplicity."""
        return "BUY"

    def get_target_pct(self) -> float:
        return self.candidate.get_param("target_pct", 1.5)

    def get_stop_loss_pct(self) -> float:
        return self.candidate.get_param("stop_loss_pct", 1.0)


class MeanReversionPolicy(BaselinePolicy):
    """
    Mean reversion strategy: Enter when price is >2 ATR away from SMA_20 (oversold/overbought).
    """

    def __init__(self):
        candidate = StrategyCandidate(
            strategy_id="baseline_mean_reversion_01",
            name="Baseline Mean Reversion",
            strategy_type=StrategyType.MEAN_REVERSION,
            params={
                "sma_period": 20,
                "atr_multiple": 2.0,
                "target_pct": 0.8,
                "stop_loss_pct": 1.2,
            },
            applicable_regimes=[
                StrategyRegime.RANGING,
                StrategyRegime.LOW_VOLATILITY,
            ],
        )
        super().__init__(candidate)

    def should_enter(self, features: MarketFeatures) -> Tuple[bool, Optional[str]]:
        """Enter on oversold/overbought deviation from moving average."""
        if not features.sma_20 or not features.atr_14 or features.current_price is None:
            return False, "insufficient_data"

        atr_mult = self.candidate.get_param("atr_multiple", 2.0)
        deviation = abs(features.current_price - features.sma_20)
        threshold = features.atr_14 * atr_mult

        if deviation > threshold:
            if features.current_price < features.sma_20:
                return True, "oversold_deviation"
            else:
                return True, "overbought_deviation"

        return False, "within_range"

    def get_side(self) -> str:
        return "BUY"

    def get_target_pct(self) -> float:
        return self.candidate.get_param("target_pct", 0.8)

    def get_stop_loss_pct(self) -> float:
        return self.candidate.get_param("stop_loss_pct", 1.2)


class VolatilityBreakPolicy(BaselinePolicy):
    """
    Volatility breakout strategy: Enter when price breaks beyond Bollinger bands
    (SMA_20 +/- 2*StdDev) with elevated volatility.
    """

    def __init__(self):
        candidate = StrategyCandidate(
            strategy_id="baseline_volatility_break_01",
            name="Baseline Volatility Breakout",
            strategy_type=StrategyType.VOLATILITY_BREAK,
            params={
                "sma_period": 20,
                "std_dev_mult": 2.0,
                "min_volatility_pct": 2.0,
                "target_pct": 2.0,
                "stop_loss_pct": 1.5,
            },
            applicable_regimes=[
                StrategyRegime.HIGH_VOLATILITY,
            ],
        )
        super().__init__(candidate)

    def should_enter(self, features: MarketFeatures) -> Tuple[bool, Optional[str]]:
        """Enter on volatility breakout."""
        if not features.sma_20 or features.volatility_pct is None or features.current_price is None:
            return False, "insufficient_data"

        min_vol = self.candidate.get_param("min_volatility_pct", 2.0)
        if features.volatility_pct < min_vol:
            return False, "low_volatility"

        # Simple Bollinger band approximation
        # Upper band = SMA + 2 * StdDev (estimated from volatility)
        # Lower band = SMA - 2 * StdDev
        estimated_std = (features.sma_20 * features.volatility_pct) / 100
        upper_band = features.sma_20 + (2 * estimated_std)
        lower_band = features.sma_20 - (2 * estimated_std)

        if features.current_price > upper_band:
            return True, "upper_breakout"
        elif features.current_price < lower_band:
            return True, "lower_breakout"

        return False, "within_bands"

    def get_side(self) -> str:
        return "BUY"

    def get_target_pct(self) -> float:
        return self.candidate.get_param("target_pct", 2.0)

    def get_stop_loss_pct(self) -> float:
        return self.candidate.get_param("stop_loss_pct", 1.5)
