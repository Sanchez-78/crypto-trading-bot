"""Tests for time-of-day filtering in shadow mode."""

import pytest
from unittest.mock import patch


def test_time_filter_shadow_by_default():
    """Time filter should be shadow mode by default (no live effect)."""
    from src.services.paper_trade_executor import _should_skip_time_of_day

    should_skip, reason, is_shadow = _should_skip_time_of_day()

    assert not should_skip, "Shadow mode should not trigger skip"
    assert is_shadow, "Should be in shadow mode by default"
