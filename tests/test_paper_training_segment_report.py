"""
Tests for paper training segment quality analysis.

Ensures:
- Dataset loading filters to completed trades only
- Computation functions return correct metrics
- Recommendation logic follows decision order
- Exclusion scenarios reduce trade counts correctly
- Output generation creates valid markdown/JSON
- End-to-end pipeline works
"""

import json
import tempfile
from pathlib import Path

import pytest

from scripts.paper_training_segment_report import (
    compute_attribution_stats,
    compute_bucket_stats,
    compute_dataset_summary,
    compute_economic_severity,
    compute_exclusion_scenarios,
    compute_regime_quality,
    compute_side_regime_matrix,
    compute_symbol_quality,
    generate_json_summary,
    generate_markdown_report,
    load_dataset,
    recommend_patch,
    separate_by_bucket,
)


class TestDatasetLoading:
    """Test dataset loading and filtering."""

    def test_load_dataset_filters_to_completed_trades(self):
        """Load only records with both exit and outcome non-null."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "data.jsonl"
            records = [
                {"trade_id": "T001", "exit": 100.0, "outcome": "WIN"},
                {"trade_id": "T002", "exit": 50.0, "outcome": "LOSS"},
                {"trade_id": "T003", "exit": None, "outcome": "WIN"},  # Incomplete
                {"trade_id": "T004", "exit": 75.0, "outcome": None},  # Incomplete
            ]
            with open(jsonl_path, "w") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")

            loaded = load_dataset(jsonl_path)
            assert len(loaded) == 2
            assert loaded[0]["trade_id"] == "T001"
            assert loaded[1]["trade_id"] == "T002"

    def test_load_dataset_skips_incomplete_records(self):
        """Incomplete records (missing exit or outcome) are excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "data.jsonl"
            with open(jsonl_path, "w") as f:
                f.write(json.dumps({"trade_id": "T001", "exit": None, "outcome": "WIN"}) + "\n")
                f.write(json.dumps({"trade_id": "T002"}) + "\n")  # No exit/outcome
                f.write(
                    json.dumps({"trade_id": "T003", "exit": 100.0, "outcome": "LOSS"}) + "\n"
                )

            loaded = load_dataset(jsonl_path)
            assert len(loaded) == 1
            assert loaded[0]["trade_id"] == "T003"


class TestComputationFunctions:
    """Test individual computation functions."""

    def _sample_records(self):
        """Return sample dataset."""
        return [
            {
                "trade_id": "T001",
                "exit": 100.0,
                "outcome": "WIN",
                "training_bucket": "C_WEAK_EV_TRAIN",
                "symbol": "BTC",
                "side": "BUY",
                "entry_regime": "BULL_TREND",
                "attribution": "NORMAL_WIN",
                "net_pnl_pct": 1.5,
                "gross_move_pct": 2.0,
                "mfe_pct": 3.0,
                "mae_pct": 0.5,
            },
            {
                "trade_id": "T002",
                "exit": 50.0,
                "outcome": "LOSS",
                "training_bucket": "D_NEG_EV_CONTROL",
                "symbol": "ETH",
                "side": "SELL",
                "entry_regime": "RANGING",
                "attribution": "FEE_DOMINATED_MOVE",
                "net_pnl_pct": -0.8,
                "gross_move_pct": 1.2,
                "mfe_pct": 0.5,
                "mae_pct": 1.8,
            },
            {
                "trade_id": "T003",
                "exit": 75.0,
                "outcome": "WIN",
                "training_bucket": "C_WEAK_EV_TRAIN",
                "symbol": "BTC",
                "side": "BUY",
                "entry_regime": "QUIET_RANGE",
                "attribution": "WRONG_DIRECTION",
                "net_pnl_pct": 0.3,
                "gross_move_pct": 0.8,
                "mfe_pct": 1.5,
                "mae_pct": 2.0,
            },
        ]

    def test_compute_dataset_summary_returns_counts(self):
        """Summary includes total_completed_trades, unique_trade_ids, unique_symbols, unique_buckets."""
        records = self._sample_records()
        summary = compute_dataset_summary(records)

        assert summary["total_completed_trades"] == 3
        assert summary["unique_trade_ids"] == 3
        assert summary["unique_symbols"] == 2  # BTC, ETH
        assert set(summary["unique_buckets"]) == {"C_WEAK_EV_TRAIN", "D_NEG_EV_CONTROL"}

    def test_compute_dataset_summary_empty_dataset(self):
        """Empty dataset returns zero counts."""
        summary = compute_dataset_summary([])

        assert summary["total_completed_trades"] == 0
        assert summary["unique_trade_ids"] == 0
        assert summary["unique_symbols"] == 0
        assert summary["unique_buckets"] == []

    def test_separate_by_bucket_groups_correctly(self):
        """Records grouped by training_bucket."""
        records = self._sample_records()
        buckets = separate_by_bucket(records)

        assert len(buckets) == 2
        assert len(buckets.get("C_WEAK_EV_TRAIN", [])) == 2
        assert len(buckets.get("D_NEG_EV_CONTROL", [])) == 1

    def test_compute_bucket_stats_includes_win_rate(self):
        """Bucket stats include count, win_rate, avg_pnl_pct, outcomes."""
        records = [
            {
                "trade_id": "T001",
                "exit": 100.0,
                "outcome": "WIN",
                "net_pnl_pct": 1.5,
            },
            {
                "trade_id": "T002",
                "exit": 50.0,
                "outcome": "LOSS",
                "net_pnl_pct": -0.8,
            },
            {
                "trade_id": "T003",
                "exit": 75.0,
                "outcome": "WIN",
                "net_pnl_pct": 0.3,
            },
        ]
        stats = compute_bucket_stats(records)

        assert stats["count"] == 3
        assert stats["win_rate"] == pytest.approx(2.0 / 3.0, abs=0.01)
        assert stats["avg_pnl_pct"] == pytest.approx((1.5 - 0.8 + 0.3) / 3, abs=0.01)
        assert stats["outcomes"]["WIN"] == 2
        assert stats["outcomes"]["LOSS"] == 1

    def test_compute_attribution_stats_calculates_percentages(self):
        """Attribution breakdown sums contributions and percentages."""
        records = self._sample_records()
        stats = compute_attribution_stats(records)

        assert stats["total"] == 3
        assert "NORMAL_WIN" in stats["by_attribution"]
        assert "WRONG_DIRECTION" in stats["by_attribution"]
        assert "FEE_DOMINATED_MOVE" in stats["by_attribution"]

        # Each should have count, percent, avg_pnl_pct
        normal_win = stats["by_attribution"]["NORMAL_WIN"]
        assert normal_win["count"] == 1
        assert normal_win["percent"] == pytest.approx(33.3, abs=0.1)

    def test_compute_economic_severity_detects_fee_dominated(self):
        """Severity analysis separates WRONG_DIRECTION from FEE_DOMINATED_MOVE."""
        records = [
            {
                "trade_id": "T001",
                "exit": 100.0,
                "outcome": "LOSS",
                "attribution": "WRONG_DIRECTION",
                "net_pnl_pct": -2.0,
                "gross_move_pct": 5.0,
                "mfe_pct": 1.0,
                "mae_pct": 6.0,
            },
            {
                "trade_id": "T002",
                "exit": 50.0,
                "outcome": "LOSS",
                "attribution": "FEE_DOMINATED_MOVE",
                "net_pnl_pct": -0.5,
                "gross_move_pct": 1.0,
                "mfe_pct": 0.2,
                "mae_pct": 1.2,
            },
        ]
        severity = compute_economic_severity(records)

        wd = severity["WRONG_DIRECTION"]
        assert wd["count"] == 1
        assert wd["percent"] == 50.0
        assert wd["avg_pnl_pct"] == pytest.approx(-2.0, abs=0.01)

        fd = severity["FEE_DOMINATED_MOVE"]
        assert fd["count"] == 1
        assert fd["percent"] == 50.0
        assert fd["avg_pnl_pct"] == pytest.approx(-0.5, abs=0.01)


class TestRecommendationLogic:
    """Test patch recommendation decision tree."""

    def _weak_ev_records(self, count=100):
        """Generate C_WEAK_EV_TRAIN records."""
        records = []
        for i in range(count):
            records.append(
                {
                    "trade_id": f"T{i:04d}",
                    "exit": 100.0,
                    "outcome": "WIN" if i % 2 == 0 else "LOSS",
                    "training_bucket": "C_WEAK_EV_TRAIN",
                    "symbol": f"SYM{i % 5}",
                    "side": "BUY" if i % 2 == 0 else "SELL",
                    "entry_regime": "BULL_TREND",
                    "attribution": "NORMAL_WIN",
                    "net_pnl_pct": 0.5,
                    "gross_move_pct": 1.0,
                    "mfe_pct": 1.5,
                    "mae_pct": 0.5,
                }
            )
        return records

    def test_recommend_patch_collect_more_if_weak_ev_train_low(self):
        """If C_WEAK_EV_TRAIN < 100: NO_PATCH_COLLECT_MORE_DATA."""
        records = self._weak_ev_records(50)
        econ_sev = compute_economic_severity(records)
        regime_stats = compute_regime_quality(records)
        symbol_stats = compute_symbol_quality(records)
        excl_scenarios = compute_exclusion_scenarios(records)

        rec = recommend_patch(records, econ_sev, regime_stats, symbol_stats, excl_scenarios)
        assert rec == "NO_PATCH_COLLECT_MORE_DATA"

    def test_recommend_patch_fee_viability_if_fee_high_direction_low(self):
        """FEE_DOMINATED_MOVE > 50%, WRONG_DIRECTION < 35% → PRECHECK_FEE_VIABILITY."""
        records = self._weak_ev_records(100)
        # Override attribution: 60% fee, 30% wrong direction
        for i, r in enumerate(records):
            if i < 60:
                r["attribution"] = "FEE_DOMINATED_MOVE"
            elif i < 90:
                r["attribution"] = "WRONG_DIRECTION"
            else:
                r["attribution"] = "NORMAL_WIN"

        econ_sev = compute_economic_severity(records)
        regime_stats = compute_regime_quality(records)
        symbol_stats = compute_symbol_quality(records)
        excl_scenarios = compute_exclusion_scenarios(records)

        rec = recommend_patch(records, econ_sev, regime_stats, symbol_stats, excl_scenarios)
        assert rec == "PRECHECK_FEE_VIABILITY"

    def test_recommend_patch_direction_filter_if_direction_high_fee_low(self):
        """WRONG_DIRECTION > 50%, FEE_DOMINATED_MOVE < 35% → PRECHECK_DIRECTION_FILTER."""
        records = self._weak_ev_records(100)
        # Override attribution: 60% wrong direction, 30% fee
        for i, r in enumerate(records):
            if i < 60:
                r["attribution"] = "WRONG_DIRECTION"
            elif i < 90:
                r["attribution"] = "FEE_DOMINATED_MOVE"
            else:
                r["attribution"] = "NORMAL_WIN"

        econ_sev = compute_economic_severity(records)
        regime_stats = compute_regime_quality(records)
        symbol_stats = compute_symbol_quality(records)
        excl_scenarios = compute_exclusion_scenarios(records)

        rec = recommend_patch(records, econ_sev, regime_stats, symbol_stats, excl_scenarios)
        assert rec == "PRECHECK_DIRECTION_FILTER"

    def test_recommend_patch_regime_filter_if_quiet_range_no_wins(self):
        """QUIET_RANGE with n≥20, win_rate=0%, exclusion improves > 0.5% → PRECHECK_REGIME_FILTER."""
        records = []
        # Create 20 QUIET_RANGE large losses, 80 other small wins
        # Exclusion improvement > 0.5%: (-60 + 16) / 100 = -0.44%, after exclusion 0.2% → 0.64% improvement
        for i in range(20):
            records.append(
                {
                    "trade_id": f"QR{i:03d}",
                    "exit": 100.0,
                    "outcome": "LOSS",
                    "training_bucket": "C_WEAK_EV_TRAIN",
                    "symbol": f"SYM_QR{i % 10}",  # Spread QUIET_RANGE across 10 symbols
                    "side": "BUY",
                    "entry_regime": "QUIET_RANGE",
                    "attribution": "NORMAL_WIN",
                    "net_pnl_pct": -3.0,  # Large losses
                    "gross_move_pct": 1.0,
                    "mfe_pct": 0.5,
                    "mae_pct": 1.5,
                }
            )
        for i in range(80):
            records.append(
                {
                    "trade_id": f"OTH{i:03d}",
                    "exit": 100.0,
                    "outcome": "WIN",
                    "training_bucket": "C_WEAK_EV_TRAIN",
                    "symbol": f"SYM_OTHER{i % 10}",  # Spread other trades across 10 symbols
                    "side": "BUY",
                    "entry_regime": "BULL_TREND",
                    "attribution": "NORMAL_WIN",
                    "net_pnl_pct": 0.2,  # Small wins
                    "gross_move_pct": 1.0,
                    "mfe_pct": 1.5,
                    "mae_pct": 0.5,
                }
            )

        econ_sev = compute_economic_severity(records)
        regime_stats = compute_regime_quality(records)
        symbol_stats = compute_symbol_quality(records)
        excl_scenarios = compute_exclusion_scenarios(records)

        rec = recommend_patch(records, econ_sev, regime_stats, symbol_stats, excl_scenarios)
        assert rec == "PRECHECK_REGIME_FILTER"

    def test_recommend_patch_symbol_filter_if_symbol_dominated(self):
        """Symbol with n≥20, single attribution >50%, worse PnL → PRECHECK_SYMBOL_FILTER."""
        records = []
        # Create 25 BTC trades with 60% FEE_DOMINATED_MOVE (avg -1.0 PnL)
        for i in range(15):
            records.append(
                {
                    "trade_id": f"BTC{i:03d}",
                    "exit": 100.0,
                    "outcome": "LOSS",
                    "training_bucket": "C_WEAK_EV_TRAIN",
                    "symbol": "BTC",
                    "side": "BUY",
                    "entry_regime": "BULL_TREND",
                    "attribution": "FEE_DOMINATED_MOVE",
                    "net_pnl_pct": -1.0,
                    "gross_move_pct": 1.0,
                    "mfe_pct": 0.5,
                    "mae_pct": 1.5,
                }
            )
        for i in range(10):
            records.append(
                {
                    "trade_id": f"BTC{15 + i:03d}",
                    "exit": 100.0,
                    "outcome": "WIN",
                    "training_bucket": "C_WEAK_EV_TRAIN",
                    "symbol": "BTC",
                    "side": "BUY",
                    "entry_regime": "BULL_TREND",
                    "attribution": "NORMAL_WIN",
                    "net_pnl_pct": 0.5,
                    "gross_move_pct": 1.0,
                    "mfe_pct": 1.5,
                    "mae_pct": 0.5,
                }
            )
        # 75 other trades (avg 0.5 PnL)
        for i in range(75):
            records.append(
                {
                    "trade_id": f"OTH{i:03d}",
                    "exit": 100.0,
                    "outcome": "WIN",
                    "training_bucket": "C_WEAK_EV_TRAIN",
                    "symbol": f"SYM{i % 5}",
                    "side": "BUY",
                    "entry_regime": "BULL_TREND",
                    "attribution": "NORMAL_WIN",
                    "net_pnl_pct": 0.5,
                    "gross_move_pct": 1.0,
                    "mfe_pct": 1.5,
                    "mae_pct": 0.5,
                }
            )

        econ_sev = compute_economic_severity(records)
        regime_stats = compute_regime_quality(records)
        symbol_stats = compute_symbol_quality(records)
        excl_scenarios = compute_exclusion_scenarios(records)

        rec = recommend_patch(records, econ_sev, regime_stats, symbol_stats, excl_scenarios)
        assert rec == "PRECHECK_SYMBOL_FILTER"

    def test_recommend_patch_default_to_collect_more(self):
        """Borderline metrics → NO_PATCH_COLLECT_MORE_DATA."""
        records = self._weak_ev_records(100)
        econ_sev = compute_economic_severity(records)
        regime_stats = compute_regime_quality(records)
        symbol_stats = compute_symbol_quality(records)
        excl_scenarios = compute_exclusion_scenarios(records)

        rec = recommend_patch(records, econ_sev, regime_stats, symbol_stats, excl_scenarios)
        assert rec == "NO_PATCH_COLLECT_MORE_DATA"


class TestExclusionScenarios:
    """Test exclusion scenario computations."""

    def test_exclusion_scenario_remove_bucket(self):
        """Excluding D_NEG_EV_CONTROL filters out records."""
        records = [
            {
                "trade_id": "T001",
                "exit": 100.0,
                "outcome": "WIN",
                "training_bucket": "C_WEAK_EV_TRAIN",
                "net_pnl_pct": 1.5,
            },
            {
                "trade_id": "T002",
                "exit": 50.0,
                "outcome": "LOSS",
                "training_bucket": "D_NEG_EV_CONTROL",
                "net_pnl_pct": -2.0,
            },
        ]
        scenarios = compute_exclusion_scenarios(records)

        # exclude_D_NEG_EV_CONTROL should have 1 record (the C_WEAK_EV_TRAIN one)
        assert scenarios["exclude_D_NEG_EV_CONTROL"]["count"] == 1
        assert scenarios["exclude_D_NEG_EV_CONTROL"]["avg_pnl_pct"] == pytest.approx(1.5, abs=0.01)

    def test_exclusion_scenario_remove_regime(self):
        """Excluding QUIET_RANGE filters regime correctly."""
        records = [
            {
                "trade_id": "T001",
                "exit": 100.0,
                "outcome": "WIN",
                "entry_regime": "QUIET_RANGE",
                "net_pnl_pct": -1.0,
            },
            {
                "trade_id": "T002",
                "exit": 50.0,
                "outcome": "WIN",
                "entry_regime": "BULL_TREND",
                "net_pnl_pct": 0.5,
            },
        ]
        scenarios = compute_exclusion_scenarios(records)

        assert scenarios["exclude_QUIET_RANGE"]["count"] == 1
        assert scenarios["exclude_QUIET_RANGE"]["avg_pnl_pct"] == pytest.approx(0.5, abs=0.01)

    def test_exclusion_scenario_combined_improvements(self):
        """Excluding both regimes shows cumulative effect."""
        records = [
            {
                "trade_id": "T001",
                "exit": 100.0,
                "outcome": "WIN",
                "entry_regime": "QUIET_RANGE",
                "symbol": "BTC",
                "net_pnl_pct": -1.0,
            },
            {
                "trade_id": "T002",
                "exit": 100.0,
                "outcome": "WIN",
                "entry_regime": "RANGING",
                "symbol": "ETH",
                "net_pnl_pct": -0.5,
            },
            {
                "trade_id": "T003",
                "exit": 100.0,
                "outcome": "WIN",
                "entry_regime": "BULL_TREND",
                "symbol": "BTC",
                "net_pnl_pct": 1.0,
            },
            {
                "trade_id": "T004",
                "exit": 100.0,
                "outcome": "WIN",
                "entry_regime": "BULL_TREND",
                "symbol": "SOL",
                "net_pnl_pct": 0.5,
            },
        ]
        scenarios = compute_exclusion_scenarios(records)

        # Exclude both QUIET_RANGE and RANGING
        combined = scenarios["exclude_QUIET_RANGE_and_RANGING"]
        assert combined["count"] == 2  # Only BULL_TREND left
        assert combined["avg_pnl_pct"] == pytest.approx(0.75, abs=0.01)  # (1.0 + 0.5) / 2


class TestOutputGeneration:
    """Test report generation."""

    def test_generate_markdown_report_creates_valid_markdown(self):
        """Generated markdown has structure and no malformed syntax."""
        summary = {
            "total_completed_trades": 10,
            "unique_trade_ids": 10,
            "unique_symbols": 2,
            "unique_buckets": ["C_WEAK_EV_TRAIN"],
        }
        bucket_stats = {
            "C_WEAK_EV_TRAIN": {
                "count": 10,
                "win_rate": 0.5,
                "avg_pnl_pct": 0.25,
                "outcomes": {"WIN": 5, "LOSS": 5},
            }
        }
        econ_sev = {
            "WRONG_DIRECTION": {"count": 3, "percent": 30.0, "avg_pnl_pct": -0.5},
            "FEE_DOMINATED_MOVE": {"count": 2, "percent": 20.0, "avg_pnl_pct": -0.3},
        }
        regime_stats = {
            "BULL_TREND": {
                "count": 5,
                "win_rate": 0.6,
                "avg_pnl_pct": 0.4,
                "attribution": {},
            }
        }
        symbol_stats = {
            "BTC": {
                "count": 6,
                "win_rate": 0.67,
                "avg_pnl_pct": 0.3,
                "attribution": {},
            }
        }
        side_regime_matrix = {}
        exclusion_scenarios = {"exclude_D_NEG_EV_CONTROL": {"count": 9, "win_rate": 0.55}}

        md = generate_markdown_report(
            summary,
            bucket_stats,
            {},
            econ_sev,
            regime_stats,
            symbol_stats,
            side_regime_matrix,
            exclusion_scenarios,
            "NO_PATCH_COLLECT_MORE_DATA",
        )

        assert "# Paper Training Segment Quality Analysis" in md
        assert "## 1. Dataset Summary" in md
        assert "## 2. Bucket Separation" in md
        assert "## 4. Economic Severity" in md
        assert "NO_PATCH_COLLECT_MORE_DATA" in md

    def test_generate_json_summary_is_valid_json(self):
        """Generated JSON is parseable."""
        summary = {
            "total_completed_trades": 10,
            "unique_trade_ids": 10,
            "unique_symbols": 2,
            "unique_buckets": ["C_WEAK_EV_TRAIN"],
        }
        bucket_stats = {"C_WEAK_EV_TRAIN": {"count": 10, "win_rate": 0.5}}
        econ_sev = {
            "WRONG_DIRECTION": {"count": 3, "percent": 30.0},
            "FEE_DOMINATED_MOVE": {"count": 2, "percent": 20.0},
        }
        exclusion_scenarios = {"exclude_D_NEG_EV_CONTROL": {"count": 9}}

        json_data = generate_json_summary(
            summary, bucket_stats, econ_sev, exclusion_scenarios, "NO_PATCH_COLLECT_MORE_DATA"
        )

        # Should be serializable
        json_str = json.dumps(json_data, default=str)
        parsed = json.loads(json_str)

        assert parsed["recommendation"] == "NO_PATCH_COLLECT_MORE_DATA"
        assert parsed["dataset_summary"]["total_completed_trades"] == 10
        assert "bucket_stats" in parsed
        assert "economic_severity" in parsed


class TestEndToEnd:
    """Test full pipeline."""

    def test_segment_report_full_pipeline(self):
        """Load JSONL → compute all stats → generate reports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create sample JSONL
            jsonl_path = Path(tmpdir) / "data.jsonl"
            records_data = [
                {
                    "trade_id": f"T{i:04d}",
                    "exit": 100.0,
                    "outcome": "WIN" if i % 2 == 0 else "LOSS",
                    "training_bucket": "C_WEAK_EV_TRAIN" if i < 80 else "D_NEG_EV_CONTROL",
                    "symbol": f"SYM{i % 4}",
                    "side": "BUY" if i % 2 == 0 else "SELL",
                    "entry_regime": ["BULL_TREND", "QUIET_RANGE", "RANGING"][i % 3],
                    "attribution": ["NORMAL_WIN", "WRONG_DIRECTION", "FEE_DOMINATED_MOVE"][
                        i % 3
                    ],
                    "net_pnl_pct": 0.5 if i % 2 == 0 else -0.3,
                    "gross_move_pct": 1.0,
                    "mfe_pct": 1.5,
                    "mae_pct": 0.5,
                }
                for i in range(100)
            ]

            with open(jsonl_path, "w") as f:
                for r in records_data:
                    f.write(json.dumps(r) + "\n")

            # Load
            loaded = load_dataset(jsonl_path)
            assert len(loaded) == 100

            # Compute all
            summary = compute_dataset_summary(loaded)
            assert summary["total_completed_trades"] == 100

            buckets_by_name = separate_by_bucket(loaded)
            bucket_stats = {k: compute_bucket_stats(v) for k, v in buckets_by_name.items()}

            c_weak_records = buckets_by_name.get("C_WEAK_EV_TRAIN", [])
            econ_sev = compute_economic_severity(c_weak_records)
            regime_stats = compute_regime_quality(c_weak_records)
            symbol_stats = compute_symbol_quality(c_weak_records)
            side_regime_matrix = compute_side_regime_matrix(c_weak_records)
            exclusion_scenarios = compute_exclusion_scenarios(c_weak_records)

            # Recommend
            recommendation = recommend_patch(
                c_weak_records, econ_sev, regime_stats, symbol_stats, exclusion_scenarios
            )
            assert recommendation in [
                "NO_PATCH_COLLECT_MORE_DATA",
                "PRECHECK_FEE_VIABILITY",
                "PRECHECK_DIRECTION_FILTER",
                "PRECHECK_REGIME_FILTER",
                "PRECHECK_SYMBOL_FILTER",
            ]

            # Generate reports (pass records to enable per-bucket attribution)
            md = generate_markdown_report(
                summary,
                bucket_stats,
                {},
                econ_sev,
                regime_stats,
                symbol_stats,
                side_regime_matrix,
                exclusion_scenarios,
                recommendation,
                records=c_weak_records,
            )
            assert len(md) > 0
            assert "# Paper Training Segment Quality Analysis" in md

            json_summary = generate_json_summary(
                summary, bucket_stats, econ_sev, exclusion_scenarios, recommendation
            )
            assert json_summary["recommendation"] == recommendation

            # Write outputs
            md_path = Path(tmpdir) / "report.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md)
            assert md_path.exists()

            json_path = Path(tmpdir) / "summary.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_summary, f, default=str)
            assert json_path.exists()


class TestCLIRegression:
    """Test for production CLI crash regression (Task 2.5A)."""

    def test_cli_path_does_not_crash_on_real_dataset(self):
        """Regression: CLI crashed with AttributeError in generate_markdown_report.

        The issue was that generate_markdown_report() received attribution_stats
        (a dict summary) and tried to iterate it as records, causing:
        AttributeError: 'str' object has no attribute 'get'

        This test reproduces the exact main() path on synthetic production data.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create realistic production dataset
            jsonl_path = Path(tmpdir) / "combined.jsonl"
            records_data = []

            # Mix of buckets and regimes like real production
            for i in range(150):
                records_data.append(
                    {
                        "trade_id": f"T{i:05d}",
                        "exit": 100.0 + (i % 5) * 10,
                        "outcome": "WIN" if i % 3 != 0 else "LOSS",
                        "training_bucket": "C_WEAK_EV_TRAIN"
                        if i < 120
                        else "D_NEG_EV_CONTROL",
                        "symbol": f"SYM{i % 6}",
                        "side": "BUY" if i % 2 == 0 else "SELL",
                        "entry_regime": ["BULL_TREND", "BEAR_TREND", "QUIET_RANGE", "RANGING"][
                            i % 4
                        ],
                        "attribution": [
                            "NORMAL_WIN",
                            "WRONG_DIRECTION",
                            "FEE_DOMINATED_MOVE",
                        ][i % 3],
                        "net_pnl_pct": 0.3 + (i % 10) * 0.05,
                        "gross_move_pct": 1.0 + (i % 5) * 0.2,
                        "mfe_pct": 1.5 + (i % 3) * 0.5,
                        "mae_pct": 0.5 + (i % 4) * 0.3,
                    }
                )

            # Write JSONL
            with open(jsonl_path, "w") as f:
                for r in records_data:
                    f.write(json.dumps(r) + "\n")

            # Reproduce main() path exactly
            records = load_dataset(jsonl_path)
            assert len(records) == 150

            summary = compute_dataset_summary(records)
            buckets_by_name = separate_by_bucket(records)
            bucket_stats = {k: compute_bucket_stats(v) for k, v in buckets_by_name.items()}

            c_weak_records = buckets_by_name.get("C_WEAK_EV_TRAIN", [])
            assert len(c_weak_records) > 0

            attribution_stats = compute_attribution_stats(c_weak_records)
            economic_severity = compute_economic_severity(c_weak_records)
            regime_stats = compute_regime_quality(c_weak_records)
            symbol_stats = compute_symbol_quality(c_weak_records)
            side_regime_matrix = compute_side_regime_matrix(c_weak_records)
            exclusion_scenarios = compute_exclusion_scenarios(c_weak_records)

            recommendation = recommend_patch(
                c_weak_records,
                economic_severity,
                regime_stats,
                symbol_stats,
                exclusion_scenarios,
            )

            # This should NOT crash with AttributeError
            md_report = generate_markdown_report(
                summary,
                bucket_stats,
                attribution_stats,
                economic_severity,
                regime_stats,
                symbol_stats,
                side_regime_matrix,
                exclusion_scenarios,
                recommendation,
                records=c_weak_records,
            )

            # Verify output is valid
            assert len(md_report) > 0
            assert "# Paper Training Segment Quality Analysis" in md_report
            assert "## 2. Bucket Separation" in md_report
            assert "## 3. Attribution by Bucket" in md_report
            assert "## 4. Economic Severity" in md_report

            json_summary = generate_json_summary(
                summary,
                bucket_stats,
                economic_severity,
                exclusion_scenarios,
                recommendation,
            )

            # Write outputs
            md_path = Path(tmpdir) / "report.md"
            json_path = Path(tmpdir) / "summary.json"

            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_report)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(json_summary, f, default=str)

            assert md_path.exists()
            assert json_path.exists()

            # Verify content
            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()
            assert len(md_content) > 0
            assert md_content.count("###") >= 2  # At least section headers


class TestPercentFormatting:
    """Test percent field formatting (P1.1AT regression: don't multiply by 100 twice)."""

    def test_bucket_avg_pnl_pct_not_scaled_100x(self):
        """avg_pnl_pct=-0.174 should display as -0.17%, not -17.40%."""
        records = [
            {
                "trade_id": "T001",
                "exit": 100.0,
                "outcome": "LOSS",
                "net_pnl_pct": -0.174,  # -0.174%
                "training_bucket": "C_WEAK_EV_TRAIN",
            },
        ]

        # Verify markdown formatting does NOT multiply by 100
        summary = compute_dataset_summary(records)
        by_bucket = separate_by_bucket(records)

        # Compute bucket stats from separated buckets
        bucket_stats = {}
        for bucket, bucket_records in by_bucket.items():
            bucket_stats[bucket] = compute_bucket_stats(bucket_records)

        regime_stats = compute_regime_quality(records)
        symbol_stats = compute_symbol_quality(records)
        side_regime = compute_side_regime_matrix(records)
        excl_scenarios = compute_exclusion_scenarios(records)

        md_report = generate_markdown_report(
            summary,
            bucket_stats,
            {},
            {},
            regime_stats,
            symbol_stats,
            side_regime,
            excl_scenarios,
            "No patch recommended",
            records=None,
        )

        # Check that -0.17% appears (not -17.40%)
        assert "-0.17%" in md_report, f"Expected -0.17% in report, got: {md_report}"
        assert "-17.40%" not in md_report, f"Should not have -17.40%, got: {md_report}"
        assert "-17.4%" not in md_report, f"Should not have -17.4%, got: {md_report}"

    def test_economic_severity_pnl_and_gross_move_not_scaled(self):
        """avg_pnl_pct and avg_gross_move_pct should not be multiplied by 100."""
        records = [
            {
                "trade_id": "T001",
                "exit": 100.0,
                "outcome": "LOSS",
                "net_pnl_pct": -0.15,
                "gross_move_pct": 0.5,
                "mfe_pct": 0.8,
                "mae_pct": -0.3,
                "attribution": "WRONG_DIRECTION",
            },
            {
                "trade_id": "T002",
                "exit": 105.0,
                "outcome": "WIN",
                "net_pnl_pct": 0.10,
                "gross_move_pct": 0.45,
                "mfe_pct": 0.7,
                "mae_pct": -0.2,
                "attribution": "WRONG_DIRECTION",
            },
        ]

        econ_severity = compute_economic_severity(records)
        wd = econ_severity["WRONG_DIRECTION"]

        # avg_pnl_pct should be around -0.025
        assert abs(wd["avg_pnl_pct"] - (-0.025)) < 0.01
        # avg_gross_move_pct should be around 0.475
        assert abs(wd["avg_gross_move_pct"] - 0.475) < 0.01

        summary = compute_dataset_summary(records)
        by_bucket = separate_by_bucket(records)

        # Compute bucket stats from separated buckets
        bucket_stats = {}
        for bucket, bucket_records in by_bucket.items():
            bucket_stats[bucket] = compute_bucket_stats(bucket_records)

        regime_stats = compute_regime_quality(records)
        symbol_stats = compute_symbol_quality(records)
        side_regime = compute_side_regime_matrix(records)
        excl_scenarios = compute_exclusion_scenarios(records)

        md_report = generate_markdown_report(
            summary,
            bucket_stats,
            {},
            econ_severity,
            regime_stats,
            symbol_stats,
            side_regime,
            excl_scenarios,
            "No patch recommended",
            records=None,
        )

        # Check formatting: should display -0.02% or -0.03%, not -2.50%
        # (exact value depends on rounding)
        assert "-2.50%" not in md_report, f"Should not have -2.50%, got: {md_report}"
        # avg_gross_move_pct around 0.475 should display as ~0.47% or 0.48%
        assert "0.4" in md_report or "0.5" in md_report  # Reasonable percentage display

    def test_win_rate_still_scaled_by_100(self):
        """win_rate (ratio 0-1) should still be multiplied by 100 for display."""
        records = [
            {
                "trade_id": "T001",
                "exit": 100.0,
                "outcome": "WIN",
                "net_pnl_pct": 0.05,
                "training_bucket": "TEST",
            },
            {
                "trade_id": "T002",
                "exit": 105.0,
                "outcome": "LOSS",
                "net_pnl_pct": -0.05,
                "training_bucket": "TEST",
            },
        ]

        summary = compute_dataset_summary(records)
        by_bucket = separate_by_bucket(records)

        # Compute bucket stats from separated buckets
        bucket_stats = {}
        for bucket, bucket_records in by_bucket.items():
            bucket_stats[bucket] = compute_bucket_stats(bucket_records)

        # 1 win out of 2 = 0.5 win_rate (ratio)
        assert bucket_stats["TEST"]["win_rate"] == 0.5

        regime_stats = compute_regime_quality(records)
        symbol_stats = compute_symbol_quality(records)
        side_regime = compute_side_regime_matrix(records)
        excl_scenarios = compute_exclusion_scenarios(records)

        md_report = generate_markdown_report(
            summary,
            bucket_stats,
            {},
            {},
            regime_stats,
            symbol_stats,
            side_regime,
            excl_scenarios,
            "No patch recommended",
            records=None,
        )

        # win_rate should display as 50.0%, not 0.5%
        assert "50.0%" in md_report, f"Expected 50.0% win rate, got: {md_report}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
