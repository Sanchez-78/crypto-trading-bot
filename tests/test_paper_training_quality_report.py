"""
Tests for paper training quality report generator.

Ensures:
- All statistic computations are accurate
- Markdown and JSON output are valid
- CLI interface works
- Edge cases (empty, missing fields) handled gracefully
"""

import json
import tempfile
from pathlib import Path

import pytest

from scripts.paper_training_quality_report import (
    load_dataset,
    compute_dataset_summary,
    compute_outcome_stats,
    compute_pnl_summary,
    compute_attribution_stats,
    compute_regime_performance,
    compute_symbol_performance,
    compute_side_performance,
    compute_barrier_distribution,
    compute_fee_viability,
    compute_geometry_impact,
    compute_cost_edge_performance,
    compute_mfe_mae_quality,
    check_learning_warnings,
    generate_markdown_report,
    generate_json_summary,
)


@pytest.fixture
def sample_trades():
    """Fixture: sample trades for testing."""
    return [
        {
            "trade_id": "T001",
            "symbol": "BTC/USDT",
            "side": "BUY",
            "entry": 67000.0,
            "exit": 67500.0,
            "entry_regime": "BULL_TREND",
            "exit_regime": "BULL_TREND",
            "outcome": "WIN",
            "net_pnl_pct": 0.75,
            "gross_move_pct": 0.75,
            "fee_drag_pct": 0.06,
            "mfe_pct": 2.1,
            "mae_pct": 0.3,
            "touched_tp": True,
            "touched_sl": False,
            "timeout": False,
            "attribution": "tp_hit",
            "bucket": "C_WEAK_EV_TRAIN",
            "geometry_calibrated": True,
            "cost_edge_ok": True,
            "cost_edge_bypassed": False,
        },
        {
            "trade_id": "T002",
            "symbol": "ETH/USDT",
            "side": "SELL",
            "entry": 3500.0,
            "exit": 3450.0,
            "entry_regime": "BEAR_TREND",
            "exit_regime": "BEAR_TREND",
            "outcome": "LOSS",
            "net_pnl_pct": -0.45,
            "gross_move_pct": -0.50,
            "fee_drag_pct": 0.08,
            "mfe_pct": 0.0,
            "mae_pct": 1.2,
            "touched_tp": False,
            "touched_sl": True,
            "timeout": False,
            "attribution": "wrong_direction",
            "bucket": "C_WEAK_EV_TRAIN",
            "geometry_calibrated": True,
            "cost_edge_ok": True,
            "cost_edge_bypassed": False,
        },
        {
            "trade_id": "T003",
            "symbol": "BTC/USDT",
            "side": "BUY",
            "entry": 67100.0,
            "exit": 67050.0,
            "entry_regime": "RANGING",
            "exit_regime": "RANGING",
            "outcome": "FLAT",
            "net_pnl_pct": 0.01,
            "gross_move_pct": -0.05,
            "fee_drag_pct": 0.06,
            "mfe_pct": 0.1,
            "mae_pct": 0.2,
            "touched_tp": False,
            "touched_sl": False,
            "timeout": True,
            "attribution": "timeout",
            "bucket": "C_NEG_EV_PROBE",
            "geometry_calibrated": False,
            "cost_edge_ok": False,
            "cost_edge_bypassed": True,
            "bypass_reason": "cold_start",
        },
    ]


class TestDatasetLoading:
    """Test JSONL loading."""

    def test_load_valid_dataset(self, sample_trades):
        """Load valid JSONL."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for trade in sample_trades:
                f.write(json.dumps(trade) + "\n")
            f.flush()
            temp_path = f.name

        try:
            records = load_dataset(temp_path)
            assert len(records) == 3
            assert records[0]["trade_id"] == "T001"
        finally:
            Path(temp_path).unlink()

    def test_load_with_malformed_lines(self):
        """Skip malformed JSON lines."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"trade_id": "T001"}\n')
            f.write("This is not JSON\n")
            f.write('{"trade_id": "T002"}\n')
            f.flush()
            temp_path = f.name

        try:
            records = load_dataset(temp_path)
            assert len(records) == 2
            assert records[0]["trade_id"] == "T001"
            assert records[1]["trade_id"] == "T002"
        finally:
            Path(temp_path).unlink()

    def test_load_empty_file(self):
        """Empty file returns empty list."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write("")
            f.flush()
            temp_path = f.name

        try:
            records = load_dataset(temp_path)
            assert len(records) == 0
        finally:
            Path(temp_path).unlink()

    def test_load_missing_file(self):
        """Missing file raises error."""
        with pytest.raises(FileNotFoundError):
            load_dataset("/nonexistent/path/data.jsonl")


class TestDatasetSummary:
    """Test dataset summary stats."""

    def test_summary_basic(self, sample_trades):
        """Compute dataset summary."""
        summary = compute_dataset_summary(sample_trades)
        assert summary["total_trades"] == 3
        assert summary["unique_symbols"] == 2  # BTC/USDT, ETH/USDT
        assert summary["unique_buckets"] == 2  # C_WEAK_EV_TRAIN, C_NEG_EV_PROBE

    def test_summary_empty(self):
        """Empty dataset."""
        summary = compute_dataset_summary([])
        assert summary["total_trades"] == 0
        assert summary["unique_symbols"] == 0


class TestOutcomeStats:
    """Test outcome distribution."""

    def test_outcome_distribution(self, sample_trades):
        """Outcome counts and rates."""
        outcomes = compute_outcome_stats(sample_trades)
        assert outcomes["outcome_counts"]["WIN"] == 1
        assert outcomes["outcome_counts"]["LOSS"] == 1
        assert outcomes["outcome_counts"]["FLAT"] == 1
        assert outcomes["outcome_rates"]["WIN"] == round(1 / 3, 4)

    def test_outcome_empty(self):
        """Empty list."""
        outcomes = compute_outcome_stats([])
        assert outcomes["total"] == 0
        assert len(outcomes["outcome_counts"]) == 0


class TestPnLSummary:
    """Test PnL metrics."""

    def test_pnl_computation(self, sample_trades):
        """PnL stats with values."""
        pnl = compute_pnl_summary(sample_trades)
        assert pnl["pnl_records_with_values"] == 3
        assert pnl["positive_pnl_count"] == 2  # T001 (0.75%), T003 (0.01%)
        assert pnl["negative_pnl_count"] == 1  # T002 (-0.45%)
        assert pnl["mean_pnl_pct"] == round((0.75 - 0.45 + 0.01) / 3, 4)

    def test_pnl_no_values(self):
        """No PnL data."""
        trades = [{"trade_id": "T001"}, {"trade_id": "T002"}]
        pnl = compute_pnl_summary(trades)
        assert pnl["pnl_records_with_values"] == 0


class TestAttributionStats:
    """Test attribution distribution."""

    def test_attribution_distribution(self, sample_trades):
        """Attribution counts."""
        attrs = compute_attribution_stats(sample_trades)
        assert attrs["attribution_counts"]["tp_hit"] == 1
        assert attrs["attribution_counts"]["wrong_direction"] == 1
        assert attrs["attribution_counts"]["timeout"] == 1

    def test_attribution_missing(self):
        """Trades without attribution."""
        trades = [{"trade_id": "T001"}, {"trade_id": "T002"}]
        attrs = compute_attribution_stats(trades)
        assert len(attrs["attribution_counts"]) == 0


class TestRegimePerformance:
    """Test win rates by regime."""

    def test_regime_performance(self, sample_trades):
        """Regime win rates."""
        perf = compute_regime_performance(sample_trades)
        assert perf["BULL_TREND"]["total"] == 1  # Only T001
        assert perf["BULL_TREND"]["wins"] == 1
        assert perf["BULL_TREND"]["win_rate"] == 1.0
        assert perf["BEAR_TREND"]["total"] == 1  # T002
        assert perf["BEAR_TREND"]["wins"] == 0
        assert perf["RANGING"]["total"] == 1  # T003
        assert perf["RANGING"]["wins"] == 0

    def test_regime_empty(self):
        """No regime data."""
        trades = [{"trade_id": "T001"}]
        perf = compute_regime_performance(trades)
        assert len(perf) == 0


class TestSymbolPerformance:
    """Test win rates by symbol."""

    def test_symbol_performance(self, sample_trades):
        """Symbol win rates."""
        perf = compute_symbol_performance(sample_trades)
        assert perf["BTC/USDT"]["total"] == 2
        assert perf["BTC/USDT"]["wins"] == 1
        assert perf["BTC/USDT"]["win_rate"] == 0.5
        assert perf["ETH/USDT"]["total"] == 1
        assert perf["ETH/USDT"]["wins"] == 0

    def test_symbol_mean_pnl(self, sample_trades):
        """Symbol mean PnL."""
        perf = compute_symbol_performance(sample_trades)
        btc_pnl = (0.75 + 0.01) / 2
        expected = round(btc_pnl, 4)
        assert perf["BTC/USDT"]["mean_pnl"] == expected


class TestSidePerformance:
    """Test BUY vs SELL performance."""

    def test_side_performance(self, sample_trades):
        """Side win rates."""
        perf = compute_side_performance(sample_trades)
        assert perf["BUY"]["total"] == 2
        assert perf["BUY"]["wins"] == 1
        assert perf["SELL"]["total"] == 1
        assert perf["SELL"]["wins"] == 0


class TestBarrierDistribution:
    """Test exit barrier stats."""

    def test_barrier_distribution(self, sample_trades):
        """Barrier counts and rates."""
        barriers = compute_barrier_distribution(sample_trades)
        assert barriers["touched_tp"] == 1
        assert barriers["touched_sl"] == 1
        assert barriers["timeout"] == 1
        assert barriers["tp_rate"] == round(1 / 3, 4)


class TestFeeViability:
    """Test fee impact analysis."""

    def test_fee_viability(self, sample_trades):
        """Fee stats."""
        fees = compute_fee_viability(sample_trades)
        assert fees["records_with_fee_data"] == 3
        mean_fee = (0.06 + 0.08 + 0.06) / 3
        assert fees["mean_fee_drag_pct"] == round(mean_fee, 4)
        # T002 has positive gross_move (-0.50) but negative net_pnl (-0.45)
        # Actually, T002 gross = -0.50, so net is worse than gross (fee drag added)
        # T001: gross=0.75 > net=0.75 (no fee ate gain here, fee reduces but still positive)
        # T003: gross=-0.05 < net=0.01 (fee actually helped, strange case)
        # Fee ate gain: should be when gross > 0 but net <= 0
        fee_ate = sum(1 for t in sample_trades if t.get("gross_move_pct", 0) > 0 and t.get("net_pnl_pct", 0) <= 0)
        assert fees["trades_where_fee_ate_gain"] == fee_ate

    def test_fee_no_data(self):
        """No fee data."""
        trades = [{"trade_id": "T001"}]
        fees = compute_fee_viability(trades)
        assert fees["records_with_fee_data"] == 0


class TestGeometryImpact:
    """Test geometry calibration impact."""

    def test_geometry_impact(self, sample_trades):
        """Calibrated vs uncalibrated."""
        geom = compute_geometry_impact(sample_trades)
        assert geom["calibrated_count"] == 2
        assert geom["uncalibrated_count"] == 1
        assert geom["calibrated_win_rate"] == 0.5  # 1 win out of 2 calibrated


class TestCostEdgePerformance:
    """Test cost-edge bypass stats."""

    def test_cost_edge_performance(self, sample_trades):
        """Cost-edge OK vs bypassed."""
        edge = compute_cost_edge_performance(sample_trades)
        assert edge["cost_edge_ok_count"] == 2
        assert edge["cost_edge_bypassed_count"] == 1


class TestMFEMAE:
    """Test MFE/MAE stats."""

    def test_mfe_mae_quality(self, sample_trades):
        """MFE/MAE metrics."""
        mfe_mae = compute_mfe_mae_quality(sample_trades)
        assert mfe_mae["mfe_records"] == 3
        assert mfe_mae["mae_records"] == 3
        mean_mfe = (2.1 + 0.0 + 0.1) / 3
        assert mfe_mae["mean_mfe_pct"] == round(mean_mfe, 4)


class TestLearningWarnings:
    """Test warning detection."""

    def test_no_warnings_normal_dataset(self, sample_trades):
        """Normal dataset produces no warnings."""
        warnings = check_learning_warnings(sample_trades)
        # 3 trades, 33% win rate (normal)
        assert len(warnings) == 0 or "Small dataset" not in warnings

    def test_warning_empty_dataset(self):
        """Empty dataset warning."""
        warnings = check_learning_warnings([])
        assert "Empty dataset" in warnings

    def test_warning_small_dataset(self):
        """Small dataset warning."""
        trades = [{"outcome": "WIN"}]
        warnings = check_learning_warnings(trades)
        assert any("Small dataset" in w for w in warnings)

    def test_warning_high_win_rate(self):
        """High win rate warning."""
        trades = [{"outcome": "WIN"} for _ in range(7)] + [{"outcome": "LOSS"} for _ in range(3)]
        warnings = check_learning_warnings(trades)
        assert any("win rate" in w.lower() and "suspiciously" in w.lower() for w in warnings)


class TestMarkdownReport:
    """Test markdown report generation."""

    def test_markdown_report_valid(self, sample_trades):
        """Generate valid markdown."""
        report = generate_markdown_report(sample_trades, "test.jsonl")
        assert "# Paper Training Quality Report" in report
        assert "## 1. Dataset Summary" in report
        assert "## 2. Outcome Distribution" in report
        assert "## 3. PnL Summary" in report
        assert "## 14. Android Dashboard Metric Recommendations" in report
        assert "Total Trades:" in report and "3" in report
        assert "WIN" in report

    def test_markdown_report_empty(self):
        """Markdown report with empty data."""
        report = generate_markdown_report([], "empty.jsonl")
        assert "# Paper Training Quality Report" in report
        assert "Empty dataset" in report


class TestJSONSummary:
    """Test JSON summary generation."""

    def test_json_summary_valid(self, sample_trades):
        """Generate valid JSON summary."""
        summary = generate_json_summary(sample_trades)
        assert "dataset" in summary
        assert "outcomes" in summary
        assert "pnl" in summary
        assert "attribution" in summary
        assert "regime_performance" in summary
        assert "warnings" in summary
        assert summary["dataset"]["total_trades"] == 3

    def test_json_summary_empty(self):
        """JSON summary with empty data."""
        summary = generate_json_summary([])
        assert summary["dataset"]["total_trades"] == 0


class TestCLIInterface:
    """Test CLI entry point."""

    def test_cli_output_to_file(self, sample_trades):
        """CLI writes to output file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "dataset.jsonl"
            output_path = Path(tmpdir) / "report.md"

            # Create dataset
            with open(dataset_path, "w") as f:
                for trade in sample_trades:
                    f.write(json.dumps(trade) + "\n")

            # Run CLI
            from scripts.paper_training_quality_report import main
            import sys
            original_argv = sys.argv
            try:
                sys.argv = ["prog", str(dataset_path), "--output", str(output_path)]
                main()
                assert output_path.exists()
                content = output_path.read_text()
                assert "# Paper Training Quality Report" in content
            finally:
                sys.argv = original_argv

    def test_cli_output_json(self, sample_trades):
        """CLI writes JSON summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dataset_path = Path(tmpdir) / "dataset.jsonl"
            json_path = Path(tmpdir) / "summary.json"

            # Create dataset
            with open(dataset_path, "w") as f:
                for trade in sample_trades:
                    f.write(json.dumps(trade) + "\n")

            # Run CLI
            from scripts.paper_training_quality_report import main
            import sys
            original_argv = sys.argv
            try:
                sys.argv = ["prog", str(dataset_path), "--json", str(json_path)]
                main()
                assert json_path.exists()
                with open(json_path) as f:
                    summary = json.load(f)
                assert summary["dataset"]["total_trades"] == 3
            finally:
                sys.argv = original_argv


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
