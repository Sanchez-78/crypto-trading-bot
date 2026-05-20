#!/usr/bin/env python3
"""
Generate offline quality reports from paper training dataset JSONL.

Consumes JSONL produced by export_paper_training_dataset.py.
Generates markdown report + optional JSON summary for analysis.

Research-only: read-only analysis, no Firebase writes, no network.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional, Union


def load_dataset(jsonl_path: str) -> list[dict]:
    """Load JSONL dataset, skip malformed lines."""
    records = []
    try:
        with open(jsonl_path, "r") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        raise FileNotFoundError(f"Dataset not found: {jsonl_path}")
    return records


def safe_div(num: Union[int, float], denom: Union[int, float], default: float = 0.0) -> float:
    """Divide safely."""
    if denom == 0:
        return default
    return float(num) / float(denom)


def compute_dataset_summary(records: list[dict]) -> dict:
    """Dataset summary stats."""
    return {
        "total_trades": len(records),
        "unique_symbols": len(set(r.get("symbol") for r in records if r.get("symbol"))),
        "unique_buckets": len(set(r.get("bucket") for r in records if r.get("bucket"))),
        "date_range": {
            "earliest_ts": min((r.get("entry_ts_raw") for r in records if r.get("entry_ts_raw")), default=None),
            "latest_ts": max((r.get("exit_ts_raw") for r in records if r.get("exit_ts_raw")), default=None),
        }
    }


def compute_outcome_stats(records: list[dict]) -> dict:
    """Win/loss/flat distribution."""
    outcomes = defaultdict(int)
    for r in records:
        outcome = r.get("outcome")
        if outcome:
            outcomes[outcome] += 1
    total = len(records)
    return {
        "outcome_counts": dict(outcomes),
        "outcome_rates": {
            k: round(safe_div(v, total), 4) for k, v in outcomes.items()
        },
        "total": total,
    }


def compute_pnl_summary(records: list[dict]) -> dict:
    """PnL metrics."""
    pnls = [r.get("net_pnl_pct") for r in records if r.get("net_pnl_pct") is not None]
    if not pnls:
        return {"total_records": len(records), "pnl_records_with_values": 0}
    return {
        "total_records": len(records),
        "pnl_records_with_values": len(pnls),
        "mean_pnl_pct": round(sum(pnls) / len(pnls), 4),
        "min_pnl_pct": round(min(pnls), 4),
        "max_pnl_pct": round(max(pnls), 4),
        "positive_pnl_count": sum(1 for p in pnls if p > 0),
        "negative_pnl_count": sum(1 for p in pnls if p < 0),
        "zero_pnl_count": sum(1 for p in pnls if p == 0),
    }


def compute_attribution_stats(records: list[dict]) -> dict:
    """Attribution distribution."""
    attrs = defaultdict(int)
    for r in records:
        attr = r.get("attribution")
        if attr:
            attrs[attr] += 1
    total = len(records)
    return {
        "attribution_counts": dict(attrs),
        "attribution_rates": {
            k: round(safe_div(v, total), 4) for k, v in attrs.items()
        }
    }


def compute_regime_performance(records: list[dict]) -> dict:
    """Win rates by entry regime."""
    regimes = defaultdict(lambda: {"wins": 0, "total": 0})
    for r in records:
        regime = r.get("entry_regime")
        if regime:
            regimes[regime]["total"] += 1
            if r.get("outcome") == "WIN":
                regimes[regime]["wins"] += 1
    return {
        regime: {
            "total": stats["total"],
            "wins": stats["wins"],
            "win_rate": round(safe_div(stats["wins"], stats["total"]), 4)
        }
        for regime, stats in regimes.items()
    }


def compute_symbol_performance(records: list[dict]) -> dict:
    """Win rates by symbol."""
    symbols = defaultdict(lambda: {"wins": 0, "total": 0, "pnls": []})
    for r in records:
        sym = r.get("symbol")
        if sym:
            symbols[sym]["total"] += 1
            if r.get("outcome") == "WIN":
                symbols[sym]["wins"] += 1
            if r.get("net_pnl_pct") is not None:
                symbols[sym]["pnls"].append(r.get("net_pnl_pct"))
    return {
        sym: {
            "total": stats["total"],
            "wins": stats["wins"],
            "win_rate": round(safe_div(stats["wins"], stats["total"]), 4),
            "mean_pnl": round(safe_div(sum(stats["pnls"]), len(stats["pnls"])), 4) if stats["pnls"] else None,
        }
        for sym, stats in symbols.items()
    }


def compute_side_performance(records: list[dict]) -> dict:
    """BUY vs SELL performance."""
    sides = defaultdict(lambda: {"wins": 0, "total": 0, "pnls": []})
    for r in records:
        side = r.get("side")
        if side:
            sides[side]["total"] += 1
            if r.get("outcome") == "WIN":
                sides[side]["wins"] += 1
            if r.get("net_pnl_pct") is not None:
                sides[side]["pnls"].append(r.get("net_pnl_pct"))
    return {
        side: {
            "total": stats["total"],
            "wins": stats["wins"],
            "win_rate": round(safe_div(stats["wins"], stats["total"]), 4),
            "mean_pnl": round(safe_div(sum(stats["pnls"]), len(stats["pnls"])), 4) if stats["pnls"] else None,
        }
        for side, stats in sides.items()
    }


def compute_barrier_distribution(records: list[dict]) -> dict:
    """TP/SL/timeout exit distribution."""
    tp_count = sum(1 for r in records if r.get("touched_tp") is True)
    sl_count = sum(1 for r in records if r.get("touched_sl") is True)
    timeout_count = sum(1 for r in records if r.get("timeout") is True)
    total = len(records)
    return {
        "touched_tp": tp_count,
        "touched_sl": sl_count,
        "timeout": timeout_count,
        "tp_rate": round(safe_div(tp_count, total), 4),
        "sl_rate": round(safe_div(sl_count, total), 4),
        "timeout_rate": round(safe_div(timeout_count, total), 4),
    }


def compute_fee_viability(records: list[dict]) -> dict:
    """Fee viability analysis."""
    with_fee_drag = [r for r in records if r.get("fee_drag_pct") is not None]
    if not with_fee_drag:
        return {"total": len(records), "records_with_fee_data": 0}
    fees = [r.get("fee_drag_pct") for r in with_fee_drag]
    gross_pnls = [r.get("gross_move_pct") for r in with_fee_drag if r.get("gross_move_pct") is not None]
    net_pnls = [r.get("net_pnl_pct") for r in with_fee_drag if r.get("net_pnl_pct") is not None]
    fee_ate_gain = sum(1 for r in with_fee_drag if r.get("gross_move_pct", 0) > 0 and r.get("net_pnl_pct", 0) <= 0)
    return {
        "total_trades": len(records),
        "records_with_fee_data": len(with_fee_drag),
        "mean_fee_drag_pct": round(safe_div(sum(fees), len(fees)), 4),
        "mean_gross_move_pct": round(safe_div(sum(gross_pnls), len(gross_pnls)), 4) if gross_pnls else None,
        "mean_net_pnl_pct": round(safe_div(sum(net_pnls), len(net_pnls)), 4) if net_pnls else None,
        "trades_where_fee_ate_gain": fee_ate_gain,
        "fee_ate_gain_rate": round(safe_div(fee_ate_gain, len(with_fee_drag)), 4) if with_fee_drag else 0,
    }


def compute_geometry_impact(records: list[dict]) -> dict:
    """Impact of geometry calibration."""
    calibrated = [r for r in records if r.get("geometry_calibrated") is True]
    uncalibrated = [r for r in records if r.get("geometry_calibrated") is False]
    cal_wins = sum(1 for r in calibrated if r.get("outcome") == "WIN")
    uncal_wins = sum(1 for r in uncalibrated if r.get("outcome") == "WIN")
    return {
        "calibrated_count": len(calibrated),
        "uncalibrated_count": len(uncalibrated),
        "calibrated_win_rate": round(safe_div(cal_wins, len(calibrated)), 4) if calibrated else None,
        "uncalibrated_win_rate": round(safe_div(uncal_wins, len(uncalibrated)), 4) if uncalibrated else None,
    }


def compute_cost_edge_performance(records: list[dict]) -> dict:
    """Cost-edge bypass performance."""
    edge_ok = [r for r in records if r.get("cost_edge_ok") is True]
    edge_bypassed = [r for r in records if r.get("cost_edge_bypassed") is True]
    ok_wins = sum(1 for r in edge_ok if r.get("outcome") == "WIN")
    bypass_wins = sum(1 for r in edge_bypassed if r.get("outcome") == "WIN")
    return {
        "cost_edge_ok_count": len(edge_ok),
        "cost_edge_bypassed_count": len(edge_bypassed),
        "cost_edge_ok_win_rate": round(safe_div(ok_wins, len(edge_ok)), 4) if edge_ok else None,
        "cost_edge_bypassed_win_rate": round(safe_div(bypass_wins, len(edge_bypassed)), 4) if edge_bypassed else None,
    }


def compute_mfe_mae_quality(records: list[dict]) -> dict:
    """MFE/MAE stats."""
    mfes = [r.get("mfe_pct") for r in records if r.get("mfe_pct") is not None]
    maes = [r.get("mae_pct") for r in records if r.get("mae_pct") is not None]
    return {
        "mfe_records": len(mfes),
        "mae_records": len(maes),
        "mean_mfe_pct": round(safe_div(sum(mfes), len(mfes)), 4) if mfes else None,
        "mean_mae_pct": round(safe_div(sum(maes), len(maes)), 4) if maes else None,
        "max_mfe_pct": round(max(mfes), 4) if mfes else None,
        "max_mae_pct": round(max(maes), 4) if maes else None,
    }


def check_learning_warnings(records: list[dict]) -> list[str]:
    """Flag potential data/learning quality issues."""
    warnings = []
    if not records:
        warnings.append("Empty dataset")
    if len(records) < 10:
        warnings.append(f"Small dataset: only {len(records)} trades (insufficient for statistical significance)")
    outcomes = compute_outcome_stats(records)
    if outcomes["outcome_rates"].get("WIN", 0) > 0.65:
        warnings.append("Suspiciously high win rate (>65%) — check for lookahead bias or overfitting")
    if outcomes["outcome_rates"].get("WIN", 0) < 0.30:
        warnings.append("Low win rate (<30%) — model may need recalibration or regime filtering")
    pnl = compute_pnl_summary(records)
    if pnl.get("pnl_records_with_values", 0) < len(records) * 0.5:
        warnings.append("Many trades missing PnL data — check parser or log completeness")
    fees = compute_fee_viability(records)
    if fees.get("fee_ate_gain_rate", 0) > 0.25:
        warnings.append("Fees ate gain in >25% of winning moves — consider wider TP or tighter stop logic")
    return warnings


def generate_markdown_report(records: list[dict], dataset_path: str) -> str:
    """Generate markdown report."""
    md = []
    md.append("# Paper Training Quality Report\n")
    md.append(f"**Dataset:** `{dataset_path}`  \n")
    md.append(f"**Generated:** `{__import__('datetime').datetime.now().isoformat()}`\n\n")

    # Dataset Summary
    ds = compute_dataset_summary(records)
    md.append("## 1. Dataset Summary\n")
    md.append(f"- **Total Trades:** {ds['total_trades']}\n")
    md.append(f"- **Unique Symbols:** {ds['unique_symbols']}\n")
    md.append(f"- **Unique Buckets:** {ds['unique_buckets']}\n")
    if ds['date_range']['earliest_ts']:
        md.append(f"- **Date Range:** {ds['date_range']['earliest_ts']} to {ds['date_range']['latest_ts']}\n")
    md.append("\n")

    # Outcome Distribution
    outcomes = compute_outcome_stats(records)
    md.append("## 2. Outcome Distribution\n")
    for outcome, count in sorted(outcomes['outcome_counts'].items()):
        rate = outcomes['outcome_rates'].get(outcome, 0)
        md.append(f"- **{outcome}:** {count} trades ({rate*100:.1f}%)\n")
    md.append("\n")

    # PnL Summary
    pnl = compute_pnl_summary(records)
    md.append("## 3. PnL Summary\n")
    if pnl.get('pnl_records_with_values', 0) > 0:
        md.append(f"- **Mean Net PnL:** {pnl['mean_pnl_pct']:.4f}%\n")
        md.append(f"- **Min:** {pnl['min_pnl_pct']:.4f}% | **Max:** {pnl['max_pnl_pct']:.4f}%\n")
        md.append(f"- **Positive PnL:** {pnl['positive_pnl_count']} trades\n")
        md.append(f"- **Negative PnL:** {pnl['negative_pnl_count']} trades\n")
    else:
        md.append("- No PnL data available\n")
    md.append("\n")

    # Attribution Distribution
    attrs = compute_attribution_stats(records)
    md.append("## 4. Attribution Distribution\n")
    if attrs['attribution_counts']:
        for attr, count in sorted(attrs['attribution_counts'].items(), key=lambda x: x[1], reverse=True):
            rate = attrs['attribution_rates'].get(attr, 0)
            md.append(f"- **{attr}:** {count} ({rate*100:.1f}%)\n")
    else:
        md.append("- No attribution data\n")
    md.append("\n")

    # Regime Performance
    regime_perf = compute_regime_performance(records)
    md.append("## 5. Regime Performance\n")
    if regime_perf:
        for regime, stats in sorted(regime_perf.items(), key=lambda x: x[1]['win_rate'], reverse=True):
            md.append(f"- **{regime}:** {stats['wins']}/{stats['total']} ({stats['win_rate']*100:.1f}%)\n")
    else:
        md.append("- No regime data\n")
    md.append("\n")

    # Symbol Performance
    sym_perf = compute_symbol_performance(records)
    md.append("## 6. Symbol Performance\n")
    if sym_perf:
        for sym, stats in sorted(sym_perf.items(), key=lambda x: x[1]['win_rate'], reverse=True)[:10]:
            pnl_str = f" | Mean PnL: {stats['mean_pnl']}%" if stats['mean_pnl'] is not None else ""
            md.append(f"- **{sym}:** {stats['wins']}/{stats['total']} ({stats['win_rate']*100:.1f}%){pnl_str}\n")
    else:
        md.append("- No symbol data\n")
    md.append("\n")

    # Side Performance
    side_perf = compute_side_performance(records)
    md.append("## 7. Side Performance (BUY vs SELL)\n")
    for side, stats in sorted(side_perf.items()):
        pnl_str = f" | Mean PnL: {stats['mean_pnl']}%" if stats['mean_pnl'] is not None else ""
        md.append(f"- **{side}:** {stats['wins']}/{stats['total']} ({stats['win_rate']*100:.1f}%){pnl_str}\n")
    md.append("\n")

    # Barrier Distribution
    barriers = compute_barrier_distribution(records)
    md.append("## 8. Exit Barrier Distribution\n")
    md.append(f"- **Touched TP:** {barriers['touched_tp']} ({barriers['tp_rate']*100:.1f}%)\n")
    md.append(f"- **Touched SL:** {barriers['touched_sl']} ({barriers['sl_rate']*100:.1f}%)\n")
    md.append(f"- **Timeout:** {barriers['timeout']} ({barriers['timeout_rate']*100:.1f}%)\n")
    md.append("\n")

    # Fee Viability
    fees = compute_fee_viability(records)
    md.append("## 9. Fee Viability Analysis\n")
    if fees.get('records_with_fee_data', 0) > 0:
        md.append(f"- **Mean Fee Drag:** {fees['mean_fee_drag_pct']}%\n")
        md.append(f"- **Mean Gross Move:** {fees['mean_gross_move_pct']}%\n")
        md.append(f"- **Mean Net PnL (after fees):** {fees['mean_net_pnl_pct']}%\n")
        md.append(f"- **Fee Ate Gain:** {fees['trades_where_fee_ate_gain']} trades ({fees['fee_ate_gain_rate']*100:.1f}%)\n")
    else:
        md.append("- No fee data\n")
    md.append("\n")

    # Geometry Calibration
    geom = compute_geometry_impact(records)
    md.append("## 10. Geometry Calibration Impact\n")
    if geom['calibrated_count'] > 0 or geom['uncalibrated_count'] > 0:
        if geom['calibrated_win_rate'] is not None:
            md.append(f"- **Calibrated:** {geom['calibrated_count']} trades, {geom['calibrated_win_rate']*100:.1f}% win rate\n")
        if geom['uncalibrated_win_rate'] is not None:
            md.append(f"- **Uncalibrated:** {geom['uncalibrated_count']} trades, {geom['uncalibrated_win_rate']*100:.1f}% win rate\n")
    else:
        md.append("- No calibration data\n")
    md.append("\n")

    # Cost-Edge Performance
    edge = compute_cost_edge_performance(records)
    md.append("## 11. Cost-Edge Bypass Performance\n")
    if edge['cost_edge_ok_count'] > 0 or edge['cost_edge_bypassed_count'] > 0:
        if edge['cost_edge_ok_win_rate'] is not None:
            md.append(f"- **Cost-Edge OK:** {edge['cost_edge_ok_count']} trades, {edge['cost_edge_ok_win_rate']*100:.1f}% win rate\n")
        if edge['cost_edge_bypassed_win_rate'] is not None:
            md.append(f"- **Cost-Edge Bypassed:** {edge['cost_edge_bypassed_count']} trades, {edge['cost_edge_bypassed_win_rate']*100:.1f}% win rate\n")
    else:
        md.append("- No cost-edge data\n")
    md.append("\n")

    # MFE/MAE Quality
    mfe_mae = compute_mfe_mae_quality(records)
    md.append("## 12. MFE/MAE Quality\n")
    if mfe_mae['mfe_records'] > 0:
        md.append(f"- **Mean MFE:** {mfe_mae['mean_mfe_pct']}% | **Max:** {mfe_mae['max_mfe_pct']}%\n")
    if mfe_mae['mae_records'] > 0:
        md.append(f"- **Mean MAE:** {mfe_mae['mean_mae_pct']}% | **Max:** {mfe_mae['max_mae_pct']}%\n")
    md.append("\n")

    # Learning Quality Warnings
    warnings = check_learning_warnings(records)
    md.append("## 13. Learning Quality Warnings\n")
    if warnings:
        for warning in warnings:
            md.append(f"- WARNING: {warning}\n")
    else:
        md.append("- No significant warnings\n")
    md.append("\n")

    # Android Dashboard Recommendations
    md.append("## 14. Android Dashboard Metric Recommendations\n")
    md.append("Based on this dataset, prioritize these metrics on the dashboard:\n\n")
    best_regime = max(regime_perf.items(), key=lambda x: x[1]['win_rate'], default=(None, {}))[0]
    best_symbol = max(sym_perf.items(), key=lambda x: x[1]['win_rate'], default=(None, {}))[0]
    md.append(f"1. **Best Regime:** {best_regime or 'N/A'}\n")
    md.append(f"2. **Best Symbol:** {best_symbol or 'N/A'}\n")
    md.append(f"3. **Overall Win Rate:** {outcomes['outcome_rates'].get('WIN', 0)*100:.1f}%\n")
    if pnl.get('mean_pnl_pct'):
        md.append(f"4. **Mean Trade PnL:** {pnl['mean_pnl_pct']}%\n")
    md.append(f"5. **Fee Drag Impact:** {fees.get('fee_ate_gain_rate', 0)*100:.1f}% of winning moves eaten\n")
    md.append("\n")

    return "".join(md)


def generate_json_summary(records: list[dict]) -> dict:
    """Generate JSON summary for programmatic use."""
    return {
        "dataset": compute_dataset_summary(records),
        "outcomes": compute_outcome_stats(records),
        "pnl": compute_pnl_summary(records),
        "attribution": compute_attribution_stats(records),
        "regime_performance": compute_regime_performance(records),
        "symbol_performance": compute_symbol_performance(records),
        "side_performance": compute_side_performance(records),
        "barriers": compute_barrier_distribution(records),
        "fee_viability": compute_fee_viability(records),
        "geometry_impact": compute_geometry_impact(records),
        "cost_edge_performance": compute_cost_edge_performance(records),
        "mfe_mae": compute_mfe_mae_quality(records),
        "warnings": check_learning_warnings(records),
    }


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate quality report from paper training dataset JSONL"
    )
    parser.add_argument("dataset", help="Path to JSONL dataset")
    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown report (default: stdout)"
    )
    parser.add_argument(
        "--json",
        default=None,
        help="Optional JSON summary output"
    )

    args = parser.parse_args()

    try:
        records = load_dataset(args.dataset)
        md_report = generate_markdown_report(records, args.dataset)

        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w") as f:
                f.write(md_report)
            print(f"Report written to {args.output}")
        else:
            print(md_report)

        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            summary = generate_json_summary(records)
            with open(args.json, "w") as f:
                json.dump(summary, f, indent=2)
            print(f"JSON summary written to {args.json}")

        print(f"Processed {len(records)} trades")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
