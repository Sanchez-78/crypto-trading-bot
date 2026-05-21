#!/usr/bin/env python3
"""
Offline segment quality analysis for paper training data.

Analyzes completed paper training trades by bucket, regime, symbol, and attribution
to identify which patch to recommend next (if any).

Offline research only. No Firebase writes. No trading changes.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional


def _safe_float(v, default=0.0):
    try:
        f = float(v)
        return default if (f != f or f == float('inf') or f == float('-inf')) else f
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def load_dataset(jsonl_path: Path) -> list:
    """Load JSONL dataset, return only completed trades (exit + outcome)."""
    records = []
    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    # Keep only completed trades
                    if record.get("exit") is not None and record.get("outcome") is not None:
                        records.append(record)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Error loading {jsonl_path}: {e}", file=sys.stderr)
        return []
    return records


def compute_dataset_summary(records: list) -> dict:
    """Compute basic dataset stats."""
    if not records:
        return {
            "total_completed_trades": 0,
            "unique_trade_ids": 0,
            "unique_symbols": 0,
            "unique_buckets": [],
        }

    trade_ids = set(r.get("trade_id") for r in records if r.get("trade_id"))
    symbols = set(r.get("symbol") for r in records if r.get("symbol"))
    buckets = set(r.get("training_bucket") or "UNKNOWN" for r in records)

    return {
        "total_completed_trades": len(records),
        "unique_trade_ids": len(trade_ids),
        "unique_symbols": len(symbols),
        "unique_buckets": sorted(buckets),
    }


def separate_by_bucket(records: list) -> dict:
    """Separate records by training_bucket."""
    buckets = defaultdict(list)
    for r in records:
        bucket = r.get("training_bucket") or "UNKNOWN"
        buckets[bucket].append(r)
    return dict(buckets)


def compute_bucket_stats(records: list) -> dict:
    """Compute stats for a bucket."""
    if not records:
        return {
            "count": 0,
            "win_rate": None,
            "avg_pnl_pct": None,
            "outcomes": {},
        }

    outcomes = defaultdict(int)
    for r in records:
        outcome = r.get("outcome", "UNKNOWN")
        outcomes[outcome] += 1

    total = len(records)
    wins = outcomes.get("WIN", 0)
    win_rate = wins / total if total > 0 else 0

    pnls = [_safe_float(r.get("net_pnl_pct", 0)) for r in records]
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0

    return {
        "count": total,
        "win_rate": round(win_rate, 4),
        "avg_pnl_pct": round(avg_pnl, 4),
        "outcomes": dict(outcomes),
    }


def compute_attribution_stats(records: list) -> dict:
    """Compute attribution breakdown and severity."""
    if not records:
        return {
            "total": 0,
            "by_attribution": {},
        }

    by_attrib = defaultdict(list)
    for r in records:
        attrib = r.get("attribution", "UNKNOWN")
        by_attrib[attrib].append(r)

    stats = {"total": len(records), "by_attribution": {}}

    for attrib, recs in by_attrib.items():
        pnls = [_safe_float(r.get("net_pnl_pct", 0)) for r in recs]
        stats["by_attribution"][attrib] = {
            "count": len(recs),
            "percent": round(100 * len(recs) / len(records), 1),
            "avg_pnl_pct": round(sum(pnls) / len(pnls) if pnls else 0, 4),
        }

    return stats


def compute_economic_severity(records: list) -> dict:
    """Compare WRONG_DIRECTION vs FEE_DOMINATED_MOVE severity."""
    wrong_dir = [r for r in records if r.get("attribution") == "WRONG_DIRECTION"]
    fee_dom = [r for r in records if r.get("attribution") == "FEE_DOMINATED_MOVE"]

    def stats_for_list(lst):
        if not lst:
            return {
                "count": 0,
                "percent": 0,
                "avg_pnl_pct": None,
                "avg_gross_move_pct": None,
                "avg_mfe_pct": None,
                "avg_mae_pct": None,
            }
        pnls = [_safe_float(r.get("net_pnl_pct", 0)) for r in lst]
        gross = [_safe_float(r.get("gross_move_pct", 0)) for r in lst]
        mfe = [_safe_float(r.get("mfe_pct", 0)) for r in lst]
        mae = [_safe_float(r.get("mae_pct", 0)) for r in lst]
        total = len(records)
        return {
            "count": len(lst),
            "percent": round(100 * len(lst) / total if total > 0 else 0, 1),
            "avg_pnl_pct": round(sum(pnls) / len(pnls) if pnls else 0, 4),
            "avg_gross_move_pct": round(sum(gross) / len(gross) if gross else 0, 4),
            "avg_mfe_pct": round(sum(mfe) / len(mfe) if mfe else 0, 4),
            "avg_mae_pct": round(sum(mae) / len(mae) if mae else 0, 4),
        }

    return {
        "WRONG_DIRECTION": stats_for_list(wrong_dir),
        "FEE_DOMINATED_MOVE": stats_for_list(fee_dom),
    }


def compute_regime_quality(records: list) -> dict:
    """Analyze quality by entry_regime."""
    by_regime = defaultdict(list)
    for r in records:
        regime = r.get("entry_regime", "UNKNOWN")
        by_regime[regime].append(r)

    stats = {}
    for regime, recs in by_regime.items():
        bucket_stats = compute_bucket_stats(recs)
        attrib_stats = compute_attribution_stats(recs)
        stats[regime] = {
            **bucket_stats,
            "attribution": attrib_stats["by_attribution"],
        }

    return stats


def compute_symbol_quality(records: list) -> dict:
    """Analyze quality by symbol."""
    by_symbol = defaultdict(list)
    for r in records:
        symbol = r.get("symbol", "UNKNOWN")
        by_symbol[symbol].append(r)

    stats = {}
    for symbol, recs in by_symbol.items():
        bucket_stats = compute_bucket_stats(recs)
        attrib_stats = compute_attribution_stats(recs)
        stats[symbol] = {
            **bucket_stats,
            "attribution": attrib_stats["by_attribution"],
        }

    return stats


def compute_side_regime_matrix(records: list) -> dict:
    """Analyze BUY/SELL x regime combinations."""
    matrix = defaultdict(list)
    for r in records:
        side = r.get("side", "UNKNOWN")
        regime = r.get("entry_regime", "UNKNOWN")
        key = f"{side}_{regime}"
        matrix[key].append(r)

    stats = {}
    for key, recs in matrix.items():
        bucket_stats = compute_bucket_stats(recs)
        attrib_stats = compute_attribution_stats(recs)
        stats[key] = {
            **bucket_stats,
            "attribution": attrib_stats["by_attribution"],
        }

    return stats


def compute_exclusion_scenarios(records: list) -> dict:
    """Compute stats for various exclusion scenarios."""
    scenarios = {}

    # Exclude D_NEG_EV_CONTROL
    filtered = [r for r in records if (r.get("training_bucket") or "UNKNOWN") != "D_NEG_EV_CONTROL"]
    scenarios["exclude_D_NEG_EV_CONTROL"] = compute_bucket_stats(filtered)

    # Exclude QUIET_RANGE
    filtered = [r for r in records if r.get("entry_regime") != "QUIET_RANGE"]
    scenarios["exclude_QUIET_RANGE"] = compute_bucket_stats(filtered)

    # Exclude RANGING
    filtered = [r for r in records if r.get("entry_regime") != "RANGING"]
    scenarios["exclude_RANGING"] = compute_bucket_stats(filtered)

    # Exclude both QUIET_RANGE and RANGING
    filtered = [r for r in records if r.get("entry_regime") not in ("QUIET_RANGE", "RANGING")]
    scenarios["exclude_QUIET_RANGE_and_RANGING"] = compute_bucket_stats(filtered)

    # Exclude symbols with < 5 trades
    symbol_counts = defaultdict(int)
    for r in records:
        symbol_counts[r.get("symbol", "UNKNOWN")] += 1
    filtered = [r for r in records if symbol_counts.get(r.get("symbol", "UNKNOWN"), 0) >= 5]
    scenarios["exclude_symbols_with_n_lt_5"] = compute_bucket_stats(filtered)

    return scenarios


def recommend_patch(
    c_weak_ev_records: list,
    economic_severity: dict,
    regime_stats: dict,
    symbol_stats: dict,
    exclusion_scenarios: dict,
) -> str:
    """
    Recommend which patch to precheck next.

    Returns one of:
    - NO_PATCH_COLLECT_MORE_DATA
    - PRECHECK_FEE_VIABILITY
    - PRECHECK_DIRECTION_FILTER
    - PRECHECK_REGIME_FILTER
    - PRECHECK_SYMBOL_FILTER
    """
    if not c_weak_ev_records or len(c_weak_ev_records) < 100:
        return "NO_PATCH_COLLECT_MORE_DATA"

    # Check economic severity
    fee_stats = economic_severity.get("FEE_DOMINATED_MOVE", {})
    wd_stats = economic_severity.get("WRONG_DIRECTION", {})

    fee_percent = fee_stats.get("percent", 0)
    wd_percent = wd_stats.get("percent", 0)

    # If FEE_DOMINATED_MOVE > 50% and WRONG_DIRECTION < 35%
    if fee_percent > 50 and wd_percent < 35:
        return "PRECHECK_FEE_VIABILITY"

    # If WRONG_DIRECTION > 50% and FEE_DOMINATED_MOVE < 35%
    if wd_percent > 50 and fee_percent < 35:
        return "PRECHECK_DIRECTION_FILTER"

    # Check regime filtering
    for regime, stats in regime_stats.items():
        if regime in ("QUIET_RANGE", "RANGING"):
            if stats.get("count", 0) >= 20 and stats.get("win_rate", 0) == 0:
                # Check if exclusion helps
                exclusion_key = f"exclude_{regime}" if regime != "QUIET_RANGE_and_RANGING" else "exclude_QUIET_RANGE_and_RANGING"
                excl_stats = exclusion_scenarios.get(exclusion_key, {})
                excl_pnl = excl_stats.get("avg_pnl_pct", 0)
                overall_pnl = sum(_safe_float(r.get("net_pnl_pct", 0)) for r in c_weak_ev_records) / len(c_weak_ev_records) if c_weak_ev_records else 0
                if excl_pnl > overall_pnl + 0.5:  # Material improvement
                    return "PRECHECK_REGIME_FILTER"

    # Check symbol filtering
    for symbol, stats in symbol_stats.items():
        if stats.get("count", 0) >= 20:
            attrib = stats.get("attribution", {})
            for cause, cause_stats in attrib.items():
                if cause_stats.get("percent", 0) > 50:
                    cause_pnl = cause_stats.get("avg_pnl_pct", 0)
                    overall_pnl = sum(_safe_float(r.get("net_pnl_pct", 0)) for r in c_weak_ev_records) / len(c_weak_ev_records) if c_weak_ev_records else 0
                    if cause_pnl < overall_pnl - 0.5:  # Materially worse
                        return "PRECHECK_SYMBOL_FILTER"

    return "NO_PATCH_COLLECT_MORE_DATA"


def generate_markdown_report(
    summary: dict,
    bucket_stats: dict,
    attribution_stats: dict,
    economic_severity: dict,
    regime_stats: dict,
    symbol_stats: dict,
    side_regime_matrix: dict,
    exclusion_scenarios: dict,
    recommendation: str,
) -> str:
    """Generate markdown report."""
    md = []

    md.append("# Paper Training Segment Quality Analysis\n")
    md.append(f"**Purpose:** Identify which patch to precheck next (if any)\n")
    md.append(f"**Recommendation:** `{recommendation}`\n\n")

    # Dataset Summary
    md.append("## 1. Dataset Summary\n")
    md.append(f"- **Total completed trades:** {summary['total_completed_trades']}\n")
    md.append(f"- **Unique trade IDs:** {summary['unique_trade_ids']}\n")
    md.append(f"- **Unique symbols:** {summary['unique_symbols']}\n")
    md.append(f"- **Buckets:** {', '.join(summary['unique_buckets'])}\n\n")

    # Bucket Separation
    md.append("## 2. Bucket Separation\n")
    md.append("⚠️ **CRITICAL:** D_NEG_EV_CONTROL data is NOT mixed into learning-quality decisions.\n\n")
    for bucket, stats in sorted(bucket_stats.items()):
        md.append(f"### {bucket}\n")
        md.append(f"- **Count:** {stats['count']}\n")
        if stats['count'] > 0:
            md.append(f"- **Win rate:** {stats['win_rate']*100:.1f}%\n")
            md.append(f"- **Avg PnL:** {stats['avg_pnl_pct']*100:.2f}%\n")
        md.append(f"- **Outcomes:** {stats['outcomes']}\n\n")

    # Attribution by Bucket
    md.append("## 3. Attribution by Bucket\n")
    for bucket in sorted(bucket_stats.keys()):
        recs = [r for r in (attribution_stats or []) if (r.get("training_bucket") or "UNKNOWN") == bucket]
        if not recs and attribution_stats:
            continue
        md.append(f"### {bucket}\n")
        # This would need refactoring to properly show per-bucket attribution
        md.append("(See economic severity for main attribution analysis)\n\n")

    # Economic Severity
    md.append("## 4. Economic Severity\n")
    wd = economic_severity.get("WRONG_DIRECTION", {})
    fd = economic_severity.get("FEE_DOMINATED_MOVE", {})

    md.append("### WRONG_DIRECTION\n")
    md.append(f"- **Count:** {wd.get('count', 0)} ({wd.get('percent', 0):.1f}%)\n")
    md.append(f"- **Avg net PnL:** {wd.get('avg_pnl_pct', 0)*100:.2f}%\n")
    md.append(f"- **Avg gross move:** {wd.get('avg_gross_move_pct', 0)*100:.2f}%\n\n")

    md.append("### FEE_DOMINATED_MOVE\n")
    md.append(f"- **Count:** {fd.get('count', 0)} ({fd.get('percent', 0):.1f}%)\n")
    md.append(f"- **Avg net PnL:** {fd.get('avg_pnl_pct', 0)*100:.2f}%\n")
    md.append(f"- **Avg gross move:** {fd.get('avg_gross_move_pct', 0)*100:.2f}%\n\n")

    if wd.get('percent', 0) > 50:
        md.append("⚠️ **Flag:** WRONG_DIRECTION dominates (>50%)\n\n")
    if fd.get('percent', 0) > 50:
        md.append("⚠️ **Flag:** FEE_DOMINATED_MOVE dominates (>50%)\n\n")

    # Regime Quality
    md.append("## 5. Regime Quality\n")
    for regime, stats in sorted(regime_stats.items()):
        if stats.get('count', 0) == 0:
            continue
        md.append(f"### {regime}\n")
        md.append(f"- **Count:** {stats['count']}\n")
        md.append(f"- **Win rate:** {stats['win_rate']*100:.1f}%\n")
        md.append(f"- **Avg PnL:** {stats['avg_pnl_pct']*100:.2f}%\n")
        if stats.get('win_rate', 0) == 0 and stats.get('count', 0) >= 20:
            md.append("⚠️ **Flag:** Zero win rate with n≥20\n")
        md.append("\n")

    # Symbol Quality (top 10 by count)
    md.append("## 6. Symbol Quality (Top 10)\n")
    top_symbols = sorted(symbol_stats.items(), key=lambda x: x[1].get('count', 0), reverse=True)[:10]
    for symbol, stats in top_symbols:
        md.append(f"### {symbol} (n={stats.get('count', 0)})\n")
        md.append(f"- **Win rate:** {stats['win_rate']*100:.1f}%\n")
        md.append(f"- **Avg PnL:** {stats['avg_pnl_pct']*100:.2f}%\n\n")

    # Exclusion Scenarios
    md.append("## 7. Exclusion Scenarios\n")
    for scenario, stats in sorted(exclusion_scenarios.items()):
        if stats.get('count', 0) == 0:
            continue
        md.append(f"### {scenario}\n")
        md.append(f"- **Remaining trades:** {stats['count']}\n")
        md.append(f"- **Win rate:** {stats.get('win_rate', 0)*100:.1f}%\n")
        md.append(f"- **Avg PnL:** {stats.get('avg_pnl_pct', 0)*100:.2f}%\n\n")

    md.append("## 8. Recommendation\n")
    md.append(f"`{recommendation}`\n")

    return "".join(md)


def generate_json_summary(
    summary: dict,
    bucket_stats: dict,
    economic_severity: dict,
    exclusion_scenarios: dict,
    recommendation: str,
) -> dict:
    """Generate JSON summary."""
    return {
        "recommendation": recommendation,
        "dataset_summary": summary,
        "bucket_stats": bucket_stats,
        "economic_severity": economic_severity,
        "exclusion_scenarios": exclusion_scenarios,
    }


def main():
    parser = argparse.ArgumentParser(description="Paper training segment quality analysis")
    parser.add_argument("dataset", help="Path to combined_paper_training_dataset.jsonl")
    parser.add_argument("--output", default="data/research/segment_quality_report.md")
    parser.add_argument("--json", default="data/research/segment_quality_summary.json")

    args = parser.parse_args()

    # Load data
    records = load_dataset(Path(args.dataset))

    if not records:
        print("Error: No completed trades found in dataset", file=sys.stderr)
        sys.exit(1)

    # Compute all sections
    summary = compute_dataset_summary(records)
    buckets_by_name = separate_by_bucket(records)
    bucket_stats = {k: compute_bucket_stats(v) for k, v in buckets_by_name.items()}

    # Get C_WEAK_EV_TRAIN for recommendation
    c_weak_records = buckets_by_name.get("C_WEAK_EV_TRAIN", [])

    attribution_stats = compute_attribution_stats(c_weak_records)
    economic_severity = compute_economic_severity(c_weak_records)
    regime_stats = compute_regime_quality(c_weak_records)
    symbol_stats = compute_symbol_quality(c_weak_records)
    side_regime_matrix = compute_side_regime_matrix(c_weak_records)
    exclusion_scenarios = compute_exclusion_scenarios(c_weak_records)

    # Recommend
    recommendation = recommend_patch(
        c_weak_records,
        economic_severity,
        regime_stats,
        symbol_stats,
        exclusion_scenarios,
    )

    # Generate reports
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
    )

    json_summary = generate_json_summary(
        summary,
        bucket_stats,
        economic_severity,
        exclusion_scenarios,
        recommendation,
    )

    # Write outputs
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        f.write(md_report)

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    with open(args.json, "w") as f:
        json.dump(json_summary, f, indent=2, default=str)

    print(f"Report: {args.output}")
    print(f"Summary: {args.json}")
    print(f"Recommendation: {recommendation}")


if __name__ == "__main__":
    main()
