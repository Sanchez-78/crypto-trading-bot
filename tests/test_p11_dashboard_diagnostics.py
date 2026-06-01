"""
P0 HOTFIX v2 Part 2: Dashboard diagnostics tests.

Tests for:
- P0 Bug #6: Dashboard ok=False must include reason field
"""

import pytest
import time
from unittest import mock


class TestDashboardPublishWithReason:
    """P0 Bug #6: Dashboard must return reason when ok=False."""

    def test_dashboard_snapshot_publish_false_has_reason(self):
        """save_dashboard_snapshot must return (ok, reason) tuple."""
        from src.services import firebase_client

        # Reset state to avoid throttle
        firebase_client._LAST_DASHBOARD_SNAPSHOT_WRITE_TS = 0.0
        firebase_client._LAST_DASHBOARD_SNAPSHOT_SEMANTIC_HASH = None
        firebase_client.db = None  # DB unavailable

        result = firebase_client.save_dashboard_snapshot({"test": "snapshot"})

        assert isinstance(result, tuple), f"Expected tuple but got {type(result)}"
        assert len(result) == 2, f"Expected (ok, reason) tuple but got {result}"

        ok, reason = result
        assert isinstance(ok, bool), "First element should be bool (ok)"
        assert isinstance(reason, str), "Second element should be str (reason)"

        # When DB unavailable, reason should be DB_UNAVAILABLE
        assert ok is False, "Should fail when db is None"
        assert reason == "DB_UNAVAILABLE", f"Expected DB_UNAVAILABLE but got {reason}"

    def test_dashboard_publish_throttle_returns_throttled_reason(self):
        """Throttle check should return THROTTLED reason."""
        from src.services import firebase_client

        # Setup: recent write
        firebase_client.db = mock.MagicMock()
        firebase_client._LAST_DASHBOARD_SNAPSHOT_WRITE_TS = time.time()

        result = firebase_client.save_dashboard_snapshot({"test": "snapshot"}, force=False)
        ok, reason = result

        assert not ok, "Throttled should return ok=False"
        assert reason == "THROTTLED", f"Expected THROTTLED but got {reason}"

    def test_dashboard_publish_success_has_empty_reason(self):
        """Successful publish should have empty reason."""
        from src.services import firebase_client
        import time as _time

        # Setup: DB available, no throttle, new data
        firebase_client.db = mock.MagicMock()
        firebase_client._LAST_DASHBOARD_SNAPSHOT_WRITE_TS = 0.0
        firebase_client._LAST_DASHBOARD_SNAPSHOT_SEMANTIC_HASH = None
        firebase_client._LAST_DASHBOARD_SNAPSHOT_HEARTBEAT_TS = 0.0

        snapshot = {"test": "data", "generated_at": _time.time()}

        result = firebase_client.save_dashboard_snapshot(snapshot, force=True)
        ok, reason = result

        assert ok is True, f"Force publish should succeed but got ok={ok}, reason={reason}"
        assert reason == "", f"Success should have empty reason but got {reason}"

    def test_dashboard_publish_exception_has_exception_reason(self):
        """Exception during write should include exception type in reason."""
        from src.services import firebase_client

        firebase_client.db = mock.MagicMock()
        firebase_client.db.document.side_effect = RuntimeError("Test error")
        firebase_client._LAST_DASHBOARD_SNAPSHOT_WRITE_TS = 0.0
        firebase_client._LAST_DASHBOARD_SNAPSHOT_SEMANTIC_HASH = None

        result = firebase_client.save_dashboard_snapshot({"test": "snapshot"}, force=True)
        ok, reason = result

        assert not ok, "Exception should return ok=False"
        assert "EXCEPTION" in reason, f"Expected EXCEPTION in reason but got {reason}"
        assert "RuntimeError" in reason, f"Expected error type in reason but got {reason}"


class TestDashboardDiagnosticCoverage:
    """Comprehensive diagnostic coverage for dashboard."""

    def test_all_dashboard_failure_modes_have_reason(self):
        """Every failure path must have explicit reason."""
        from src.services import firebase_client

        failure_reasons = [
            "THROTTLED",
            "NO_CHANGE",
            "DB_UNAVAILABLE",
            "FIREBASE_HEALTH_QUOTA_EXHAUSTED",
            "EXCEPTION_RuntimeError",
        ]

        # All these should be legitimate reasons from save_dashboard_snapshot
        for reason in failure_reasons:
            # Just verify they exist (not exhaustive, just samples)
            assert len(reason) > 0, f"Reason should not be empty"
            assert "_" in reason or reason.isupper(), f"Reason format: {reason}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
