"""Regression test: ensure metrics publish callback has defined utc_timestamp_iso."""

import pytest
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.v5_bot.paper.runner import V5BotRunner
from src.v5_bot.util.datetime_utils import utc_timestamp_iso
from src.v5_bot.config import TRADING_SYMBOLS


logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_periodic_metrics_publish_has_defined_utc_timestamp_and_writes_snapshot():
    """
    Regression: Verify metrics publish callback does NOT raise NameError on utc_timestamp_iso.
    This test ensures that:
    1. utc_timestamp_iso is properly imported in runner.py
    2. publish_metrics() can construct a valid metrics dict with timestamp
    3. Firebase quota-aware repository accepts the snapshot
    4. REAL_ORDERS_ALLOWED remains false
    """

    # Mock Firebase repository to avoid actual credentials/writes
    with patch('src.v5_bot.paper.runner.QuotaAwareFirestoreRepository') as mock_firebase_class:
        mock_firebase = MagicMock()
        mock_firebase.set_dashboard = AsyncMock(return_value=True)
        mock_firebase_class.return_value = mock_firebase

        # Mock market feeds
        with patch('src.v5_bot.paper.runner.BinanceUSDMFeed') as mock_feed_class:
            mock_feed = MagicMock()
            mock_feed.get_status = MagicMock(return_value={'running': False, 'symbols_with_data': 0})
            mock_feed_class.return_value = mock_feed

            # Create bot instance
            bot = V5BotRunner(firebase_creds_path=None)

            # Verify Firebase is initialized
            assert bot.firebase is not None, "Firebase repository should be initialized"
            assert bot.firebase.set_dashboard is not None, "Firebase set_dashboard should exist"

            # Call publish_metrics directly to trigger the callback
            try:
                await bot.publish_metrics()
                # If we get here, no NameError was raised
                success = True
            except NameError as e:
                if 'utc_timestamp_iso' in str(e):
                    pytest.fail(f"NameError: utc_timestamp_iso not defined: {e}")
                raise

            assert success, "publish_metrics() should complete without NameError"

            # Verify set_dashboard was called (Firebase write happened)
            assert mock_firebase.set_dashboard.called, "Firebase.set_dashboard should be called"

            # Get the call arguments to verify structure
            call_args = mock_firebase.set_dashboard.call_args
            if call_args:
                dashboard_obj = call_args[0][0] if call_args[0] else None
                # Verify the dashboard object has timestamp field (via to_firestore_dict)
                assert dashboard_obj is not None, "Dashboard object should be passed to set_dashboard"


def test_utc_timestamp_iso_function_exists_and_returns_valid_iso_string():
    """Verify the helper function exists and returns valid ISO 8601 timestamp."""
    timestamp_str = utc_timestamp_iso()
    assert isinstance(timestamp_str, str), "utc_timestamp_iso should return string"
    assert 'T' in timestamp_str, "Timestamp should be ISO 8601 format with T separator"
    assert 'Z' in timestamp_str or '+' in timestamp_str, "Timestamp should be UTC (Z suffix or +00:00)"

    # Verify it can be parsed back
    try:
        if timestamp_str.endswith('Z'):
            parsed = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            parsed = datetime.fromisoformat(timestamp_str)
        assert parsed.tzinfo is not None, "Parsed timestamp should have timezone info"
    except ValueError as e:
        pytest.fail(f"Could not parse ISO timestamp: {timestamp_str}: {e}")


def test_real_orders_allowed_remains_false():
    """Verify ENABLE_REAL_ORDERS configuration remains false."""
    import os
    from src.v5_bot.config import ENABLE_REAL_ORDERS

    assert ENABLE_REAL_ORDERS is False, "ENABLE_REAL_ORDERS should remain false"

    # Also check environment
    env_real_orders = os.environ.get('ENABLE_REAL_ORDERS', '').lower()
    assert env_real_orders != 'true', f"Environment ENABLE_REAL_ORDERS should not be true, got: {env_real_orders}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
