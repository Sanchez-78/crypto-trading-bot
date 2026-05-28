"""Feature extraction from market data for strategy decision-making."""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime
import statistics
from ..util.datetime_utils import utc_now


@dataclass
class MarketFeatures:
    """Extracted market features for strategy evaluation."""
    symbol: str
    current_price: float
    bid: float
    ask: float
    spread_bps: float

    # Trend features
    sma_5: Optional[float] = None  # Simple moving average (5 closes)
    sma_20: Optional[float] = None  # Simple moving average (20 closes)
    trend_direction: Optional[str] = None  # "up", "down", "ranging"

    # Volatility features
    atr_14: Optional[float] = None  # Average true range
    volatility_pct: Optional[float] = None  # Rolling 20-close volatility

    # Momentum features
    rsi_14: Optional[float] = None  # Relative strength index
    roc_12: Optional[float] = None  # Rate of change

    # Volume features
    volume_sma: Optional[float] = None
    volume_current: Optional[float] = None
    volume_ratio: Optional[float] = None

    # Regime classification
    regime: Optional[str] = None  # "trending_up", "trending_down", "ranging", etc.

    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Export features as dict."""
        return {
            "symbol": self.symbol,
            "current_price": self.current_price,
            "bid": self.bid,
            "ask": self.ask,
            "spread_bps": self.spread_bps,
            "sma_5": self.sma_5,
            "sma_20": self.sma_20,
            "trend_direction": self.trend_direction,
            "atr_14": self.atr_14,
            "volatility_pct": self.volatility_pct,
            "rsi_14": self.rsi_14,
            "regime": self.regime,
            "timestamp": self.timestamp,
        }


class FeatureEngine:
    """Extract features from price/volume data."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.closes: List[float] = []
        self.highs: List[float] = []
        self.lows: List[float] = []
        self.volumes: List[float] = []

    def add_candle(self, close: float, high: float, low: float, volume: float = 0.0) -> None:
        """Add a candle (OHLC bar) to history."""
        self.closes.append(close)
        self.highs.append(high)
        self.lows.append(low)
        if volume > 0:
            self.volumes.append(volume)

    def calc_sma(self, period: int) -> Optional[float]:
        """Calculate simple moving average."""
        if len(self.closes) < period:
            return None
        return statistics.mean(self.closes[-period:])

    def calc_volatility(self, period: int = 20) -> Optional[float]:
        """Calculate historical volatility (standard deviation of returns)."""
        if len(self.closes) < period:
            return None

        recent = self.closes[-period:]
        returns = []
        for i in range(1, len(recent)):
            ret = (recent[i] - recent[i-1]) / recent[i-1]
            returns.append(ret)

        if not returns:
            return None

        std_dev = statistics.stdev(returns)
        return std_dev * 100  # as percentage

    def calc_atr(self, period: int = 14) -> Optional[float]:
        """Calculate average true range."""
        if len(self.closes) < period:
            return None

        true_ranges = []
        for i in range(len(self.closes)):
            if i == 0:
                tr = self.highs[i] - self.lows[i]
            else:
                tr = max(
                    self.highs[i] - self.lows[i],
                    abs(self.highs[i] - self.closes[i-1]),
                    abs(self.lows[i] - self.closes[i-1]),
                )
            true_ranges.append(tr)

        return statistics.mean(true_ranges[-period:])

    def calc_rsi(self, period: int = 14) -> Optional[float]:
        """Calculate relative strength index."""
        if len(self.closes) < period + 1:
            return None

        gains = []
        losses = []
        start_idx = max(1, len(self.closes) - period)
        for i in range(start_idx, len(self.closes)):
            change = self.closes[i] - self.closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = statistics.mean(gains)
        avg_loss = statistics.mean(losses)

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def classify_regime(self) -> Optional[str]:
        """Classify current market regime."""
        sma_5 = self.calc_sma(5)
        sma_20 = self.calc_sma(20)

        if not sma_5 or not sma_20:
            return None

        volatility = self.calc_volatility(20)
        current = self.closes[-1] if self.closes else None

        if not current:
            return None

        # Trend classification
        if sma_5 > sma_20:
            trend = "trending_up"
        elif sma_5 < sma_20:
            trend = "trending_down"
        else:
            trend = "ranging"

        # Volatility classification
        if volatility and volatility > 3.0:
            vol_class = "_high_vol"
        else:
            vol_class = "_normal_vol"

        return trend + vol_class

    def extract_features(self, current_price: float, bid: float, ask: float,
                         spread_bps: Optional[float] = None) -> MarketFeatures:
        """Extract all features for strategy evaluation."""
        sma_5 = self.calc_sma(5)
        sma_20 = self.calc_sma(20)

        # Trend direction
        trend_dir = None
        if sma_5 and sma_20:
            trend_dir = "up" if sma_5 > sma_20 else "down"

        regime = self.classify_regime()

        if spread_bps is None:
            if ask > 0:
                spread_bps = (ask - bid) / ((bid + ask) / 2) * 10000
            else:
                spread_bps = 0.0

        return MarketFeatures(
            symbol=self.symbol,
            current_price=current_price,
            bid=bid,
            ask=ask,
            spread_bps=spread_bps,
            sma_5=sma_5,
            sma_20=sma_20,
            trend_direction=trend_dir,
            atr_14=self.calc_atr(14),
            volatility_pct=self.calc_volatility(20),
            rsi_14=self.calc_rsi(14),
            regime=regime,
            timestamp=utc_now().timestamp(),
        )
