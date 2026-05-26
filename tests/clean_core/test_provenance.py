"""Tests for provenance/epoch/journal (tests 15-20)."""

import pytest
import os
from src.clean_core.provenance.epoch import CleanPaperEpoch
from src.clean_core.provenance.journal import CleanCoreJournal
from src.clean_core.provenance.eligibility import (
    LearningEligibility,
    LearningEligibilityResolver,
)
from src.clean_core.domain import ExecutionTruthClass


class TestCleanPaperEpoch:
    """Test suite for CleanPaperEpoch."""

    def test_15_epoch_creation_and_tracking(self, clean_epoch):
        """Test 15: Create epoch and track closed trades."""
        assert clean_epoch.status == "active"
        assert clean_epoch.closed_trades_count == 0

        # Add a futures-qualified trade
        clean_epoch.add_closed_trade(
            net_pnl_pct=0.5,
            readiness_eligible=True,
            execution_truth_class="futures_rpi_aware_measured",
        )

        assert clean_epoch.closed_trades_count == 1
        assert clean_epoch.readiness_eligible_count == 1
        assert clean_epoch.total_net_pnl_pct == 0.5

    def test_16_epoch_readiness_check_threshold(self, clean_epoch):
        """Test 16: Epoch readiness requires min observations."""
        clean_epoch.min_observations = 5

        # Add 3 trades (below threshold)
        for i in range(3):
            clean_epoch.add_closed_trade(
                net_pnl_pct=0.1,
                readiness_eligible=True,
                execution_truth_class="futures_rpi_aware_measured",
            )

        assert clean_epoch.is_ready_for_readiness_check() is False

        # Add 2 more (reach threshold)
        for i in range(2):
            clean_epoch.add_closed_trade(
                net_pnl_pct=0.1,
                readiness_eligible=True,
                execution_truth_class="futures_rpi_aware_measured",
            )

        clean_epoch.status = "completed"
        assert clean_epoch.is_ready_for_readiness_check() is True

    def test_17_journal_append_and_read(self, journal):
        """Test 17: Append events to journal and retrieve them."""
        event1_data = {"trade_id": "t001", "pnl_pct": 0.5}
        journal.append_event("trade_closed", event1_data, clean_core_version="R1")

        event2_data = {"epoch_id": "e001", "status": "completed"}
        journal.append_event(
            "epoch_completed", event2_data, clean_core_version="R1"
        )

        events = journal.read_events()
        assert len(events) == 2
        assert events[0]["event_type"] == "trade_closed"
        assert events[1]["event_type"] == "epoch_completed"

    def test_18_journal_event_filtering(self, journal):
        """Test 18: Filter journal events by type."""
        journal.append_event("trade_closed", {"trade_id": "t001"})
        journal.append_event("learning_update", {"epoch_id": "e001"})
        journal.append_event("trade_closed", {"trade_id": "t002"})

        closed_events = journal.read_events(event_type_filter="trade_closed")
        assert len(closed_events) == 2

        learning_events = journal.read_events(event_type_filter="learning_update")
        assert len(learning_events) == 1

    def test_19_eligibility_resolver_futures_qualified(self, clean_epoch):
        """Test 19: Futures RPI-measured outcome is eligible for learning."""
        resolver = LearningEligibilityResolver(clean_epoch)

        outcome = {
            "execution_truth_class": ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED.value,
            "readiness_eligible": True,
            "epoch_id": clean_epoch.epoch_id,
            "market_tape_status": "synced",
            "test_generated": False,
        }

        eligibility = resolver.resolve(outcome)

        assert eligibility.eligible is True
        assert eligibility.reason == LearningEligibility.VALID_CLEAN_FUTURES

    def test_20_eligibility_resolver_legacy_spot_rejected(self, clean_epoch):
        """Test 20: Legacy Spot execution is ineligible for learning."""
        resolver = LearningEligibilityResolver(clean_epoch)

        outcome = {
            "execution_truth_class": ExecutionTruthClass.LEGACY_SPOT_EXECUTION_UNVERIFIED.value,
            "readiness_eligible": False,
            "epoch_id": clean_epoch.epoch_id,
            "market_tape_status": "synced",
            "test_generated": False,
        }

        eligibility = resolver.resolve(outcome)

        assert eligibility.eligible is False
        assert eligibility.reason == LearningEligibility.LEGACY_SPOT
