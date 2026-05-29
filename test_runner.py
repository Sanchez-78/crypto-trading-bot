#!/usr/bin/env python3
"""Direct pytest runner."""
import sys
import pytest

sys.exit(pytest.main([
    'tests/v5_bot/test_quota_guard.py',
    'tests/v5_bot/test_outbox.py',
    'tests/v5_bot/test_learning.py',
    'tests/v5_bot/test_strategy.py',
    'tests/v5_bot/test_futures_feed.py',
    'tests/v5_bot/test_paper_lifecycle.py',
    '-v', '--tb=line', '--color=no'
]))
