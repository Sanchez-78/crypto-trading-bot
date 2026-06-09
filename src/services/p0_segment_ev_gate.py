"""
P0.3 — Segment-Based EV Gate (Pure Logic Module)

Core responsibility: Decide if a trading signal meets STRICT_EV criteria
or must be routed to PAPER_EVIDENCE_COLLECTION.

This module is intentionally pure logic — no Binance, Firebase, execution,
or strategy tuning. Easy to test, easy to audit, easy to disable/evolve.

Key split:
- STRICT_EV: Requires segment evidence (n>=30, PF>=1.2, avg_pnl>0, timeout_rate<=60%)
- PAPER_EVIDENCE_COLLECTION: Allowed for approved collection (ETHUSDT, no strict claim)
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple
import math


@dataclass(frozen=True)
class SegmentKey:
    """Unique identifier for a trading segment."""
    symbol: str
    side: str
    regime: str
    source: str
    tp_sl_profile: str

    def __hash__(self):
        return hash((self.symbol, self.side, self.regime, self.source, self.tp_sl_profile))

    def __eq__(self, other):
        if not isinstance(other, SegmentKey):
            return False
        return (self.symbol == other.symbol and
                self.side == other.side and
                self.regime == other.regime and
                self.source == other.source and
                self.tp_sl_profile == other.tp_sl_profile)


@dataclass
class SegmentStats:
    """Realized statistics for a segment (from closed trade history)."""
    key: SegmentKey
    n: int                      # Total trades in segment
    wins: int                   # Trades with pnl_usd > 0
    losses: int                 # Trades with pnl_usd <= 0
    gross_win_usd: float       # Sum of all winning trades
    gross_loss_usd: float      # Absolute sum of all losing trades
    net_pnl_usd: float         # Total profit/loss
    avg_pnl_usd: float         # Average per trade
    profit_factor: float       # gross_win / gross_loss (0 if no losses)
    timeout_count: int         # Trades that exited on TIMEOUT
    timeout_rate: float        # timeout_count / n

    def win_rate(self) -> float:
        """Win rate as percentage (0-100)."""
        if self.n == 0:
            return 0.0
        return 100.0 * self.wins / self.n


@dataclass
class SegmentGateDecision:
    """Decision from segment eligibility gate."""
    strict_ev_allowed: bool      # True if segment meets all strict EV criteria
    reason: str                  # Human-readable decision reason
    readiness_eligible: bool     # True if segment can contribute to readiness claim
    realized_ev_usd: Optional[float] = None  # Realized EV (avg_pnl_usd), if positive
    stats: Optional[SegmentStats] = None     # Computed stats (may be None if insufficient data)


class P0SegmentEVGate:
    """
    P0.3 Segment EV Gate — Pure logic for strict vs evidence-collection routing.

    No dependencies: pure dataclass logic, easy to test in isolation.
    """

    # Strict EV eligibility thresholds (immutable)
    MIN_SAMPLE_SIZE = 30
    MIN_PROFIT_FACTOR = 1.2
    MAX_TIMEOUT_RATE = 0.60

    # Quarantined segments (not eligible for strict EV until evidence proves otherwise)
    QUARANTINED_SYMBOLS = {"BTCUSDT", "SOLUSDT"}
    QUARANTINED_REGIMES = {"BEAR_TREND"}

    # Allowed evidence collection scope
    EVIDENCE_COLLECTION_SYMBOLS = {"ETHUSDT"}
    EVIDENCE_COLLECTION_REGIMES = {"BULL_TREND", "BEAR_TREND"}  # Can collect both, but analyze separately

    @staticmethod
    def build_segment_key(
        symbol: str,
        side: str,
        regime: str,
        source: str,
        tp_sl_profile: str
    ) -> SegmentKey:
        """Construct segment key from signal/trade metadata."""
        return SegmentKey(
            symbol=symbol or "UNKNOWN",
            side=side or "UNKNOWN",
            regime=regime or "UNKNOWN",
            source=source or "UNKNOWN",
            tp_sl_profile=tp_sl_profile or "UNKNOWN",
        )

    @staticmethod
    def compute_segment_stats(
        closed_trades: list[dict],
        key: SegmentKey
    ) -> Optional[SegmentStats]:
        """
        Compute realized statistics for a segment from closed trade history.

        Args:
            closed_trades: List of closed trade dicts with schema:
                {symbol, side, regime, source, tp_sl_profile, pnl_usd, exit_reason, ...}
            key: SegmentKey to filter trades

        Returns:
            SegmentStats if n > 0, else None
        """
        if not closed_trades:
            return None

        # Filter trades matching segment key
        segment_trades = []
        for trade in closed_trades:
            if (trade.get("symbol") == key.symbol and
                trade.get("side") == key.side and
                trade.get("regime") == key.regime and
                trade.get("source") == key.source and
                trade.get("tp_sl_profile") == key.tp_sl_profile):
                segment_trades.append(trade)

        n = len(segment_trades)
        if n == 0:
            return None

        # Compute stats
        wins = 0
        losses = 0
        gross_win = 0.0
        gross_loss = 0.0
        net_pnl = 0.0
        timeout_count = 0

        for trade in segment_trades:
            pnl = trade.get("pnl_usd", 0.0)
            net_pnl += pnl

            if pnl > 0:
                wins += 1
                gross_win += pnl
            else:
                losses += 1
                gross_loss += abs(pnl)

            if trade.get("exit_reason") == "TIMEOUT":
                timeout_count += 1

        avg_pnl = net_pnl / n if n > 0 else 0.0
        pf = gross_win / max(gross_loss, 1e-9)  # Avoid division by zero
        timeout_rate = timeout_count / n if n > 0 else 0.0

        return SegmentStats(
            key=key,
            n=n,
            wins=wins,
            losses=losses,
            gross_win_usd=gross_win,
            gross_loss_usd=gross_loss,
            net_pnl_usd=net_pnl,
            avg_pnl_usd=avg_pnl,
            profit_factor=pf,
            timeout_count=timeout_count,
            timeout_rate=timeout_rate,
        )

    @staticmethod
    def is_quarantined_for_strict_ev(symbol: str, regime: str) -> Tuple[bool, str]:
        """
        Check if segment is quarantined (not eligible for strict EV).

        Returns:
            (is_quarantined, reason)
        """
        if symbol in P0SegmentEVGate.QUARANTINED_SYMBOLS:
            return True, f"symbol_quarantined_p0:{symbol}"
        if regime in P0SegmentEVGate.QUARANTINED_REGIMES:
            return True, f"regime_quarantined_p0:{regime}"
        return False, "not_quarantined"

    @staticmethod
    def is_eligible_for_evidence_collection(symbol: str, regime: str) -> Tuple[bool, str]:
        """
        Check if segment is in the allowed evidence collection scope.

        Returns:
            (is_allowed, reason)
        """
        if symbol not in P0SegmentEVGate.EVIDENCE_COLLECTION_SYMBOLS:
            return False, f"symbol_not_in_evidence_scope:{symbol}"
        if regime not in P0SegmentEVGate.EVIDENCE_COLLECTION_REGIMES:
            return False, f"regime_not_in_evidence_scope:{regime}"
        return True, "allowed_for_evidence_collection"

    @staticmethod
    def evaluate_segment_for_strict_ev(stats: SegmentStats) -> SegmentGateDecision:
        """
        Evaluate if a segment meets strict EV criteria.

        Requires ALL of:
        - n >= 30 trades
        - avg_pnl_usd > 0 (profitable)
        - profit_factor >= 1.2
        - timeout_rate <= 60%

        Args:
            stats: SegmentStats from segment history

        Returns:
            SegmentGateDecision with strict_ev_allowed=True only if ALL pass
        """
        # Check minimum sample size
        if stats.n < P0SegmentEVGate.MIN_SAMPLE_SIZE:
            return SegmentGateDecision(
                strict_ev_allowed=False,
                reason=f"insufficient_evidence:n={stats.n}<{P0SegmentEVGate.MIN_SAMPLE_SIZE}",
                readiness_eligible=False,
                stats=stats,
            )

        # Check profitability
        if stats.avg_pnl_usd <= 0:
            return SegmentGateDecision(
                strict_ev_allowed=False,
                reason=f"negative_expectancy:avg_pnl={stats.avg_pnl_usd:.8f}",
                readiness_eligible=False,
                realized_ev_usd=stats.avg_pnl_usd,
                stats=stats,
            )

        # Check profit factor
        if stats.profit_factor < P0SegmentEVGate.MIN_PROFIT_FACTOR:
            return SegmentGateDecision(
                strict_ev_allowed=False,
                reason=f"pf_too_low:pf={stats.profit_factor:.2f}<{P0SegmentEVGate.MIN_PROFIT_FACTOR}",
                readiness_eligible=False,
                realized_ev_usd=stats.avg_pnl_usd,
                stats=stats,
            )

        # Check timeout rate
        if stats.timeout_rate > P0SegmentEVGate.MAX_TIMEOUT_RATE:
            return SegmentGateDecision(
                strict_ev_allowed=False,
                reason=f"timeout_rate_too_high:rate={stats.timeout_rate:.1%}>{P0SegmentEVGate.MAX_TIMEOUT_RATE:.1%}",
                readiness_eligible=False,
                realized_ev_usd=stats.avg_pnl_usd,
                stats=stats,
            )

        # All checks pass
        return SegmentGateDecision(
            strict_ev_allowed=True,
            reason="approved:all_criteria_met",
            readiness_eligible=True,
            realized_ev_usd=stats.avg_pnl_usd,
            stats=stats,
        )

    @staticmethod
    def decide_segment_gate(
        symbol: str,
        side: str,
        regime: str,
        source: str,
        tp_sl_profile: str,
        closed_trades: list[dict],
    ) -> SegmentGateDecision:
        """
        Complete decision pipeline: build key → compute stats → evaluate → decide.

        This is the main entry point for deciding if a signal is approved for strict EV.

        Args:
            symbol: Trading pair (e.g., "ETHUSDT")
            side: "BUY" or "SELL"
            regime: Trend regime (e.g., "BULL_TREND", "BEAR_TREND")
            source: Entry source (e.g., "paper_evidence_collection", "strict_ev")
            tp_sl_profile: TP/SL configuration profile
            closed_trades: Historical closed trades for stats computation

        Returns:
            SegmentGateDecision with full reasoning
        """
        # Step 1: Check quarantine
        is_quar, quar_reason = P0SegmentEVGate.is_quarantined_for_strict_ev(symbol, regime)
        if is_quar:
            return SegmentGateDecision(
                strict_ev_allowed=False,
                reason=quar_reason,
                readiness_eligible=False,
            )

        # Step 2: Build segment key
        key = P0SegmentEVGate.build_segment_key(symbol, side, regime, source, tp_sl_profile)

        # Step 3: Compute segment stats
        stats = P0SegmentEVGate.compute_segment_stats(closed_trades, key)
        if stats is None:
            return SegmentGateDecision(
                strict_ev_allowed=False,
                reason="no_segment_history",
                readiness_eligible=False,
            )

        # Step 4: Evaluate against strict EV criteria
        return P0SegmentEVGate.evaluate_segment_for_strict_ev(stats)
