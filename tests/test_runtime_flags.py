"""Regression tests for truthful Firebase degradation status in paper mode."""

from src.services import runtime_flags


def test_dashboard_reports_local_archive_without_blocking_paper(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper_train")
    monkeypatch.setenv("ENABLE_REAL_ORDERS", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMED", "false")
    monkeypatch.setenv("REAL_TRADING_ENABLED", "false")
    runtime_flags.set_db_degraded_safe_mode(True, "quota_429")
    try:
        status = runtime_flags.get_dashboard_status()
        assert status["state"] == "PAPER_TRAIN_LOCAL_ARCHIVE"
        assert status["entries"] == "paper_enabled"
        assert runtime_flags.should_skip_entry("ETHUSDT") == (False, "")
    finally:
        runtime_flags.set_db_degraded_safe_mode(False, None)


def test_dashboard_keeps_fail_closed_status_for_real_mode(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "real")
    monkeypatch.setenv("ENABLE_REAL_ORDERS", "true")
    runtime_flags.set_db_degraded_safe_mode(True, "quota_429")
    try:
        status = runtime_flags.get_dashboard_status()
        assert status["state"] == "SAFE_MODE_FIREBASE_DEGRADED"
        assert status["entries"] == "blocked"
        assert runtime_flags.should_skip_entry("ETHUSDT")[0] is True
    finally:
        runtime_flags.set_db_degraded_safe_mode(False, None)
