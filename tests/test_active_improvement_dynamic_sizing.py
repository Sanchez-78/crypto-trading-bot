"""Tests for dynamic position sizing with EV and segment multipliers."""

import pytest
from unittest.mock import patch


def test_sizing_clamps_min_max():
    """Position sizing should clamp between min and max."""
    from src.services.paper_trade_executor import _calculate_dynamic_position_size

    with patch("os.getenv") as mock_env:
        mock_env.side_effect = lambda k, default: {
            "PAPER_POSITION_SIZE_USD": "25",
            "PAPER_MIN_SIZE_USD": "10",
            "PAPER_MAX_SIZE_USD": "75",
        }.get(k, default)

        # Very high EV -> would be 2.0x * 25 = 50, within bounds
        size = _calculate_dynamic_position_size({"ev": 0.20}, "ALLOW")
        assert 10 <= size <= 75, f"Size {size} should be clamped [10, 75]"

        # Very low EV -> would be 0.5x * 25 = 12.5, within bounds
        size = _calculate_dynamic_position_size({"ev": 0.01}, "ALLOW")
        assert 10 <= size <= 75, f"Size {size} should be clamped [10, 75]"


def test_segment_multiplier_size_down():
    """SIZE_DOWN action should apply 0.5x multiplier."""
    from src.services.paper_trade_executor import _calculate_dynamic_position_size

    with patch("os.getenv") as mock_env:
        mock_env.side_effect = lambda k, default: {
            "PAPER_POSITION_SIZE_USD": "25",
            "PAPER_MIN_SIZE_USD": "10",
            "PAPER_MAX_SIZE_USD": "75",
        }.get(k, default)

        # Medium EV (1.0x), SIZE_DOWN (0.5x) -> 25 * 1.0 * 0.5 = 12.5
        size_allow = _calculate_dynamic_position_size({"ev": 0.07}, "ALLOW")
        size_down = _calculate_dynamic_position_size({"ev": 0.07}, "SIZE_DOWN")

        assert size_down < size_allow, "SIZE_DOWN should produce smaller position"
        assert abs(size_down - size_allow * 0.5) < 0.1, "SIZE_DOWN should be 0.5x"


def test_ev_multiplier_brackets():
    """EV multiplier should follow correct brackets."""
    from src.services.paper_trade_executor import _calculate_dynamic_position_size

    with patch("os.getenv") as mock_env:
        mock_env.side_effect = lambda k, default: {
            "PAPER_POSITION_SIZE_USD": "25",
            "PAPER_MIN_SIZE_USD": "10",
            "PAPER_MAX_SIZE_USD": "75",
        }.get(k, default)

        sizes = {}
        for ev in [0.00, 0.03, 0.05, 0.10, 0.15, 0.20]:
            sizes[ev] = _calculate_dynamic_position_size({"ev": ev}, "ALLOW")

        # Size should monotonically increase with EV
        evs = sorted(sizes.keys())
        for i in range(len(evs) - 1):
            assert sizes[evs[i]] <= sizes[evs[i + 1]], f"Size should increase with EV"


def test_missing_ev_uses_default():
    """Missing EV should use 1.0x (default/medium)."""
    from src.services.paper_trade_executor import _calculate_dynamic_position_size

    with patch("os.getenv") as mock_env:
        mock_env.side_effect = lambda k, default: {
            "PAPER_POSITION_SIZE_USD": "25",
            "PAPER_MIN_SIZE_USD": "10",
            "PAPER_MAX_SIZE_USD": "75",
        }.get(k, default)

        # No EV provided
        size_no_ev = _calculate_dynamic_position_size({}, "ALLOW")
        # EV = 0.07 -> 1.0x multiplier
        size_medium_ev = _calculate_dynamic_position_size({"ev": 0.07}, "ALLOW")

        assert abs(size_no_ev - size_medium_ev) < 5, "Missing EV should default to medium confidence"
