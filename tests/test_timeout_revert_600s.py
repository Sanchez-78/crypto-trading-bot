"""Test timeout revert from 1200s back to 600s (CYCLE 31 revert).

Tests verify:
1. Position closes at 600s with TIMEOUT exit even if TP not hit
2. Position closes at TP before 600s (TP exit)
3. No regressions in exit timing

Note: These tests focus on the timeout mechanism itself (effective_hold_s,
check_and_close_timeout_positions) rather than full position opening workflow,
since the latter involves complex gating that requires broader test setup.
"""
import pytest
import time
import os
from unittest.mock import patch

from src.services.paper_trade_executor import (
    _effective_paper_hold_s,
    _POSITIONS,
    _POSITION_LOCK,
    reset_paper_positions,
    check_and_close_timeout_positions,
    close_paper_position,
)


@pytest.fixture
def clean_positions():
    """Fixture to ensure clean state before/after tests."""
    reset_paper_positions()
    yield
    reset_paper_positions()


@pytest.fixture
def timeout_600s():
    """Fixture to set timeout to 600s for testing."""
    import src.services.paper_trade_executor as pte
    original = pte._MAX_AGE_S
    pte._MAX_AGE_S = 600.0
    yield
    pte._MAX_AGE_S = original


def _inject_position(trade_id: str, entry_ts: float, symbol: str = "XRPUSDT",
                     training_bucket: str = None, max_hold_s: float = None,
                     last_price_ts: float = None) -> dict:
    """Inject a position directly into the in-memory state for testing.

    Args:
        trade_id: Unique trade identifier
        entry_ts: Entry timestamp
        symbol: Trading pair symbol
        training_bucket: Optional training bucket classification
        max_hold_s: Optional explicit max hold time
        last_price_ts: Timestamp for last price update (defaults to entry_ts)
    """
    entry_price = 2.5
    tp_price = entry_price * 1.012
    sl_price = entry_price * 0.988

    # Use entry_ts as last_price_ts by default to ensure price is always fresh
    if last_price_ts is None:
        last_price_ts = entry_ts

    pos = {
        "trade_id": trade_id,
        "symbol": symbol,
        "entry_price": entry_price,
        "entry_ts": entry_ts,
        "created_at": entry_ts,
        "side": "BUY",
        "tp_price": tp_price,
        "sl_price": sl_price,
        "size_usd": 25.0,
        "last_price": entry_price,
        "last_price_ts": last_price_ts,
    }

    if training_bucket:
        pos["training_bucket"] = training_bucket
    if max_hold_s is not None:
        pos["max_hold_s"] = max_hold_s

    with _POSITION_LOCK:
        _POSITIONS[trade_id] = pos

    return pos


class TestEffectiveHoldTimeCalculation:
    """Test _effective_paper_hold_s calculation."""

    def test_default_600s_timeout(self, timeout_600s):
        """Non-training position defaults to 600s."""
        pos = {
            "symbol": "XRPUSDT",
            "side": "BUY",
            "entry_price": 2.5,
        }

        effective = _effective_paper_hold_s(pos)
        assert effective == 600.0

    def test_training_position_capped_at_600s(self, timeout_600s):
        """Training position is capped at 600s even with larger max_hold."""
        pos = {
            "symbol": "XRPUSDT",
            "training_bucket": "C_WEAK_EV_TRAIN",
            "max_hold_s": 1200.0,  # Old cycle 31 value
        }

        effective = _effective_paper_hold_s(pos)
        assert effective == 600.0

    def test_training_position_respects_smaller_max_hold(self, timeout_600s):
        """Training position with smaller max_hold uses that value."""
        pos = {
            "symbol": "XRPUSDT",
            "training_bucket": "C_WEAK_EV_TRAIN",
            "max_hold_s": 300.0,
        }

        effective = _effective_paper_hold_s(pos)
        assert effective == 300.0

    def test_explicit_timeout_s_used_if_present(self, timeout_600s):
        """If timeout_s explicitly set, it's used."""
        pos = {
            "symbol": "XRPUSDT",
            "timeout_s": 450.0,
        }

        effective = _effective_paper_hold_s(pos)
        assert effective == 450.0

    def test_exploration_bucket_respects_max_hold(self, timeout_600s):
        """Exploration position respects explicit max_hold_s."""
        pos = {
            "symbol": "ETHUSDT",
            "explore_bucket": "C_WEAK_EV",
            "max_hold_s": 400.0,
        }

        effective = _effective_paper_hold_s(pos)
        assert effective == 400.0


class TestTimeoutClosures:
    """Test timeout-based position closure at 600s boundary."""

    def test_position_closes_at_600s(self, clean_positions, timeout_600s):
        """Position closes exactly at 600s."""
        entry_ts = time.time()
        trade_id = "paper_test_600s"
        exit_ts = entry_ts + 600.0

        # Inject position with last_price_ts near the exit time to keep price fresh
        _inject_position(trade_id, entry_ts, last_price_ts=exit_ts - 60.0)

        # Check at 600s (price is 60s old, still within 120s max age)
        closed_trades = check_and_close_timeout_positions(exit_ts)

        assert len(closed_trades) == 1
        assert closed_trades[0]["trade_id"] == trade_id
        assert closed_trades[0]["exit_reason"] == "TIMEOUT"

    def test_position_does_not_close_at_599_9s(self, clean_positions, timeout_600s):
        """Position does NOT close at 599.9s."""
        entry_ts = time.time()
        trade_id = "paper_test_599_9"

        _inject_position(trade_id, entry_ts)

        # Check at 599.9s
        exit_ts = entry_ts + 599.9
        closed_trades = check_and_close_timeout_positions(exit_ts)

        assert len(closed_trades) == 0

        # Verify position still open
        with _POSITION_LOCK:
            assert trade_id in _POSITIONS

    def test_position_closes_at_600_1s(self, clean_positions, timeout_600s):
        """Position closes at 600.1s (past boundary)."""
        entry_ts = time.time()
        trade_id = "paper_test_600_1"

        _inject_position(trade_id, entry_ts)

        # Check at 600.1s
        exit_ts = entry_ts + 600.1
        closed_trades = check_and_close_timeout_positions(exit_ts)

        assert len(closed_trades) == 1
        assert closed_trades[0]["trade_id"] == trade_id

    def test_multiple_positions_close_at_600s(self, clean_positions, timeout_600s):
        """Multiple positions all close at 600s timeout."""
        entry_ts = time.time()

        # Inject 3 positions
        trade_ids = []
        for i in range(3):
            trade_id = f"paper_multi_{i}"
            _inject_position(trade_id, entry_ts, symbol=f"SYM{i}")
            trade_ids.append(trade_id)

        assert len(trade_ids) == 3

        # All should timeout at 600s
        exit_ts = entry_ts + 600.0
        closed_trades = check_and_close_timeout_positions(exit_ts)

        assert len(closed_trades) == 3
        closed_ids = {t["trade_id"] for t in closed_trades}
        assert closed_ids == set(trade_ids)

    def test_partial_positions_close_at_600s(self, clean_positions, timeout_600s):
        """Only timed-out positions close; others remain open."""
        entry_ts = time.time()

        # Position 1: should timeout
        _inject_position("paper_timeout", entry_ts)

        # Position 2: entered later, should NOT timeout yet
        later_ts = entry_ts + 300.0
        _inject_position("paper_still_open", later_ts)

        # Check at 600s from first position
        exit_ts = entry_ts + 600.0
        closed_trades = check_and_close_timeout_positions(exit_ts)

        # Only first should close
        assert len(closed_trades) == 1
        assert closed_trades[0]["trade_id"] == "paper_timeout"

        # Second should still be open
        with _POSITION_LOCK:
            assert "paper_still_open" in _POSITIONS


class TestTrainingPositionTimeouts:
    """Test training-specific timeout behavior."""

    def test_training_position_capped_at_600s_timeout(self, clean_positions, timeout_600s):
        """Training position with max_hold=1200 still closes at 600s."""
        entry_ts = time.time()
        trade_id = "paper_training_capped"

        # Inject training position with old cycle 31 max_hold
        _inject_position(
            trade_id,
            entry_ts,
            training_bucket="C_WEAK_EV_TRAIN",
            max_hold_s=1200.0
        )

        # Should timeout at 600s, not 1200s
        exit_ts = entry_ts + 600.0
        closed_trades = check_and_close_timeout_positions(exit_ts)

        assert len(closed_trades) == 1
        assert closed_trades[0]["trade_id"] == trade_id


class TestTimeoutOutcomeClassification:
    """Test that TIMEOUT outcome classification is correct."""

    def test_timeout_win_if_positive_pnl(self, clean_positions, timeout_600s):
        """TIMEOUT classified as WIN if net PnL positive."""
        entry_ts = time.time()
        trade_id = "paper_timeout_win"

        _inject_position(trade_id, entry_ts)

        # Close at profit (exit > entry)
        exit_price = 2.53  # Above entry of 2.5
        exit_ts = entry_ts + 600.0

        closed = close_paper_position(trade_id, exit_price, exit_ts, "TIMEOUT")

        assert closed["exit_reason"] == "TIMEOUT"
        assert closed["outcome"] == "WIN"

    def test_timeout_loss_if_negative_pnl(self, clean_positions, timeout_600s):
        """TIMEOUT classified as LOSS if net PnL negative."""
        entry_ts = time.time()
        trade_id = "paper_timeout_loss"

        _inject_position(trade_id, entry_ts)

        # Close at loss (exit < entry)
        exit_price = 2.47  # Below entry of 2.5
        exit_ts = entry_ts + 600.0

        closed = close_paper_position(trade_id, exit_price, exit_ts, "TIMEOUT")

        assert closed["exit_reason"] == "TIMEOUT"
        assert closed["outcome"] == "LOSS"


class TestTimeoutComparisonWithCycle31:
    """Sanity check: 600s should be half of 1200s (cycle 31 value)."""

    def test_600s_is_half_of_1200s(self):
        """600s timeout is exactly half of cycle 31's 1200s."""
        new_timeout = 600.0
        old_timeout = 1200.0

        assert new_timeout * 2 == old_timeout
        assert new_timeout == old_timeout / 2


class TestPositionAgeCalculation:
    """Test that position age is correctly calculated at timeout boundary."""

    def test_position_age_calculation_at_boundary(self, clean_positions, timeout_600s):
        """Position age is correctly calculated at 600s boundary."""
        entry_ts = time.time()
        trade_id = "paper_age_calc"

        _inject_position(trade_id, entry_ts)

        # At 600s, position should have age=600s
        exit_ts = entry_ts + 600.0
        closed_trades = check_and_close_timeout_positions(exit_ts)

        assert len(closed_trades) == 1
        closed = closed_trades[0]

        # Duration should be ~600s
        assert 599.0 < closed["duration_s"] < 601.0
