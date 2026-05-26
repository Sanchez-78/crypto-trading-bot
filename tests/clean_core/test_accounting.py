"""Tests for PAPER execution accounting (tests 10-14)."""

import pytest
from src.clean_core.execution.paper_accounting import FillObservation, ClosedPaperOutcome
from src.clean_core.execution.funding import FundingRealization
from src.clean_core.domain import ExecutionTruthClass
from datetime import datetime, timezone


class TestExecutionAccounting:
    """Test suite for PAPER execution accounting."""

    def test_10_fill_observation_creation(self, market_source_futures):
        """Test 10: Create fill observation with accurate slippage calc."""
        fill = FillObservation(
            position_id="test_pos_001",
            symbol="BTCUSDT",
            side="long",
            qty=1.0,
            touch_price=50000.0,
            fill_price=50001.0,
            midpoint=50000.5,
            spread_bps=0.2,
            slippage_bps=2.0,  # (50001 - 50000) / 50000 * 10000
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            market_source=market_source_futures,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )

        assert fill.position_id == "test_pos_001"
        assert fill.slippage_bps == 2.0
        assert fill.execution_truth_class == ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED

    def test_11_closed_outcome_pnl_calculation(
        self, market_source_futures, fee_schedule
    ):
        """Test 11: Calculate complete PnL from entry/exit fills."""
        entry_fill = FillObservation(
            position_id="test_pos_001",
            symbol="BTCUSDT",
            side="long",
            qty=1.0,
            touch_price=50000.0,
            fill_price=50000.0,
            midpoint=50000.5,
            spread_bps=0.2,
            slippage_bps=0.0,
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            market_source=market_source_futures,
            timestamp_utc="2026-05-26T12:00:00Z",
        )

        exit_fill = FillObservation(
            position_id="test_pos_001",
            symbol="BTCUSDT",
            side="long",
            qty=1.0,
            touch_price=50100.0,
            fill_price=50100.0,
            midpoint=50100.0,
            spread_bps=0.2,
            slippage_bps=0.0,
            execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
            market_source=market_source_futures,
            timestamp_utc="2026-05-26T13:00:00Z",
        )

        funding = FundingRealization(
            symbol="BTCUSDT",
            position_id="test_pos_001",
            entry_time_utc="2026-05-26T12:00:00Z",
            exit_time_utc="2026-05-26T13:00:00Z",
            holding_hours=1.0,
            funding_payments=[
                {"timestamp": "2026-05-26T13:00:00Z", "rate_bps": 10.0, "cashflow_bps": 10.0}
            ],
            total_cashflow_bps=10.0,
            reconciliation_status="complete",
        )

        outcome = ClosedPaperOutcome.calculate_from_fills(
            position_id="test_pos_001",
            epoch_id="clean_core_r1_test_001",
            entry_fill=entry_fill,
            exit_fill=exit_fill,
            fee_schedule=fee_schedule,
            funding_realization=funding,
            entry_time_utc="2026-05-26T12:00:00Z",
            exit_time_utc="2026-05-26T13:00:00Z",
            holding_minutes=60.0,
        )

        assert outcome.gross_pnl_pct > 0  # (50100 - 50000) / 50000 = 0.2%
        assert outcome.net_pnl_pct > 0  # gross - fees - funding

    def test_12_fee_schedule_round_trip(self, fee_schedule):
        """Test 12: Calculate round-trip cost with maker/taker."""
        cost = fee_schedule.total_round_trip_bps(entry_is_maker=True, exit_is_maker=False)

        assert cost == fee_schedule.maker_fee_bps + fee_schedule.taker_fee_bps

    def test_13_fill_invalid_side_rejected(self, market_source_futures):
        """Test 13: Reject invalid side on fill."""
        with pytest.raises(ValueError):
            FillObservation(
                position_id="test_pos",
                symbol="BTCUSDT",
                side="invalid",
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

    def test_14_readiness_eligibility_determined_by_execution_truth(
        self, market_source_futures, market_source_futures_rpi, fee_schedule
    ):
        """Test 14: Readiness eligibility depends on execution_truth_class."""
        # Create two fills with different execution truth
        entry_fill_rpi = FillObservation(
            position_id="test_pos_rpi",
            symbol="BTCUSDT",
            side="long",
            qty=1.0,
            touch_price=50000.0,
            fill_price=50000.0,
            midpoint=50000.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            execution_truth_class=ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED,
            market_source=market_source_futures_rpi,
            timestamp_utc="2026-05-26T12:00:00Z",
        )

        exit_fill_rpi = FillObservation(
            position_id="test_pos_rpi",
            symbol="BTCUSDT",
            side="long",
            qty=1.0,
            touch_price=50100.0,
            fill_price=50100.0,
            midpoint=50100.0,
            spread_bps=0.0,
            slippage_bps=0.0,
            execution_truth_class=ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED,
            market_source=market_source_futures_rpi,
            timestamp_utc="2026-05-26T13:00:00Z",
        )

        funding = FundingRealization(
            symbol="BTCUSDT",
            position_id="test_pos_rpi",
            entry_time_utc="2026-05-26T12:00:00Z",
            exit_time_utc="2026-05-26T13:00:00Z",
            holding_hours=1.0,
            funding_payments=[],
            total_cashflow_bps=0.0,
            reconciliation_status="complete",
        )

        outcome = ClosedPaperOutcome.calculate_from_fills(
            position_id="test_pos_rpi",
            epoch_id="test",
            entry_fill=entry_fill_rpi,
            exit_fill=exit_fill_rpi,
            fee_schedule=fee_schedule,
            funding_realization=funding,
            entry_time_utc="2026-05-26T12:00:00Z",
            exit_time_utc="2026-05-26T13:00:00Z",
            holding_minutes=60.0,
        )

        # RPI-aware measurement should be clean PAPER metrics eligible, but never REAL readiness
        assert outcome.eligible_for_clean_paper_metrics is True
        assert outcome.eligible_for_real_readiness is False
        assert (
            outcome.execution_truth_class
            == ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED
        )
