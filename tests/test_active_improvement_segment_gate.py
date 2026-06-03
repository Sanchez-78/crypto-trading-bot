"""Tests for segment profitability gating with confidence-aware logic."""

import pytest
from unittest.mock import MagicMock, patch


def test_low_n_segment_always_allowed():
    """Segment with n < 20 should always be ALLOW, no block."""
    from src.services.paper_trade_executor import _get_segment_pf

    with patch("src.services.paper_trade_executor._get_learner_state") as mock_learner:
        mock_learner.return_value = MagicMock(rolling100=[])
        pf, n, expectancy = _get_segment_pf("BTCUSDT", "BULL_TREND", "BUY")

        assert n == 0, "Low sample count should return n=0"
        assert pf == 1.0, "Default PF should be 1.0 for no data"


def test_medium_n_segment_size_down():
    """Segment with 20 <= n < 50 should SIZE_DOWN, not block."""
    from src.services.paper_trade_executor import _should_skip_segment_by_profitability

    with patch("src.services.paper_trade_executor._get_segment_pf") as mock_pf:
        mock_pf.return_value = (0.50, 30, -0.05)  # Bad PF but medium n
        should_block, reason, action = _should_skip_segment_by_profitability("BTCUSDT", "BULL", "BUY")

        assert not should_block, "Medium n should not hard-block"
        assert action == "SIZE_DOWN", "Medium n should SIZE_DOWN"


def test_high_n_segment_blocks_if_enabled():
    """Segment with n >= 50, PF < 0.70, and negative expectancy should BLOCK if hard_block_enabled."""
    from src.services.paper_trade_executor import _should_skip_segment_by_profitability

    with patch("src.services.paper_trade_executor._get_segment_pf") as mock_pf:
        with patch("os.getenv") as mock_env:
            mock_pf.return_value = (0.60, 60, -0.10)  # Bad PF, high n, negative exp
            mock_env.side_effect = lambda k, default: {
                "PAPER_SEGMENT_HARD_BLOCK_MIN_N": "50",
                "PAPER_SEGMENT_HARD_BLOCK_ENABLED": "true",
            }.get(k, default)

            should_block, reason, action = _should_skip_segment_by_profitability(
                "BTCUSDT", "BULL", "BUY"
            )

            assert should_block, "High n + bad PF + hard_block_enabled should BLOCK"
            assert action == "BLOCK"


def test_hard_block_disabled_by_default():
    """Hard block should be disabled by default, only SIZE_DOWN."""
    from src.services.paper_trade_executor import _should_skip_segment_by_profitability

    with patch("src.services.paper_trade_executor._get_segment_pf") as mock_pf:
        with patch("os.getenv") as mock_env:
            mock_pf.return_value = (0.50, 60, -0.10)
            mock_env.side_effect = lambda k, default: {
                "PAPER_SEGMENT_HARD_BLOCK_MIN_N": "50",
                "PAPER_SEGMENT_HARD_BLOCK_ENABLED": "false",  # Default: disabled
            }.get(k, default)

            should_block, reason, action = _should_skip_segment_by_profitability(
                "BTCUSDT", "BULL", "BUY"
            )

            assert not should_block, "Hard block disabled should not block"
            assert action == "ALLOW"
