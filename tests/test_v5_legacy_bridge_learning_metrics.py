"""
Phase 2 Tests: V5 Legacy Bridge — Learning and Metrics

Test learning updates, readiness determination, and metrics publishing.
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.services.v5_legacy_bridge.event_models import LegacyPaperCloseEvent
from src.services.v5_legacy_bridge.learning_bridge import V5LearningBridge
from src.services.v5_legacy_bridge.metrics_publisher import V5MetricsPublisher
from src.services.v5_legacy_bridge import config


def create_close_event(
    trade_id="trade_123",
    symbol="BTC/USDT",
    side="LONG",
    net_pnl=100.0,
    net_pnl_pct=0.02,
    exit_reason="tp_hit",
    learning_eligible=True,
    real_orders_allowed=False,
    entry_price=50000,
    exit_price=50100,
    gross_pnl=150.0,
    fees=50.0,
    spread=0,
) -> LegacyPaperCloseEvent:
    """Helper to create close event."""
    return LegacyPaperCloseEvent(
        trade_id=trade_id,
        symbol=symbol,
        side=side,
        exit_ts=datetime.utcnow().isoformat(),
        exit_price=exit_price,
        exit_reason=exit_reason,
        gross_pnl=gross_pnl,
        fees=fees,
        spread=spread,
        net_pnl=net_pnl,
        net_pnl_pct=net_pnl_pct,
        duration_seconds=3600,
        learning_eligible=learning_eligible,
        readiness_eligible=False,
        real_orders_allowed=real_orders_allowed,
        metadata={},
    )


def test_learning_update_real_orders_false():
    """Test that learning updates enforce real_orders_allowed=false."""
    bridge = V5LearningBridge()

    close_event = create_close_event(real_orders_allowed=False)
    update = bridge.apply_learning_from_close(close_event)

    assert "error" not in update
    assert update["real_orders_allowed"] is False
    assert update["source"] == "legacy_v5_bridge"


def test_learning_update_fails_if_real_orders_true():
    """Test that learning updates reject real_orders_allowed=true."""
    bridge = V5LearningBridge()

    close_event = create_close_event(real_orders_allowed=True)
    update = bridge.apply_learning_from_close(close_event)

    assert "error" in update
    assert update["error"] == "REAL_ORDERS_NOT_ALLOWED"


def test_learning_update_includes_required_fields():
    """Test that learning update includes all required fields."""
    bridge = V5LearningBridge()

    close_event = create_close_event()
    update = bridge.build_learning_update(close_event)

    required_fields = [
        "trade_id",
        "symbol",
        "side",
        "regime",
        "exit_reason",
        "gross_pnl",
        "fees",
        "spread",
        "net_pnl",
        "net_pnl_pct",
        "learning_eligible",
        "readiness_eligible",
        "source",
        "real_orders_allowed",
        "timestamp",
    ]

    for field in required_fields:
        assert field in update, f"Missing field: {field}"


def test_learning_determines_readiness_eligible():
    """Test that readiness eligibility is determined correctly."""
    bridge = V5LearningBridge()

    # Profitable, learning eligible
    close_event = create_close_event(
        net_pnl_pct=0.02,
        exit_reason="tp_hit",
        learning_eligible=True,
    )
    update = bridge.build_learning_update(close_event)
    assert update["readiness_eligible"] is True

    # Not profitable
    close_event = create_close_event(
        net_pnl_pct=-0.01,
        exit_reason="sl_hit",
        learning_eligible=True,
    )
    update = bridge.build_learning_update(close_event)
    assert update["readiness_eligible"] is False

    # Not learning eligible
    close_event = create_close_event(
        net_pnl_pct=0.02,
        exit_reason="tp_hit",
        learning_eligible=False,
    )
    update = bridge.build_learning_update(close_event)
    assert update["readiness_eligible"] is False

    # Excluded exit reason
    close_event = create_close_event(
        net_pnl_pct=0.02,
        exit_reason="timeout",
        learning_eligible=True,
    )
    update = bridge.build_learning_update(close_event)
    assert update["readiness_eligible"] is False


def test_metrics_publish_contains_android_required_fields():
    """Test that dashboard metrics include all Android required fields."""
    publisher = V5MetricsPublisher()

    dashboard = publisher.build_dashboard_metrics(
        runtime_state={},
        quota_snapshot={
            "internal_reads_cap": 20000,
            "internal_writes_cap": 10000,
            "reads_used": 100,
            "writes_used": 50,
            "reads_remaining": 19900,
            "writes_remaining": 9950,
            "state": "normal",
        },
        trading_stats={
            "open_positions": 1,
            "closed_today": 5,
            "entries_attempted": 10,
            "entries_accepted": 5,
            "entries_rejected": 5,
            "reject_reasons": {},
            "cost_edge_pass": 4,
            "cost_edge_fail": 1,
        },
        learning_stats={
            "learning_updates": 3,
            "eligible_closes": 2,
            "readiness_status": "TESTING",
            "readiness_status_cs": "TESTOVÁNÍ",
        },
    )

    # Check all required fields present
    for field in config.ANDROID_REQUIRED_FIELDS:
        assert field in dashboard, f"Missing Android required field: {field}"


def test_readiness_metrics_determines_status():
    """Test that readiness metrics correctly determine status."""
    publisher = V5MetricsPublisher()

    # Not enough trades
    readiness = publisher.build_readiness_metrics({
        "learning_updates": 10,
        "eligible_closes": 5,
    })
    assert readiness["status"] == "NOT_READY"

    # Enough trades, good performance
    readiness = publisher.build_readiness_metrics({
        "learning_updates": 50,
        "eligible_closes": 30,
        "win_rate": 0.60,
        "cost_edge_pct": 0.8,
    })
    assert readiness["status"] == "READY"

    # Enough trades, mediocre performance
    readiness = publisher.build_readiness_metrics({
        "learning_updates": 50,
        "eligible_closes": 20,
        "win_rate": 0.50,
        "cost_edge_pct": 0.3,
    })
    assert readiness["status"] == "TESTING"


def test_quota_metrics_includes_utilization():
    """Test that quota metrics include utilization percentages."""
    from src.services.v5_legacy_bridge.quota import V5LegacyQuotaGuard
    import tempfile
    from unittest.mock import patch
    import os
    from src.services.v5_legacy_bridge import config as cfg

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(cfg, "RUNTIME_DIR", tmpdir):
            with patch.object(cfg, "V5_QUOTA_DB_PATH", os.path.join(tmpdir, "quota.sqlite")):
                guard = V5LegacyQuotaGuard()
                guard.record_read(1000)
                guard.record_write(500)

                publisher = V5MetricsPublisher(guard)
                quota = publisher.build_quota_metrics()

                assert "reads_utilization_pct" in quota
                assert "writes_utilization_pct" in quota
                assert 0 <= quota["reads_utilization_pct"] <= 100
                assert 0 <= quota["writes_utilization_pct"] <= 100


def test_metrics_payload_includes_all_sections():
    """Test that prepared payload includes dashboard, readiness, and quota."""
    publisher = V5MetricsPublisher()

    payload = publisher.prepare_publish_payload()

    assert "dashboard" in payload
    assert "readiness" in payload
    assert "quota" in payload
    assert "timestamp" in payload
