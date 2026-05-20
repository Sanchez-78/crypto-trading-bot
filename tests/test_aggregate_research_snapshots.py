"""
Tests for research snapshot aggregation.

Ensures:
- Duplicate trade_ids are merged correctly
- Most complete record is retained
- Metadata backfilled if one record has it
- Output is valid JSONL
- Empty/missing directories handled gracefully
"""

import json
import tempfile
from pathlib import Path

import pytest

from scripts.aggregate_research_snapshots import (
    aggregate_snapshots,
    count_nonnull_fields,
    is_more_complete,
    merge_records,
)


class TestCountNonnullFields:
    """Test field counting utility."""

    def test_count_all_null(self):
        record = {"a": None, "b": None, "c": None}
        assert count_nonnull_fields(record) == 0

    def test_count_mixed(self):
        record = {"a": 1, "b": None, "c": "value", "d": None}
        assert count_nonnull_fields(record) == 2

    def test_count_all_nonnull(self):
        record = {"a": 1, "b": "x", "c": 0, "d": False}
        assert count_nonnull_fields(record) == 4


class TestIsMoreComplete:
    """Test completeness comparison."""

    def test_outcome_is_deciding(self):
        """Record with outcome is more complete than one without."""
        candidate = {"outcome": "WIN", "trade_id": "T001"}
        current = {"trade_id": "T001", "entry": 100.0}
        assert is_more_complete(candidate, current) is True

    def test_no_outcome_loses(self):
        """Record without outcome loses to one with outcome."""
        candidate = {"trade_id": "T001", "entry": 100.0}
        current = {"outcome": "WIN", "trade_id": "T001"}
        assert is_more_complete(candidate, current) is False

    def test_attribution_tiebreaker(self):
        """When outcome tied, attribution decides."""
        candidate = {"outcome": "WIN", "attribution": "tp_hit", "trade_id": "T001"}
        current = {"outcome": "WIN", "trade_id": "T001"}
        assert is_more_complete(candidate, current) is True

    def test_metadata_tiebreaker(self):
        """When outcome+attribution tied, metadata decides."""
        candidate = {
            "outcome": "WIN",
            "attribution": "tp_hit",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "entry_regime": "BULL",
            "trade_id": "T001",
        }
        current = {"outcome": "WIN", "attribution": "tp_hit", "trade_id": "T001"}
        assert is_more_complete(candidate, current) is True

    def test_field_count_final_tiebreaker(self):
        """When all else tied, field count decides."""
        candidate = {"trade_id": "T001", "a": 1, "b": 2, "c": 3}
        current = {"trade_id": "T001", "a": 1}
        assert is_more_complete(candidate, current) is True


class TestMergeRecords:
    """Test record merging logic."""

    def test_merge_keeps_more_complete(self):
        """Merge prefers more complete record."""
        current = {"trade_id": "T001", "entry": 100.0}
        candidate = {"trade_id": "T001", "outcome": "WIN"}
        merged = merge_records(current, candidate)
        assert merged["outcome"] == "WIN"
        assert merged["entry"] == 100.0  # backfilled from current

    def test_merge_backfills_metadata(self):
        """Merge backfills null fields from less complete record."""
        current = {
            "trade_id": "T001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "outcome": None,
        }
        candidate = {"trade_id": "T001", "outcome": "WIN"}
        merged = merge_records(current, candidate)
        assert merged["outcome"] == "WIN"
        assert merged["symbol"] == "BTCUSDT"  # backfilled
        assert merged["side"] == "BUY"  # backfilled

    def test_merge_doesnt_overwrite_with_none(self):
        """Merge doesn't overwrite existing values with None."""
        current = {"trade_id": "T001", "entry": 100.0, "exit": 101.0}
        candidate = {"trade_id": "T001", "entry": None, "exit": 102.0}
        merged = merge_records(current, candidate)
        # Current has more non-null fields (3 vs 2), becomes base
        assert merged["exit"] == 101.0  # from current
        assert merged["entry"] == 100.0  # from current


class TestAggregateSnapshots:
    """Test full aggregation flow."""

    def test_aggregate_single_snapshot(self):
        """Aggregation works with single snapshot file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create snapshot directory structure
            snap_dir = Path(tmpdir) / "snapshots" / "snap_001"
            snap_dir.mkdir(parents=True)

            # Write sample JSONL
            snapshot_file = snap_dir / "paper_training_dataset.jsonl"
            records = [
                {"trade_id": "T001", "symbol": "BTC", "outcome": "WIN", "exit": 100.0},
                {"trade_id": "T002", "symbol": "ETH", "outcome": "LOSS", "exit": 50.0},
            ]
            with open(snapshot_file, "w") as f:
                for record in records:
                    f.write(json.dumps(record) + "\n")

            # Aggregate
            output_file = Path(tmpdir) / "combined.jsonl"
            stats = aggregate_snapshots(
                Path(tmpdir) / "snapshots",
                output_file,
            )

            # Verify stats
            assert stats["total_input_records"] == 2
            assert stats["unique_trade_ids"] == 2
            assert stats["completed_trades"] == 2
            assert stats["incomplete_records"] == 0
            assert stats["duplicate_count"] == 0

            # Verify output
            output_records = []
            with open(output_file, "r") as f:
                for line in f:
                    output_records.append(json.loads(line))
            assert len(output_records) == 2

    def test_aggregate_deduplicates(self):
        """Aggregation deduplicates by trade_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = Path(tmpdir) / "snapshots" / "snap_001"
            snap_dir.mkdir(parents=True)

            # Write two versions of same trade
            snapshot_file = snap_dir / "paper_training_dataset.jsonl"
            with open(snapshot_file, "w") as f:
                f.write(json.dumps({"trade_id": "T001", "symbol": "BTC"}) + "\n")
                f.write(
                    json.dumps({"trade_id": "T001", "outcome": "WIN", "exit": 100.0})
                    + "\n"
                )

            output_file = Path(tmpdir) / "combined.jsonl"
            stats = aggregate_snapshots(
                Path(tmpdir) / "snapshots",
                output_file,
            )

            # Should deduplicate
            assert stats["total_input_records"] == 2
            assert stats["unique_trade_ids"] == 1
            assert stats["duplicate_count"] == 1

            # Verify merged record has both fields
            with open(output_file, "r") as f:
                merged = json.loads(f.readline())
            assert merged["symbol"] == "BTC"
            assert merged["outcome"] == "WIN"
            assert merged["exit"] == 100.0

    def test_aggregate_multiple_snapshots(self):
        """Aggregation merges records from multiple snapshot directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two snapshot directories
            snap_dir_1 = Path(tmpdir) / "snapshots" / "snap_001"
            snap_dir_2 = Path(tmpdir) / "snapshots" / "snap_002"
            snap_dir_1.mkdir(parents=True)
            snap_dir_2.mkdir(parents=True)

            # Write records to snap_001
            with open(snap_dir_1 / "paper_training_dataset.jsonl", "w") as f:
                f.write(json.dumps({"trade_id": "T001", "symbol": "BTC"}) + "\n")
                f.write(json.dumps({"trade_id": "T002", "symbol": "ETH"}) + "\n")

            # Write records to snap_002 (T001 is duplicate, T003 is new)
            with open(snap_dir_2 / "paper_training_dataset.jsonl", "w") as f:
                f.write(
                    json.dumps({"trade_id": "T001", "outcome": "WIN", "exit": 100.0})
                    + "\n"
                )
                f.write(json.dumps({"trade_id": "T003", "symbol": "ADA"}) + "\n")

            output_file = Path(tmpdir) / "combined.jsonl"
            stats = aggregate_snapshots(
                Path(tmpdir) / "snapshots",
                output_file,
            )

            assert stats["total_input_records"] == 4
            assert stats["unique_trade_ids"] == 3
            assert stats["duplicate_count"] == 1

    def test_aggregate_completed_vs_incomplete(self):
        """Aggregation separates completed vs incomplete records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = Path(tmpdir) / "snapshots" / "snap_001"
            snap_dir.mkdir(parents=True)

            snapshot_file = snap_dir / "paper_training_dataset.jsonl"
            with open(snapshot_file, "w") as f:
                # Completed: has exit and outcome
                f.write(
                    json.dumps(
                        {
                            "trade_id": "T001",
                            "exit": 100.0,
                            "outcome": "WIN",
                        }
                    )
                    + "\n"
                )
                # Incomplete: missing outcome
                f.write(
                    json.dumps(
                        {
                            "trade_id": "T002",
                            "exit": None,
                            "outcome": None,
                        }
                    )
                    + "\n"
                )
                # Incomplete: missing exit
                f.write(
                    json.dumps({"trade_id": "T003", "exit": None, "outcome": "WIN"})
                    + "\n"
                )

            output_file = Path(tmpdir) / "combined.jsonl"
            stats = aggregate_snapshots(
                Path(tmpdir) / "snapshots",
                output_file,
            )

            assert stats["completed_trades"] == 1
            assert stats["incomplete_records"] == 2

    def test_aggregate_missing_directory(self):
        """Aggregation exits gracefully with missing snapshots directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "combined.jsonl"

            with pytest.raises(SystemExit):
                aggregate_snapshots(
                    Path(tmpdir) / "nonexistent",
                    output_file,
                )

    def test_aggregate_empty_directory(self):
        """Aggregation handles empty snapshots directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = Path(tmpdir) / "snapshots"
            snap_dir.mkdir()

            output_file = Path(tmpdir) / "combined.jsonl"
            stats = aggregate_snapshots(snap_dir, output_file)

            assert stats["total_input_records"] == 0
            assert stats["unique_trade_ids"] == 0
            assert stats["completed_trades"] == 0

    def test_aggregate_invalid_json_skipped(self):
        """Aggregation skips invalid JSON lines gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = Path(tmpdir) / "snapshots" / "snap_001"
            snap_dir.mkdir(parents=True)

            snapshot_file = snap_dir / "paper_training_dataset.jsonl"
            with open(snapshot_file, "w") as f:
                f.write(json.dumps({"trade_id": "T001", "exit": 100.0}) + "\n")
                f.write("invalid json line\n")  # Invalid JSON
                f.write(json.dumps({"trade_id": "T002", "exit": 50.0}) + "\n")

            output_file = Path(tmpdir) / "combined.jsonl"
            stats = aggregate_snapshots(
                Path(tmpdir) / "snapshots",  # Pass parent snapshots dir
                output_file,
            )

            # Should skip invalid line
            assert stats["total_input_records"] == 2
            assert stats["unique_trade_ids"] == 2

    def test_aggregate_output_is_valid_jsonl(self):
        """Output file is valid JSONL (one JSON object per line)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = Path(tmpdir) / "snapshots" / "snap_001"
            snap_dir.mkdir(parents=True)

            snapshot_file = snap_dir / "paper_training_dataset.jsonl"
            with open(snapshot_file, "w") as f:
                f.write(json.dumps({"trade_id": "T001", "symbol": "BTC"}) + "\n")
                f.write(json.dumps({"trade_id": "T002", "symbol": "ETH"}) + "\n")

            output_file = Path(tmpdir) / "combined.jsonl"
            aggregate_snapshots(snap_dir, output_file)

            # Verify JSONL format
            with open(output_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:  # Skip empty lines
                        record = json.loads(line)  # Should not raise
                        assert "trade_id" in record


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
