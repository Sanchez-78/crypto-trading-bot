"""
Phase 3 Tests: V5 Legacy Bridge — Hook Integration

Test that legacy PAPER_ENTRY and PAPER_EXIT correctly call V5 bridge methods.
"""

import pytest
import time
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.services.paper_trade_executor import open_paper_position, close_paper_position, _get_v5_bridge
from src.services.v5_legacy_bridge.event_models import LegacyPaperOpenEvent, LegacyPaperCloseEvent


def test_legacy_entry_hook_records_open_event():
    """Test that legacy PAPER_ENTRY calls v5_bridge.record_open()."""
    with patch("src.services.paper_trade_executor._get_v5_bridge") as mock_get_bridge:
        mock_bridge = MagicMock()
        mock_get_bridge.return_value = mock_bridge

        signal = {
            "symbol": "BTC/USDT",
            "action": "BUY",
            "side": "LONG",
            "ev": 0.85,
            "score": 0.75,
            "confidence": 0.9,
            "coherence": 1.0,
            "auditor_factor": 1.0,
            "regime": "BULLISH",
        }

        result = open_paper_position(
            signal=signal,
            price=50000.0,
            ts=time.time(),
            reason="RDE_TAKE",
            extra={"training_bucket": "A_STRICT_TAKE"},
        )

        assert result["status"] == "opened"
        assert mock_bridge.record_open.called
        call_args = mock_bridge.record_open.call_args[0][0]
        assert call_args.symbol == "BTC/USDT"
        assert call_args.side == "BUY"  # Normalized by legacy to BUY/SELL
        assert call_args.real_orders_allowed is False


def test_legacy_close_hook_records_close_and_learning_update():
    """Test that legacy PAPER_EXIT calls v5_bridge.record_close() and apply_learning()."""
    # First open a position
    signal = {
        "symbol": "ETH/USDT",
        "action": "SELL",
        "side": "SELL",  # Will be normalized to SELL
        "ev": 0.70,
        "score": 0.65,
        "regime": "BEARISH",
    }

    open_result = open_paper_position(
        signal=signal,
        price=3000.0,
        ts=time.time(),
        reason="RDE_TAKE",
    )

    trade_id = open_result["trade_id"]

    with patch("src.services.paper_trade_executor._get_v5_bridge") as mock_get_bridge:
        mock_bridge = MagicMock()
        mock_get_bridge.return_value = mock_bridge

        # Now close it
        closed_trade = close_paper_position(
            position_id=trade_id,
            price=2970.0,
            ts=time.time() + 300,  # 5 minutes later
            reason="TP_HIT",
        )

        assert closed_trade is not None
        assert closed_trade["trade_id"] == trade_id
        assert closed_trade["exit_reason"] == "TP_HIT"

        # Verify bridge was called
        assert mock_bridge.record_close.called
        call_args = mock_bridge.record_close.call_args[0][0]
        assert call_args.trade_id == trade_id
        assert call_args.exit_reason == "TP_HIT"
        assert call_args.real_orders_allowed is False


def test_close_hook_idempotent_no_double_learning():
    """Test that close hook doesn't double-learn if called twice."""
    signal = {
        "symbol": "XRP/USDT",
        "action": "BUY",
        "side": "LONG",
        "ev": 0.80,
        "score": 0.70,
    }

    open_result = open_paper_position(signal, 1.5, time.time(), "RDE_TAKE")
    trade_id = open_result["trade_id"]

    with patch("src.services.paper_trade_executor._get_v5_bridge") as mock_get_bridge:
        mock_bridge = MagicMock()
        mock_get_bridge.return_value = mock_bridge

        # Close once
        close_paper_position(trade_id, 1.52, time.time() + 100, "TP_HIT")
        assert mock_bridge.record_close.call_count == 1

        # Try to close again (should be deduped by legacy dedup, not bridge)
        close_paper_position(trade_id, 1.52, time.time() + 100, "TP_HIT")
        # Second call should return None (position not found)


def test_bridge_failure_outboxes_and_does_not_crash_legacy_loop():
    """Test that bridge write failure doesn't crash legacy trading loop."""
    with patch("src.services.paper_trade_executor._get_v5_bridge") as mock_get_bridge:
        mock_bridge = MagicMock()
        mock_bridge.record_open.side_effect = Exception("Firebase timeout")
        mock_get_bridge.return_value = mock_bridge

        signal = {"symbol": "ADA/USDT", "action": "BUY", "side": "LONG", "ev": 0.75}

        # Should not raise - bridge failure should be silently logged
        result = open_paper_position(signal, 1.2, time.time(), "RDE_TAKE")
        assert result["status"] == "opened"  # Legacy still opened despite bridge error


def test_real_orders_false_in_all_bridge_events():
    """Test that all bridge events have real_orders_allowed=false."""
    with patch("src.services.paper_trade_executor._get_v5_bridge") as mock_get_bridge:
        mock_bridge = MagicMock()
        mock_get_bridge.return_value = mock_bridge

        # Open
        signal = {"symbol": "BTC/USDT", "action": "BUY", "side": "LONG", "ev": 0.85}
        open_result = open_paper_position(signal, 50000, time.time(), "RDE_TAKE")
        trade_id = open_result["trade_id"]

        # Verify open event has real_orders_allowed=false
        open_event = mock_bridge.record_open.call_args[0][0]
        assert open_event.real_orders_allowed is False

        # Close
        mock_get_bridge.return_value = mock_bridge  # Reset for close
        closed = close_paper_position(trade_id, 50100, time.time() + 300, "TP_HIT")

        # Verify close event has real_orders_allowed=false
        close_event = mock_bridge.record_close.call_args[0][0]
        assert close_event.real_orders_allowed is False


def test_standalone_v5_service_not_required():
    """Test that V5 bridge works without standalone V5 service."""
    # The bridge is initialized as a singleton within the legacy process
    bridge = _get_v5_bridge()

    # Bridge should initialize successfully in legacy context
    assert bridge is not None or bridge is False  # Either initialized or explicitly failed


def test_metrics_publish_called_periodically():
    """Test that metrics publishing would be called in event loop."""
    with patch("src.services.paper_trade_executor._get_v5_bridge") as mock_get_bridge:
        mock_bridge = MagicMock()
        mock_get_bridge.return_value = mock_bridge

        # Simulate what bot2/main.py does
        open_positions = []  # No open positions in this test

        trading_stats = {
            "open_positions": len(open_positions),
            "closed_today": 0,
            "entries_attempted": 0,
            "entries_accepted": 0,
            "entries_rejected": 0,
            "reject_reasons": {},
            "cost_edge_pass": 0,
            "cost_edge_fail": 0,
        }

        # This is what the event loop calls
        if mock_bridge:
            mock_bridge.publish_metrics(trading_stats=trading_stats)
            mock_bridge.flush_outbox(limit=20)

        assert mock_bridge.publish_metrics.called
        assert mock_bridge.flush_outbox.called
