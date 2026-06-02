"""Phase 4C: Live PAPER Metrics Dashboard Tests

Verify that:
1. PAPER metrics are collected correctly
2. Dashboard displays live metrics
3. Legacy metrics are labeled clearly
4. No stale data is shown
"""

import pytest
import time
from src.services.paper_training_metrics import (
    get_paper_metrics, record_paper_entry, record_paper_exit,
    record_learning_update, record_starvation_bypass_accepted,
    record_starvation_bypass_rejected, PaperTrainingMetrics
)


class TestPaperMetricsCollection:
    """Test PAPER metrics collection."""

    def setup_method(self):
        """Reset metrics before each test."""
        # Create fresh instance
        from src.services import paper_training_metrics
        paper_training_metrics._metrics = None
        self.metrics = get_paper_metrics()

    def test_paper_entry_recorded(self):
        """PAPER entry is recorded with timestamp."""
        record_paper_entry("BTC", "BUY", "PAPER_EXPLORE")
        snapshot = self.metrics.get_metrics(open_positions_count=1)

        assert snapshot["paper_entries_1h"] == 1
        assert snapshot["last_paper_entry_age_s"] is not None
        assert snapshot["last_paper_entry_age_s"] < 5  # Should be very recent

    def test_paper_exit_recorded(self):
        """PAPER exit is recorded with timestamp."""
        record_paper_exit("BTC", "BUY", "WIN")
        snapshot = self.metrics.get_metrics()

        assert snapshot["paper_exits_1h"] == 1
        assert snapshot["last_paper_exit_age_s"] is not None
        assert snapshot["last_paper_exit_age_s"] < 5

    def test_learning_update_recorded(self):
        """Learning update is recorded."""
        record_learning_update("BTC", "trade_123")
        snapshot = self.metrics.get_metrics()

        assert snapshot["paper_learning_updates_1h"] == 1
        assert snapshot["last_learning_update_age_s"] is not None
        assert snapshot["last_learning_update_age_s"] < 5

    def test_starvation_bypass_accepted_recorded(self):
        """Starvation bypass acceptance is recorded."""
        record_starvation_bypass_accepted("BTC", "PAPER_STARVATION_DISCOVERY")
        snapshot = self.metrics.get_metrics()

        assert snapshot["starvation_bypass_accepted_1h"] == 1

    def test_starvation_bypass_rejected_recorded(self):
        """Starvation bypass rejection is recorded."""
        record_starvation_bypass_rejected("BTC", "idle_too_low")
        snapshot = self.metrics.get_metrics()

        assert snapshot["starvation_bypass_rejected_1h"] == 1

    def test_multiple_events_counted(self):
        """Multiple events are counted correctly."""
        # Record 5 entries
        for i in range(5):
            record_paper_entry(f"BTC", "BUY")
            time.sleep(0.01)  # Small delay

        # Record 3 exits
        for i in range(3):
            record_paper_exit("BTC", "BUY", "WIN")
            time.sleep(0.01)

        # Record 2 learning updates
        for i in range(2):
            record_learning_update("BTC")
            time.sleep(0.01)

        snapshot = self.metrics.get_metrics()

        assert snapshot["paper_entries_1h"] == 5
        assert snapshot["paper_exits_1h"] == 3
        assert snapshot["paper_learning_updates_1h"] == 2

    def test_open_positions_passed(self):
        """Open positions count is passed through."""
        snapshot = self.metrics.get_metrics(open_positions_count=3)
        assert snapshot["open_positions"] == 3

    def test_v5_outbox_pending_counts(self):
        """V5 outbox pending counts are passed through."""
        snapshot = self.metrics.get_metrics(
            v5_outbox_pending_open=2,
            v5_outbox_pending_close=1,
            v5_outbox_pending_learning=3
        )

        assert snapshot["v5_outbox_pending_open"] == 2
        assert snapshot["v5_outbox_pending_close"] == 1
        assert snapshot["v5_outbox_pending_learning"] == 3

    def test_1h_window_excludes_old_events(self):
        """Events older than 1 hour are excluded."""
        # Create a metrics instance
        m = PaperTrainingMetrics()

        # Manually add an event with old timestamp (>1 hour ago)
        old_ts = time.time() - 3700  # 1h 1m ago
        m._paper_entries_1h.append(old_ts)

        # Add a recent event
        recent_ts = time.time()
        m._paper_entries_1h.append(recent_ts)

        snapshot = m.get_metrics()

        # Should only count the recent event
        assert snapshot["paper_entries_1h"] == 1

    def test_age_calculations(self):
        """Event age is calculated correctly."""
        record_paper_entry("BTC", "BUY")
        time.sleep(0.5)  # Wait 500ms

        snapshot = self.metrics.get_metrics()

        # Age should be approximately 0.5 seconds
        age = snapshot["last_paper_entry_age_s"]
        assert 0.4 < age < 1.0, f"Age {age} not in expected range"

    def test_none_ages_when_no_events(self):
        """Ages are None when no events recorded."""
        snapshot = self.metrics.get_metrics()

        assert snapshot["last_paper_entry_age_s"] is None
        assert snapshot["last_paper_exit_age_s"] is None
        assert snapshot["last_learning_update_age_s"] is None


class TestDashboardDisplay:
    """Test dashboard display of PAPER metrics."""

    def test_czech_dashboard_print_paper_training_live(self, capsys):
        """Dashboard can print PAPER training live metrics."""
        from src.v5_bot.util.czech_dashboard import CzechDashboard

        dashboard = CzechDashboard(trading_symbols=["BTCUSDT", "ETHUSDT"])

        paper_metrics = {
            "open_positions": 2,
            "paper_entries_1h": 5,
            "paper_exits_1h": 3,
            "paper_learning_updates_1h": 4,
            "starvation_bypass_accepted_1h": 1,
            "starvation_bypass_rejected_1h": 0,
            "last_paper_entry_age_s": 12.5,
            "last_paper_exit_age_s": 45.2,
            "last_learning_update_age_s": 8.1,
            "v5_outbox_pending_open": 0,
            "v5_outbox_pending_close": 1,
            "v5_outbox_pending_learning": 0,
        }

        dashboard.print_paper_training_live(paper_metrics)
        captured = capsys.readouterr()

        # Verify output contains expected elements
        assert "PAPER TRAINING – LIVE" in captured.out
        assert "Otevřené pozice" in captured.out
        assert "2" in captured.out  # open_positions
        assert "Vstupy (1h)" in captured.out
        assert "5" in captured.out  # entries_1h
        assert "Výstupy (1h)" in captured.out
        assert "3" in captured.out  # exits_1h
        assert "Aktualizace učení (1h)" in captured.out
        assert "4" in captured.out  # learning_updates_1h

    def test_dashboard_shows_recent_event_ages(self, capsys):
        """Dashboard shows ages of recent events."""
        from src.v5_bot.util.czech_dashboard import CzechDashboard

        dashboard = CzechDashboard(trading_symbols=["BTCUSDT"])

        paper_metrics = {
            "open_positions": 1,
            "paper_entries_1h": 1,
            "paper_exits_1h": 0,
            "paper_learning_updates_1h": 0,
            "starvation_bypass_accepted_1h": 0,
            "starvation_bypass_rejected_1h": 0,
            "last_paper_entry_age_s": 25.0,
            "last_paper_exit_age_s": None,
            "last_learning_update_age_s": None,
            "v5_outbox_pending_open": 0,
            "v5_outbox_pending_close": 0,
            "v5_outbox_pending_learning": 0,
        }

        dashboard.print_paper_training_live(paper_metrics)
        captured = capsys.readouterr()

        assert "Poslední vstup" in captured.out
        assert "25s zpět" in captured.out or "25" in captured.out

    def test_dashboard_shows_outbox_pending(self, capsys):
        """Dashboard shows V5 outbox pending events."""
        from src.v5_bot.util.czech_dashboard import CzechDashboard

        dashboard = CzechDashboard(trading_symbols=["BTCUSDT"])

        paper_metrics = {
            "open_positions": 0,
            "paper_entries_1h": 0,
            "paper_exits_1h": 0,
            "paper_learning_updates_1h": 0,
            "starvation_bypass_accepted_1h": 0,
            "starvation_bypass_rejected_1h": 0,
            "last_paper_entry_age_s": None,
            "last_paper_exit_age_s": None,
            "last_learning_update_age_s": None,
            "v5_outbox_pending_open": 2,
            "v5_outbox_pending_close": 1,
            "v5_outbox_pending_learning": 3,
        }

        dashboard.print_paper_training_live(paper_metrics)
        captured = capsys.readouterr()

        assert "V5 Outbox" in captured.out
        assert "paper_open" in captured.out
        assert "2" in captured.out  # pending_open
        assert "paper_close" in captured.out
        assert "1" in captured.out  # pending_close
        assert "learning_update" in captured.out
        assert "3" in captured.out  # pending_learning

    def test_dashboard_shows_starvation_metrics(self, capsys):
        """Dashboard shows starvation bypass metrics."""
        from src.v5_bot.util.czech_dashboard import CzechDashboard

        dashboard = CzechDashboard(trading_symbols=["BTCUSDT"])

        paper_metrics = {
            "open_positions": 1,
            "paper_entries_1h": 2,
            "paper_exits_1h": 1,
            "paper_learning_updates_1h": 1,
            "starvation_bypass_accepted_1h": 2,
            "starvation_bypass_rejected_1h": 5,
            "last_paper_entry_age_s": 10.0,
            "last_paper_exit_age_s": 20.0,
            "last_learning_update_age_s": 15.0,
            "v5_outbox_pending_open": 0,
            "v5_outbox_pending_close": 0,
            "v5_outbox_pending_learning": 0,
        }

        dashboard.print_paper_training_live(paper_metrics)
        captured = capsys.readouterr()

        assert "Starvation bypass" in captured.out
        assert "Přijato" in captured.out
        assert "2" in captured.out  # accepted
        assert "Odmítnuto" in captured.out
        assert "5" in captured.out  # rejected

    def test_dashboard_full_status_with_paper_metrics(self, capsys):
        """Full dashboard status includes PAPER metrics."""
        from src.v5_bot.util.czech_dashboard import CzechDashboard

        dashboard = CzechDashboard(trading_symbols=["BTCUSDT"])

        closed_trades = {}
        paper_metrics = {
            "open_positions": 1,
            "paper_entries_1h": 3,
            "paper_exits_1h": 2,
            "paper_learning_updates_1h": 2,
            "starvation_bypass_accepted_1h": 0,
            "starvation_bypass_rejected_1h": 0,
            "last_paper_entry_age_s": 15.0,
            "last_paper_exit_age_s": 30.0,
            "last_learning_update_age_s": 10.0,
            "v5_outbox_pending_open": 0,
            "v5_outbox_pending_close": 0,
            "v5_outbox_pending_learning": 0,
        }

        dashboard.print_status(
            closed_trades=closed_trades,
            entries_attempted=5,
            entries_successful=3,
            entries_rejected=2,
            trades_closed=2,
            open_positions_count=1,
            paper_metrics=paper_metrics
        )
        captured = capsys.readouterr()

        # Should contain both legacy section and PAPER TRAINING section
        assert "VYSLEDKY OBCHODOVANI" in captured.out or "TRADING PERFORMANCE" in captured.out
        assert "PAPER TRAINING – LIVE" in captured.out
        assert "Vstupy (1h)" in captured.out
        assert "3" in captured.out


class TestMetricsThreadSafety:
    """Test that metrics are thread-safe."""

    def test_concurrent_recordings(self):
        """Metrics handle concurrent recordings correctly."""
        import threading
        from src.services import paper_training_metrics
        paper_training_metrics._metrics = None
        metrics = get_paper_metrics()

        def record_entries():
            for i in range(10):
                record_paper_entry("BTC", "BUY")
                time.sleep(0.001)

        def record_exits():
            for i in range(10):
                record_paper_exit("BTC", "BUY", "WIN")
                time.sleep(0.001)

        def record_learning():
            for i in range(10):
                record_learning_update("BTC")
                time.sleep(0.001)

        # Run concurrently
        t1 = threading.Thread(target=record_entries)
        t2 = threading.Thread(target=record_exits)
        t3 = threading.Thread(target=record_learning)

        t1.start()
        t2.start()
        t3.start()

        t1.join()
        t2.join()
        t3.join()

        snapshot = metrics.get_metrics()

        # Should have recorded all events
        assert snapshot["paper_entries_1h"] == 10
        assert snapshot["paper_exits_1h"] == 10
        assert snapshot["paper_learning_updates_1h"] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
