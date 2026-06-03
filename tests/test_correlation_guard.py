"""Tests for correlation guard."""

import pytest
from unittest.mock import patch


def test_no_conflict_when_no_open_positions():
    """Should ALLOW when no open positions."""
    from src.services.correlation_guard import check_correlation_conflict

    open_positions = {}
    should_action, reason, action = check_correlation_conflict("BTCUSDT", open_positions)

    assert not should_action, "No conflict when empty"
    assert action == "ALLOW"


def test_guard_detects_correlated_pair():
    """Should SIZE_DOWN when open symbol is highly correlated."""
    from src.services.correlation_guard import check_correlation_conflict

    open_positions = {
        "pos1": {"symbol": "BTCUSDT"}
    }

    with patch("os.getenv") as mock_env:
        mock_env.side_effect = lambda k, default: {
            "PAPER_CORRELATION_GUARD_ENABLED": "true",
            "PAPER_CORRELATION_THRESHOLD": "0.80",
            "PAPER_CORRELATION_HARD_BLOCK": "false",
        }.get(k, default)

        # ETHUSDT is correlated with BTCUSDT (0.85)
        should_action, reason, action = check_correlation_conflict("ETHUSDT", open_positions)

        assert should_action, "Should detect correlation"
        assert action == "SIZE_DOWN", "Should SIZE_DOWN when hard_block disabled"


def test_hard_block_when_enabled():
    """Should BLOCK when hard_block is enabled and correlation detected."""
    from src.services.correlation_guard import check_correlation_conflict

    open_positions = {
        "pos1": {"symbol": "BTCUSDT"}
    }

    with patch("os.getenv") as mock_env:
        mock_env.side_effect = lambda k, default: {
            "PAPER_CORRELATION_GUARD_ENABLED": "true",
            "PAPER_CORRELATION_THRESHOLD": "0.80",
            "PAPER_CORRELATION_HARD_BLOCK": "true",  # Enabled
        }.get(k, default)

        should_action, reason, action = check_correlation_conflict("ETHUSDT", open_positions)

        assert should_action, "Should detect correlation"
        assert action == "BLOCK", "Should BLOCK when hard_block enabled"


def test_guard_disabled():
    """Guard should be disabled by default."""
    from src.services.correlation_guard import check_correlation_conflict

    open_positions = {
        "pos1": {"symbol": "BTCUSDT"}
    }

    with patch("os.getenv") as mock_env:
        mock_env.side_effect = lambda k, default: {
            "PAPER_CORRELATION_GUARD_ENABLED": "false",  # Disabled
            "PAPER_CORRELATION_THRESHOLD": "0.80",
            "PAPER_CORRELATION_HARD_BLOCK": "false",
        }.get(k, default)

        should_action, reason, action = check_correlation_conflict("ETHUSDT", open_positions)

        assert not should_action, "Should not trigger when disabled"
        assert action == "ALLOW"
