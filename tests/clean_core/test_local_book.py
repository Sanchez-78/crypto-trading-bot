"""Tests for local order book integrity (tests 5-9)."""

import pytest
from src.clean_core.market.local_book import (
    LocalOrderBook,
    DepthSnapshot,
    DepthEvent,
    BookIntegrityStatus,
)


class TestLocalOrderBook:
    """Test suite for LocalOrderBook."""

    def test_5_snapshot_initialization(self, local_book, depth_snapshot):
        """Test 5: Initialize book with snapshot, verify SYNCED status."""
        assert local_book.status == BookIntegrityStatus.UNINITIALIZED

        local_book.apply_snapshot(depth_snapshot)

        assert local_book.status == BookIntegrityStatus.SYNCED
        assert local_book.last_update_id == 1000
        assert local_book.best_bid == 50000.0
        assert local_book.best_ask == 50001.0

    def test_6_sequence_continuity_gap_detection(self, local_book, depth_snapshot):
        """Test 6: Detect sequence gap when first_update_id breaks continuity."""
        local_book.apply_snapshot(depth_snapshot)

        # Create event with gap: first_update_id should be 1001, but is 1003
        gap_event = DepthEvent(
            first_update_id=1003,
            last_update_id=1010,
            bid_deltas=[[50000.5, 1.0]],
            ask_deltas=[],
        )

        local_book.apply_event(gap_event)

        assert local_book.status == BookIntegrityStatus.GAP_DETECTED
        assert local_book.gap_count > 0

    def test_7_event_application_updates_book(self, local_book, depth_snapshot):
        """Test 7: Apply valid event and verify order book updates."""
        local_book.apply_snapshot(depth_snapshot)

        # Valid continuation event
        event = DepthEvent(
            first_update_id=1001,
            last_update_id=1005,
            previous_final_id=1000,
            bid_deltas=[[50000.5, 1.0]],  # New bid level
            ask_deltas=[[50001.5, 0.5]],  # Update ask
        )

        local_book.apply_event(event)

        assert local_book.last_update_id == 1005
        assert local_book.status == BookIntegrityStatus.SYNCED

    def test_8_stale_detection(self, local_book, depth_snapshot):
        """Test 8: Detect stale order book after threshold."""
        local_book.apply_snapshot(depth_snapshot)

        # Snapshot timestamp is 1234567890000
        # Current time 2000ms later should trigger stale
        current_time = depth_snapshot.timestamp_ms + 2000

        assert local_book.is_stale(current_time) is True

    def test_9_checkpoint_generation(self, local_book, depth_snapshot):
        """Test 9: Generate checkpoint with full tape state."""
        local_book.apply_snapshot(depth_snapshot)

        checkpoint = local_book.checkpoint(depth_snapshot.timestamp_ms)

        assert checkpoint.symbol == "BTCUSDT"
        assert checkpoint.best_bid == 50000.0
        assert checkpoint.best_ask == 50001.0
        assert checkpoint.integrity_status == BookIntegrityStatus.SYNCED
        assert checkpoint.eligible_for_execution_measurement is True
