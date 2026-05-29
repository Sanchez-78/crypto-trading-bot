"""Tests for MVP taker-fee-only model."""

import pytest
from src.clean_core.execution.fees import FeeSchedule
from src.clean_core.execution.paper_accounting import FillObservation, ClosedPaperOutcome
from src.clean_core.domain import ExecutionTruthClass
from datetime import datetime, timezone


class TestTakerFeeMVP:
    """Validate MVP uses taker fees for all touch fills."""

    def test_10_fee_schedule_has_maker_and_taker(self, fee_schedule):
        """Test 10: FeeSchedule has separate maker/taker rates."""
        assert fee_schedule.maker_fee_bps > 0
        assert fee_schedule.taker_fee_bps > 0
        # Taker should be higher (market orders)
        assert fee_schedule.taker_fee_bps >= fee_schedule.maker_fee_bps

    def test_11_entry_cost_bps_taker_is_higher(self, fee_schedule):
        """Test 11: Taker entry cost is higher than maker."""
        maker_entry = fee_schedule.entry_cost_bps(is_maker=True)
        taker_entry = fee_schedule.entry_cost_bps(is_maker=False)
        assert taker_entry >= maker_entry

    def test_12_exit_cost_bps_taker_is_higher(self, fee_schedule):
        """Test 12: Taker exit cost is higher than maker."""
        maker_exit = fee_schedule.exit_cost_bps(is_maker=True)
        taker_exit = fee_schedule.exit_cost_bps(is_maker=False)
        assert taker_exit >= maker_exit

    def test_13_closed_outcome_uses_taker_fees(
        self, market_source_futures, fee_schedule
    ):
        """Test 13: ClosedPaperOutcome.calculate_from_fills uses taker fees."""
        entry_fill = FillObservation(
            position_id="test_pos_taker",
            symbol="BTCUSDT",
            side="long",
            qty=1.0,
            touch_price=50000.0,
            fill_price=50000.0,
            midpoint=50000.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            market_source=market_source_futures,
            timestamp_utc="2026-05-26T12:00:00Z",
        )

        exit_fill = FillObservation(
            position_id="test_pos_taker",
            symbol="BTCUSDT",
            side="long",
            qty=1.0,
            touch_price=50100.0,
            fill_price=50100.0,
            midpoint=50100.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            market_source=market_source_futures,
            timestamp_utc="2026-05-26T13:00:00Z",
        )

        from src.clean_core.execution.funding import FundingRealization
        funding = FundingRealization(
            symbol="BTCUSDT",
            position_id="test_pos_taker",
            entry_time_utc="2026-05-26T12:00:00Z",
            exit_time_utc="2026-05-26T13:00:00Z",
            holding_hours=1.0,
            funding_payments=[],
            total_cashflow_bps=0.0,
            reconciliation_status="complete",
        )

        outcome = ClosedPaperOutcome.calculate_from_fills(
            position_id="test_pos_taker",
            epoch_id="test_taker",
            entry_fill=entry_fill,
            exit_fill=exit_fill,
            fee_schedule=fee_schedule,
            funding_realization=funding,
            entry_time_utc="2026-05-26T12:00:00Z",
            exit_time_utc="2026-05-26T13:00:00Z",
            holding_minutes=60.0,
        )

        # Fee cost should match taker (not maker)
        expected_taker_fees = (fee_schedule.taker_fee_bps * 2) / 100.0
        assert outcome.fee_cost_pct == pytest.approx(expected_taker_fees, rel=0.01)

    def test_14_mvp_never_uses_maker_fees(
        self, market_source_futures, fee_schedule
    ):
        """Test 14: MVP MVP configuration never produces maker-fee outcomes."""
        # Create outcome with valid Futures data
        from src.clean_core.execution.paper_accounting import FillObservation
        from src.clean_core.execution.funding import FundingRealization

        entry_fill = FillObservation(
            position_id="test_pos_mvp",
            symbol="BTCUSDT",
            side="long",
            qty=1.0,
            touch_price=50000.0,
            fill_price=50000.0,
            midpoint=50000.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            market_source=market_source_futures,
            timestamp_utc="2026-05-26T12:00:00Z",
        )

        exit_fill = FillObservation(
            position_id="test_pos_mvp",
            symbol="BTCUSDT",
            side="long",
            qty=1.0,
            touch_price=50100.0,
            fill_price=50100.0,
            midpoint=50100.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            market_source=market_source_futures,
            timestamp_utc="2026-05-26T13:00:00Z",
        )

        funding = FundingRealization(
            symbol="BTCUSDT",
            position_id="test_pos_mvp",
            entry_time_utc="2026-05-26T12:00:00Z",
            exit_time_utc="2026-05-26T13:00:00Z",
            holding_hours=1.0,
            funding_payments=[],
            total_cashflow_bps=0.0,
            reconciliation_status="complete",
        )

        outcome = ClosedPaperOutcome.calculate_from_fills(
            position_id="test_pos_mvp",
            epoch_id="test_mvp",
            entry_fill=entry_fill,
            exit_fill=exit_fill,
            fee_schedule=fee_schedule,
            funding_realization=funding,
            entry_time_utc="2026-05-26T12:00:00Z",
            exit_time_utc="2026-05-26T13:00:00Z",
            holding_minutes=60.0,
        )

        # Cost must be taker-based (touch fills)
        expected_taker_cost = (fee_schedule.taker_fee_bps * 2) / 100.0
        assert outcome.fee_cost_pct == pytest.approx(expected_taker_cost, rel=0.01)
