"""Segment/policy performance tracking for learning."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from ..execution.accounting import TradeAccounting


@dataclass
class SegmentStats:
    """Performance statistics for one policy segment."""
    segment_id: str
    strategy_id: str
    regime: str  # Market regime this segment applies to

    # Sample tracking
    total_closes: int = 0
    eligible_closes: int = 0

    # Trade outcomes
    wins: int = 0
    losses: int = 0
    flats: int = 0

    # PnL tracking
    total_gross_pnl_usd: float = 0.0
    total_net_pnl_usd: float = 0.0
    total_costs_usd: float = 0.0

    # Expectancy (net PnL / entry notional, in basis points)
    net_expectancy_bps: float = 0.0
    gross_expectancy_bps: float = 0.0

    # Profit factor
    profit_factor: float = 1.0

    # Rolling window for recent performance
    rolling_20_closes: List[float] = field(default_factory=list)  # Recent close PnL pcts
    rolling_50_closes: List[float] = field(default_factory=list)
    rolling_100_closes: List[float] = field(default_factory=list)

    def add_trade(self, trade: TradeAccounting) -> None:
        """Add closed trade to segment statistics."""
        self.total_closes += 1

        # Classify outcome
        if trade.net_pnl_usd > 0:
            self.wins += 1
        elif trade.net_pnl_usd < 0:
            self.losses += 1
        else:
            self.flats += 1

        # Accumulate PnL
        self.total_gross_pnl_usd += trade.gross_pnl_usd
        self.total_net_pnl_usd += trade.net_pnl_usd
        self.total_costs_usd += trade.total_costs_usd

        # Add to rolling windows
        if trade.entry_fill:
            notional = trade.entry_fill.notional_usd
            pnl_pct = (trade.net_pnl_usd / notional * 100) if notional > 0 else 0
            self.rolling_20_closes.append(pnl_pct)
            self.rolling_50_closes.append(pnl_pct)
            self.rolling_100_closes.append(pnl_pct)

            # Keep rolling windows at max size
            if len(self.rolling_20_closes) > 20:
                self.rolling_20_closes.pop(0)
            if len(self.rolling_50_closes) > 50:
                self.rolling_50_closes.pop(0)
            if len(self.rolling_100_closes) > 100:
                self.rolling_100_closes.pop(0)

    def recalc_stats(self) -> None:
        """Recalculate derived statistics."""
        # Expectancy in basis points
        if self.total_closes > 0:
            total_notional = sum(t.entry_fill.notional_usd for t in [] if t.entry_fill)
            if total_notional > 0:
                self.net_expectancy_bps = (self.total_net_pnl_usd / total_notional) * 10000
                self.gross_expectancy_bps = (self.total_gross_pnl_usd / total_notional) * 10000

            # Profit factor: wins / losses
            if self.losses > 0:
                self.profit_factor = (self.wins + self.flats) / self.losses
            elif self.wins > 0:
                self.profit_factor = 2.0  # At least 2.0 if no losses

    def win_rate(self) -> Optional[float]:
        """Calculate win rate."""
        total = self.wins + self.losses + self.flats
        if total == 0:
            return None
        return self.wins / total

    def to_dict(self) -> Dict:
        """Export stats as dict."""
        return {
            "segment_id": self.segment_id,
            "strategy_id": self.strategy_id,
            "regime": self.regime,
            "total_closes": self.total_closes,
            "eligible_closes": self.eligible_closes,
            "wins": self.wins,
            "losses": self.losses,
            "flats": self.flats,
            "win_rate": self.win_rate(),
            "total_net_pnl_usd": self.total_net_pnl_usd,
            "net_expectancy_bps": self.net_expectancy_bps,
            "profit_factor": self.profit_factor,
        }


class PolicyStateTracker:
    """Tracks learning state across all segments."""

    def __init__(self):
        self.segments: Dict[str, SegmentStats] = {}

    def get_or_create_segment(self, segment_id: str, strategy_id: str, regime: str) -> SegmentStats:
        """Get or create segment stats."""
        if segment_id not in self.segments:
            self.segments[segment_id] = SegmentStats(
                segment_id=segment_id,
                strategy_id=strategy_id,
                regime=regime,
            )
        return self.segments[segment_id]

    def add_eligible_trade(self, trade: TradeAccounting, segment_id: str,
                          strategy_id: str, regime: str) -> None:
        """Add eligible trade to segment."""
        segment = self.get_or_create_segment(segment_id, strategy_id, regime)
        segment.add_trade(trade)
        segment.eligible_closes += 1
        segment.recalc_stats()

    def get_segment(self, segment_id: str) -> Optional[SegmentStats]:
        """Get segment stats."""
        return self.segments.get(segment_id)

    def get_segments_for_strategy(self, strategy_id: str) -> List[SegmentStats]:
        """Get all segments for a strategy."""
        return [s for s in self.segments.values() if s.strategy_id == strategy_id]

    def summary(self) -> Dict:
        """Summary of all segments."""
        return {
            segment_id: segment.to_dict()
            for segment_id, segment in self.segments.items()
        }
