#!/usr/bin/env python3
"""
Aggregate research snapshot datasets from multiple JSONL files.

Reads all paper_training_dataset.jsonl files from data/research/snapshots/*/
and merges them by trade_id, keeping the most complete record.

Offline research tooling only. No Firebase writes. No trading logic changes.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


def count_nonnull_fields(record: dict) -> int:
    """Count non-null fields in a record."""
    return sum(1 for v in record.values() if v is not None)


def is_more_complete(candidate: dict, current: dict) -> bool:
    """
    Determine if candidate record is more complete than current.

    Preference order:
    1. Has outcome (completed trade)
    2. Has attribution (economic analysis)
    3. Has symbol/side/entry_regime (metadata)
    4. More non-null fields overall
    """
    cand_has_outcome = candidate.get("outcome") is not None
    curr_has_outcome = current.get("outcome") is not None

    if cand_has_outcome and not curr_has_outcome:
        return True
    if not cand_has_outcome and curr_has_outcome:
        return False

    cand_has_attrib = candidate.get("attribution") is not None
    curr_has_attrib = current.get("attribution") is not None

    if cand_has_attrib and not curr_has_attrib:
        return True
    if not cand_has_attrib and curr_has_attrib:
        return False

    cand_has_metadata = all(
        candidate.get(k) is not None
        for k in ("symbol", "side", "entry_regime")
    )
    curr_has_metadata = all(
        current.get(k) is not None
        for k in ("symbol", "side", "entry_regime")
    )

    if cand_has_metadata and not curr_has_metadata:
        return True
    if not cand_has_metadata and curr_has_metadata:
        return False

    return count_nonnull_fields(candidate) > count_nonnull_fields(current)


def merge_records(current: dict, candidate: dict) -> dict:
    """
    Merge two records, preferring more complete one.

    If candidate is more complete, use it as base and backfill with current's non-null values.
    Otherwise, keep current as base and backfill with candidate's non-null values.
    """
    if is_more_complete(candidate, current):
        merged = dict(candidate)
        for key, value in current.items():
            if key not in merged or merged[key] is None:
                merged[key] = value
        return merged
    else:
        merged = dict(current)
        for key, value in candidate.items():
            if key not in merged or merged[key] is None:
                merged[key] = value
        return merged


def aggregate_snapshots(
    snapshots_dir: Path,
    output_path: Path,
) -> dict:
    """
    Aggregate all snapshot JSONL files.

    Args:
        snapshots_dir: Path to data/research/snapshots/ directory
        output_path: Path to output combined JSONL file

    Returns:
        dict with aggregation stats
    """
    snapshots_dir = Path(snapshots_dir)
    output_path = Path(output_path)

    if not snapshots_dir.exists():
        print(f"Error: snapshots directory not found: {snapshots_dir}", file=sys.stderr)
        sys.exit(1)

    # Find all snapshot JSONL files
    snapshot_files = sorted(snapshots_dir.glob("*/paper_training_dataset.jsonl"))

    if not snapshot_files:
        print(f"Warning: no snapshot files found in {snapshots_dir}", file=sys.stderr)
        snapshot_files = []

    # Read and aggregate records
    records_by_id = {}
    total_input = 0
    duplicates = 0

    for snapshot_file in snapshot_files:
        try:
            with open(snapshot_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)
                        trade_id = record.get("trade_id")

                        if not trade_id:
                            continue

                        total_input += 1

                        if trade_id in records_by_id:
                            duplicates += 1
                            records_by_id[trade_id] = merge_records(
                                records_by_id[trade_id],
                                record
                            )
                        else:
                            records_by_id[trade_id] = record

                    except json.JSONDecodeError:
                        print(f"Warning: invalid JSON in {snapshot_file}: {line[:80]}", file=sys.stderr)
                        continue

        except Exception as e:
            print(f"Error reading {snapshot_file}: {e}", file=sys.stderr)
            continue

    # Categorize records
    completed_trades = []
    incomplete_records = []

    for record in records_by_id.values():
        # Completed trade: has both exit price and outcome
        if record.get("exit") is not None and record.get("outcome") is not None:
            completed_trades.append(record)
        else:
            incomplete_records.append(record)

    # Write output JSONL
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        for record in completed_trades:
            f.write(json.dumps(record, default=str) + "\n")
        for record in incomplete_records:
            f.write(json.dumps(record, default=str) + "\n")

    # Report stats
    stats = {
        "total_input_records": total_input,
        "unique_trade_ids": len(records_by_id),
        "completed_trades": len(completed_trades),
        "incomplete_records": len(incomplete_records),
        "duplicate_count": duplicates,
        "output_file": str(output_path),
    }

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Aggregate research snapshot datasets"
    )
    parser.add_argument(
        "--snapshots-dir",
        default="data/research/snapshots",
        help="Path to snapshots directory (default: data/research/snapshots)",
    )
    parser.add_argument(
        "--output",
        default="data/research/combined_paper_training_dataset.jsonl",
        help="Output JSONL path (default: data/research/combined_paper_training_dataset.jsonl)",
    )

    args = parser.parse_args()

    stats = aggregate_snapshots(
        Path(args.snapshots_dir),
        Path(args.output),
    )

    # Print stats
    print(f"Total input records: {stats['total_input_records']}")
    print(f"Unique trade_ids: {stats['unique_trade_ids']}")
    print(f"Completed trades: {stats['completed_trades']}")
    print(f"Incomplete records: {stats['incomplete_records']}")
    print(f"Duplicates handled: {stats['duplicate_count']}")
    print(f"Output: {stats['output_file']}")


if __name__ == "__main__":
    main()
