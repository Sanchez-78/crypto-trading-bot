"""Tests for standalone forward PAPER runner with simulated feed."""

import pytest
import os
import json
import tempfile
from pathlib import Path

from src.clean_core.runner.forward_paper_runner import ForwardPaperRunner
from src.clean_core.runner.simulated_futures_feed import SimulatedFuturesFeed
from src.clean_core.strategy.fixed_strategy import FixedStrategy


class TestForwardRunnerSimulatedFeed:
    """Test forward PAPER runner with deterministic simulated feed."""

    def test_15_simulated_feed_initialization(self):
        """Test 15: SimulatedFuturesFeed initializes and returns snapshot."""
        snapshot = {
            "time": "2026-05-26T12:00:00Z",
            "price": 50000.0,
            "bid": 49999.5,
            "ask": 50000.5,
        }
        trades = [{"time": "2026-05-26T12:01:00Z", "price": 50050.0}]

        feed = SimulatedFuturesFeed(snapshot, trades)
        feed.initialize("BTCUSDT")

        snap = feed.get_snapshot()
        assert snap is not None
        assert snap.symbol == "BTCUSDT"
        assert snap.price == 50000.0
        assert snap.bid == 49999.5
        assert snap.ask == 50000.5

    def test_16_simulated_feed_trade_iteration(self):
        """Test 16: SimulatedFuturesFeed iterates trades correctly."""
        snapshot = {
            "time": "2026-05-26T12:00:00Z",
            "price": 50000.0,
            "bid": 49999.5,
            "ask": 50000.5,
        }
        trades = [
            {"time": "2026-05-26T12:01:00Z", "price": 50050.0},
            {"time": "2026-05-26T12:02:00Z", "price": 50100.0},
            {"time": "2026-05-26T12:03:00Z", "price": 50150.0},
        ]

        feed = SimulatedFuturesFeed(snapshot, trades)
        feed.initialize("BTCUSDT")

        # Consume trades
        prices = []
        while True:
            trade = feed.get_next_trade()
            if not trade:
                break
            prices.append(trade.price)

        assert len(prices) == 3
        assert prices == [50050.0, 50100.0, 50150.0]

    def test_17_forward_runner_requires_absolute_output_dir(self):
        """Test 17: ForwardPaperRunner requires absolute output_dir."""
        snapshot = {"time": "2026-05-26T12:00:00Z", "price": 50000.0, "bid": 49999.5, "ask": 50000.5}
        trades = [{"time": "2026-05-26T12:01:00Z", "price": 50050.0}]
        feed = SimulatedFuturesFeed(snapshot, trades)

        # Relative path should fail (treated as non-absolute)
        with pytest.raises(ValueError, match="absolute|must exist"):
            runner = ForwardPaperRunner(
                feed=feed,
                symbol="BTCUSDT",
                output_dir="relative/path",
            )

    def test_18_forward_runner_requires_existing_output_dir(self):
        """Test 18: ForwardPaperRunner requires output_dir to exist."""
        snapshot = {"time": "2026-05-26T12:00:00Z", "price": 50000.0, "bid": 49999.5, "ask": 50000.5}
        trades = [{"time": "2026-05-26T12:01:00Z", "price": 50050.0}]
        feed = SimulatedFuturesFeed(snapshot, trades)

        # Non-existent absolute path should fail
        with pytest.raises(ValueError, match="must exist"):
            runner = ForwardPaperRunner(
                feed=feed,
                symbol="BTCUSDT",
                output_dir=str(Path("/tmp/nonexistent_12345_cleanup_now")),
            )

    def test_19_forward_runner_end_to_end_simulated(self):
        """Test 19: ForwardPaperRunner completes full lifecycle with simulated feed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = {
                "time": "2026-05-26T12:00:00Z",
                "price": 50000.0,
                "bid": 49999.5,
                "ask": 50000.5,
            }
            trades = [
                {"time": "2026-05-26T12:01:00Z", "price": 50050.0},
                {"time": "2026-05-26T12:02:00Z", "price": 50075.0},
                {"time": "2026-05-26T12:03:00Z", "price": 50100.0},
                {"time": "2026-05-26T12:04:00Z", "price": 50090.0},
                {"time": "2026-05-26T12:05:00Z", "price": 50105.0},
                {"time": "2026-05-26T12:06:00Z", "price": 50110.0},
                {"time": "2026-05-26T12:07:00Z", "price": 50150.0},
                {"time": "2026-05-26T12:08:00Z", "price": 50200.0},
                {"time": "2026-05-26T12:09:00Z", "price": 50250.0},
                {"time": "2026-05-26T12:10:00Z", "price": 50300.0},
                {"time": "2026-05-26T12:11:00Z", "price": 50350.0},
                {"time": "2026-05-26T12:12:00Z", "price": 50400.0},
                {"time": "2026-05-26T12:13:00Z", "price": 50450.0},
                {"time": "2026-05-26T12:14:00Z", "price": 50500.0},
                {"time": "2026-05-26T12:15:00Z", "price": 50540.0},
                {"time": "2026-05-26T12:16:00Z", "price": 50555.0},
            ]

            feed = SimulatedFuturesFeed(snapshot, trades)
            runner = ForwardPaperRunner(
                feed=feed,
                symbol="BTCUSDT",
                output_dir=tmpdir,
            )

            report = runner.run()

            # Verify report structure
            assert report["symbol"] == "BTCUSDT"
            assert report["status"] == "complete"
            assert report["closed_trades_count"] == 1
            assert len(report["closed_outcomes"]) == 1

            # Verify closed outcome
            outcome = report["closed_outcomes"][0]
            assert outcome["entry_price"] == pytest.approx(50050.0)
            assert outcome["exit_price"] == pytest.approx(50555.0)
            assert outcome["gross_pnl_pct"] == pytest.approx(1.0, rel=0.01)
            assert outcome["eligible_for_clean_paper_metrics"] is True
            assert outcome["eligible_for_real_readiness"] is False

            # Verify journal was created
            assert os.path.exists(report["journal_path"])
            with open(report["journal_path"], "r") as f:
                lines = f.readlines()
                assert len(lines) > 0
                event = json.loads(lines[0])
                assert event["event_type"] == "paper_trade_closed"

    def test_20_forward_runner_uses_taker_fees_in_report(self):
        """Test 20: ForwardPaperRunner report shows taker-fee costs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = {
                "time": "2026-05-26T12:00:00Z",
                "price": 50000.0,
                "bid": 49999.5,
                "ask": 50000.5,
            }
            trades = [
                {"time": "2026-05-26T12:01:00Z", "price": 50050.0},
                {"time": "2026-05-26T12:16:00Z", "price": 50555.0},
            ]

            feed = SimulatedFuturesFeed(snapshot, trades)
            runner = ForwardPaperRunner(
                feed=feed,
                symbol="BTCUSDT",
                output_dir=tmpdir,
            )

            report = runner.run()
            outcome = report["closed_outcomes"][0]

            # Expected fee: 2 * taker_fee_bps (entry + exit)
            # Taker is 4 bps, so total = 8 bps = 0.08%
            expected_fee = 0.08
            assert outcome["fee_cost_pct"] == pytest.approx(expected_fee, rel=0.01)

            # Net PnL should be gross - fees (no funding in MVP)
            # Gross ≈ 1%, Fee = 0.08%, Net ≈ 0.92%
            expected_net = 1.0 - 0.08
            assert outcome["net_pnl_pct"] == pytest.approx(expected_net, rel=0.01)
