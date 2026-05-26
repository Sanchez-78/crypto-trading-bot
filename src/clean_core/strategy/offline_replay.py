"""Offline PAPER replay engine for deterministic lifecycle simulation."""

from datetime import datetime, timezone, timedelta
from typing import Optional, List
import json

from src.clean_core.strategy.fixed_strategy import FixedStrategy, SignalHypothesis
from src.clean_core.strategy.paper_position import PaperPosition, PositionState
from src.clean_core.execution.paper_accounting import FillObservation, ClosedPaperOutcome
from src.clean_core.execution.fees import FeeSchedule
from src.clean_core.execution.funding import FundingRealization
from src.clean_core.domain import ExecutionTruthClass, MarketSourceIdentity
from src.clean_core.market.local_book import LocalOrderBook, DepthSnapshot, DepthEvent


class OfflineReplayEngine:
    """Replay a complete PAPER trade lifecycle offline (no live sockets)."""

    def __init__(
        self,
        strategy: FixedStrategy,
        fee_schedule: FeeSchedule,
        market_source: MarketSourceIdentity,
    ):
        self.strategy = strategy
        self.fee_schedule = fee_schedule
        self.market_source = market_source
        self.positions: dict[str, PaperPosition] = {}
        self.closed_positions: List[PaperPosition] = []
        self.next_position_id = 0

    def replay_snapshot_and_trades(
        self,
        symbol: str,
        initial_snapshot: dict,
        trades: List[dict],
        epoch_id: str = "offline_replay",
    ) -> List[ClosedPaperOutcome]:
        """
        Replay a complete market sequence and generate closed PAPER outcomes.

        Args:
            symbol: "BTCUSDT"
            initial_snapshot: {"time": "2026-05-26T12:00:00Z", "price": 50000.0, "bid": 49999.5, "ask": 50000.5}
            trades: [
                {"time": "2026-05-26T12:01:00Z", "price": 50000.2, "bid": 49999.8, "ask": 50000.6},
                ...
            ]
            epoch_id: Epoch identifier

        Returns: List of ClosedPaperOutcome
        """
        closed_outcomes = []
        current_price = initial_snapshot["price"]
        current_time = initial_snapshot["time"]
        current_bid = initial_snapshot.get("bid", current_price - 0.5)
        current_ask = initial_snapshot.get("ask", current_price + 0.5)

        # Initial state: start with snapshot price as baseline high/low
        recent_high = current_price
        recent_low = current_price

        # Simulate each trade in sequence
        for i, trade in enumerate(trades):
            current_time = trade["time"]
            current_price = trade["price"]
            current_bid = trade.get("bid", current_price - 0.5)
            current_ask = trade.get("ask", current_price + 0.5)

            # Update recent high/low (10-trade window from PREVIOUS trades only)
            recent_prices = [t["price"] for t in trades[max(0, i - 10) : i]]  # Exclude current
            if recent_prices:
                recent_high = max(recent_prices)
                recent_low = min(recent_prices)
            # If no previous trades, keep using the initial recent_high/low (don't reset)

            # Step 1: Check for entry signal
            signal = self.strategy.generate_signal(symbol, current_price, recent_high, recent_low)

            if signal and not self.positions:  # Only enter if no position open
                self.next_position_id += 1
                entry_position = self._open_position(
                    signal=signal,
                    entry_price=current_price,
                    entry_time_utc=current_time,
                    entry_bid=current_bid,
                    entry_ask=current_ask,
                )

            # Step 2: Check exit conditions for any open position
            if self.positions:
                pos_id = list(self.positions.keys())[0]
                pos = self.positions[pos_id]

                if pos.is_open():
                    minutes_held = self._minutes_between(pos.entry_time_utc, current_time)
                    should_exit, exit_reason = self.strategy.should_exit(
                        current_price, pos.entry_price, minutes_held
                    )

                    if should_exit:
                        closed_outcome = self._close_position(
                            position_id=pos_id,
                            exit_price=current_price,
                            exit_reason=exit_reason,
                            exit_time_utc=current_time,
                            exit_bid=current_bid,
                            exit_ask=current_ask,
                            epoch_id=epoch_id,
                        )
                        if closed_outcome:
                            closed_outcomes.append(closed_outcome)

        return closed_outcomes

    def _open_position(
        self,
        signal: SignalHypothesis,
        entry_price: float,
        entry_time_utc: str,
        entry_bid: float,
        entry_ask: float,
    ) -> PaperPosition:
        """Open a new PAPER position."""
        self.next_position_id += 1
        pos_id = f"pos_{self.next_position_id}"

        tp = self.strategy.tp_target_price(entry_price)
        sl = self.strategy.sl_target_price(entry_price)

        position = PaperPosition(
            position_id=pos_id,
            symbol=signal.symbol,
            entry_price=entry_price,
            qty=1.0,
            side=signal.side,
            entry_time_utc=entry_time_utc,
            tp_price=tp,
            sl_price=sl,
            timeout_minutes=self.strategy.timeout_minutes,
            entry_metadata={
                "signal_id": signal.signal_id,
                "hypothesis": signal.hypothesis,
                "entry_reason": signal.entry_reason,
            },
        )

        position.open()
        self.positions[pos_id] = position
        return position

    def _close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str,
        exit_time_utc: str,
        exit_bid: float,
        exit_ask: float,
        epoch_id: str,
    ) -> Optional[ClosedPaperOutcome]:
        """Close an open position and generate ClosedPaperOutcome."""
        if position_id not in self.positions:
            return None

        position = self.positions.pop(position_id)
        position.close(exit_price, exit_reason, exit_time_utc)
        self.closed_positions.append(position)

        # Create fill observations
        entry_fill = FillObservation(
            position_id=position_id,
            symbol=position.symbol,
            side=position.side,
            qty=position.qty,
            touch_price=position.entry_price,
            fill_price=position.entry_price,
            midpoint=(position.entry_price),
            spread_bps=0.0,
            slippage_bps=0.0,
            execution_truth_class=self.market_source.execution_truth_class,
            market_source=self.market_source,
            timestamp_utc=position.entry_time_utc,
        )

        exit_fill = FillObservation(
            position_id=position_id,
            symbol=position.symbol,
            side=position.side,
            qty=position.qty,
            touch_price=exit_price,
            fill_price=exit_price,
            midpoint=exit_price,
            spread_bps=0.0,
            slippage_bps=position.exit_slippage_bps,
            execution_truth_class=self.market_source.execution_truth_class,
            market_source=self.market_source,
            timestamp_utc=exit_time_utc,
        )

        # Create funding realization (no funding for MVP)
        funding = FundingRealization(
            symbol=position.symbol,
            position_id=position_id,
            entry_time_utc=position.entry_time_utc,
            exit_time_utc=exit_time_utc,
            holding_hours=(position.holding_minutes() or 0) / 60.0,
            funding_payments=[],
            total_cashflow_bps=0.0,
            reconciliation_status="complete",
        )

        # Calculate outcome
        outcome = ClosedPaperOutcome.calculate_from_fills(
            position_id=position_id,
            epoch_id=epoch_id,
            entry_fill=entry_fill,
            exit_fill=exit_fill,
            fee_schedule=self.fee_schedule,
            funding_realization=funding,
            entry_time_utc=position.entry_time_utc,
            exit_time_utc=exit_time_utc,
            holding_minutes=position.holding_minutes() or 0,
            learning_source="canonical",
        )

        return outcome

    def _minutes_between(self, time_start: str, time_end: str) -> float:
        """Calculate minutes between two ISO timestamps."""
        try:
            dt_start = datetime.fromisoformat(time_start.replace("Z", "+00:00"))
            dt_end = datetime.fromisoformat(time_end.replace("Z", "+00:00"))
            return (dt_end - dt_start).total_seconds() / 60.0
        except Exception:
            return 0.0
