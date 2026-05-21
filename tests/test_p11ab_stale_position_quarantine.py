"""
Regression tests for P1.1AB: Stale paper position quarantine guard.

Ensures:
- Stale/outlier paper positions are quarantined, not learned
- Normal paper training continues unaffected
- Quarantined positions are removed from open state
- Quarantine logs are generated
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.services.paper_trade_executor import (
    _is_stale_paper_position,
    close_paper_position,
    get_paper_open_positions,
    open_paper_position,
    _PAPER_MAX_PNL_PCT_TRAINING,
    _PAPER_MAX_PRICE_DEVIATION,
)


class TestStalePositionDetection:
    """Test stale position validation logic."""

    def test_stale_position_excessive_loss(self):
        """Position with >2% loss is detected as stale."""
        pnl_data = {"net_pnl_pct": -15.0}  # Way too large
        entry_price = 2500.0
        exit_price = 2128.0
        position = {"entry_price": entry_price}

        is_stale, reason = _is_stale_paper_position(pnl_data, entry_price, exit_price, position)
        assert is_stale, "Should detect excessive loss as stale"
        assert "excessive_pnl_pct" in reason

    def test_stale_position_excessive_gain(self):
        """Position with >2% gain is detected as stale."""
        pnl_data = {"net_pnl_pct": 5.0}  # Way too large
        entry_price = 100.0
        exit_price = 105.0
        position = {"entry_price": entry_price}

        is_stale, reason = _is_stale_paper_position(pnl_data, entry_price, exit_price, position)
        assert is_stale, "Should detect excessive gain as stale"
        assert "excessive_pnl_pct" in reason

    def test_stale_position_impossible_price_movement(self):
        """Position with 5%+ price deviation is detected as stale."""
        pnl_data = {"net_pnl_pct": -0.15}  # Reasonable loss
        entry_price = 2500.0
        exit_price = 2128.0  # 15% below entry = stale data
        position = {"entry_price": entry_price}

        is_stale, reason = _is_stale_paper_position(pnl_data, entry_price, exit_price, position)
        assert is_stale, "Should detect impossible price movement"
        assert "impossible_price_deviation" in reason

    def test_normal_position_small_loss(self):
        """Normal position with <0.5% loss is not stale."""
        pnl_data = {"net_pnl_pct": -0.174}  # Small, realistic loss
        entry_price = 2128.0
        exit_price = 2126.3
        position = {"entry_price": entry_price}

        is_stale, reason = _is_stale_paper_position(pnl_data, entry_price, exit_price, position)
        assert not is_stale, "Should not detect normal loss as stale"
        assert reason == ""

    def test_normal_position_small_gain(self):
        """Normal position with <0.5% gain is not stale."""
        pnl_data = {"net_pnl_pct": 0.2}  # Small, realistic gain
        entry_price = 2128.0
        exit_price = 2132.3
        position = {"entry_price": entry_price}

        is_stale, reason = _is_stale_paper_position(pnl_data, entry_price, exit_price, position)
        assert not is_stale, "Should not detect normal gain as stale"
        assert reason == ""

    def test_threshold_boundary_at_max_pnl(self):
        """Position at exactly 2.0% loss is not stale."""
        pnl_data = {"net_pnl_pct": -2.0}  # Exactly at threshold
        entry_price = 100.0
        exit_price = 98.0
        position = {"entry_price": entry_price}

        is_stale, reason = _is_stale_paper_position(pnl_data, entry_price, exit_price, position)
        assert not is_stale, "Should allow exactly 2.0%"

    def test_threshold_boundary_above_max_pnl(self):
        """Position at 2.01% loss is stale."""
        pnl_data = {"net_pnl_pct": -2.01}  # Just above threshold
        entry_price = 100.0
        exit_price = 97.99
        position = {"entry_price": entry_price}

        is_stale, reason = _is_stale_paper_position(pnl_data, entry_price, exit_price, position)
        assert is_stale, "Should detect just above 2.0% as stale"


class TestQuarantineInClosePosition:
    """Test quarantine behavior when closing positions."""

    @patch("src.services.paper_trade_executor._safe_learning_update_for_paper_trade")
    @patch("src.services.paper_trade_executor._safe_bucket_metrics_update_for_paper_trade")
    @patch("src.services.paper_trade_executor.log")
    def test_stale_position_quarantined_not_learned(
        self, mock_log, mock_metrics, mock_learning
    ):
        """Stale position is quarantined and NOT sent to learning."""
        # Setup: open a position
        signal = {
            "symbol": "ETHUSDT",
            "side": "BUY",
            "ev": 0.01,
            "score": 0.5,
        }
        extra = {
            "paper_source": "training_sampler",
            "training_bucket": "C_WEAK_EV_TRAIN",
        }
        pos = open_paper_position(
            signal=signal,
            price=2500.0,
            ts=1700000000.0,
            extra=extra,
        )

        assert pos is not None, "Position should open"
        trade_id = pos["trade_id"]
        entry_ts = 1700000000.0

        # Close with stale data (huge loss)
        closed_trade = close_paper_position(
            position_id=trade_id,
            price=2128.0,  # 15% drop = stale data
            ts=entry_ts + 60,
            reason="TIMEOUT",
        )

        # Verify quarantine log emitted
        assert mock_log.warning.called
        warning_calls = [call for call in mock_log.warning.call_args_list
                        if "[PAPER_POSITION_QUARANTINED]" in str(call)]
        assert len(warning_calls) > 0, "Should log quarantine"

        # Verify NO quality/econ logs emitted (only quarantine log should be there)
        quality_calls = [call for call in mock_log.info.call_args_list
                        if "[PAPER_TRAIN_QUALITY_EXIT]" in str(call)]
        assert len(quality_calls) == 0, "Should NOT emit quality exit for stale position"

        econ_calls = [call for call in mock_log.info.call_args_list
                      if "[PAPER_TRAIN_ECON_ATTRIB]" in str(call)]
        assert len(econ_calls) == 0, "Should NOT emit econ attribution for stale position"

        # Verify learning NOT called
        assert not mock_learning.called, "Quarantined position should NOT be sent to learning"

        # Verify position was closed and removed
        assert closed_trade is not None
        open_positions = get_paper_open_positions()
        assert len(open_positions) == 0, "Position should be removed from open state"

    @patch("src.services.paper_trade_executor._safe_learning_update_for_paper_trade")
    @patch("src.services.paper_trade_executor._safe_bucket_metrics_update_for_paper_trade")
    @patch("src.services.paper_trade_executor.log")
    def test_normal_position_learned(self, mock_log, mock_metrics, mock_learning):
        """Normal position is NOT quarantined and IS sent to learning with quality logs."""
        # Setup: open a position
        signal = {
            "symbol": "ETHUSDT",
            "side": "BUY",
            "ev": 0.01,
            "score": 0.5,
        }
        extra = {
            "paper_source": "training_sampler",
            "training_bucket": "C_WEAK_EV_TRAIN",
        }
        pos = open_paper_position(
            signal=signal,
            price=2128.0,
            ts=1700000000.0,
            extra=extra,
        )

        assert pos is not None, "Position should open"
        trade_id = pos["trade_id"]
        entry_ts = 1700000000.0

        # Close with normal data (small loss: -0.094%)
        closed_trade = close_paper_position(
            position_id=trade_id,
            price=2126.0,  # 0.094% loss = normal
            ts=entry_ts + 60,
            reason="TP",
        )

        # Verify quality logs ARE emitted
        quality_calls = [call for call in mock_log.info.call_args_list
                        if "[PAPER_TRAIN_QUALITY_EXIT]" in str(call)]
        assert len(quality_calls) > 0, "Normal position should emit quality exit log"

        # Verify econ logs ARE emitted
        econ_calls = [call for call in mock_log.info.call_args_list
                      if "[PAPER_TRAIN_ECON_ATTRIB]" in str(call)]
        assert len(econ_calls) > 0, "Normal position should emit econ attribution log"

        # Verify learning IS called
        assert mock_learning.called, "Normal position should be sent to learning"
        assert closed_trade is not None

    @patch("src.services.paper_trade_executor._safe_learning_update_for_paper_trade")
    @patch("src.services.paper_trade_executor._safe_bucket_metrics_update_for_paper_trade")
    def test_quarantine_removes_from_open_state(self, mock_metrics, mock_learning):
        """Quarantined position is removed from open positions."""
        # Open two positions
        signal1 = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "ev": 0.01,
            "score": 0.5,
        }
        extra1 = {
            "paper_source": "training_sampler",
            "training_bucket": "C_WEAK_EV_TRAIN",
        }
        pos1 = open_paper_position(
            signal=signal1,
            price=42000.0,
            ts=1700000000.0,
            extra=extra1,
        )
        trade_id_1 = pos1["trade_id"]

        signal2 = {
            "symbol": "ETHUSDT",
            "side": "BUY",
            "ev": 0.01,
            "score": 0.5,
        }
        extra2 = {
            "paper_source": "training_sampler",
            "training_bucket": "C_WEAK_EV_TRAIN",
        }
        pos2 = open_paper_position(
            signal=signal2,
            price=2500.0,
            ts=1700000060.0,
            extra=extra2,
        )
        trade_id_2 = pos2["trade_id"]

        assert len(get_paper_open_positions()) == 2

        # Close stale position (the second one with 15% drop)
        close_paper_position(
            position_id=trade_id_2,
            price=2128.0,  # Stale data (15% drop)
            ts=1700000060.0 + 60,
            reason="TIMEOUT",
        )

        # Verify only one position remains
        remaining = get_paper_open_positions()
        assert len(remaining) == 1, "Stale position should be removed"
        assert remaining[0]["trade_id"] == trade_id_1, "Normal position should remain"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
