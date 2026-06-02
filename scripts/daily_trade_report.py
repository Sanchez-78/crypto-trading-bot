#!/usr/bin/env python3
"""Daily Trade & Learning Report Generator

Generates comprehensive daily report on:
- Paper trades (entries, exits, closed)
- Learning metrics (updates, segments, performance)
- Recommendations for optimization

Run daily at 18:00 UTC (end of trading day)
"""
import re
import sys
import time
import json
import subprocess
from datetime import datetime, timedelta
from collections import defaultdict

def get_logs(hours=24):
    """Fetch recent logs from journalctl."""
    try:
        result = subprocess.run(
            ["journalctl", "-u", "cryptomaster.service",
             f"--since={hours} hours ago", "--no-pager"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.split('\n') if result.returncode == 0 else []
    except subprocess.TimeoutExpired:
        print(f"Warning: journalctl timeout after 30s, using last 200 lines", file=sys.stderr)
        try:
            result = subprocess.run(
                ["journalctl", "-u", "cryptomaster.service", "-n", "1000", "--no-pager"],
                capture_output=True, text=True, timeout=15
            )
            return result.stdout.split('\n') if result.returncode == 0 else []
        except Exception as e2:
            print(f"Error fetching logs: {e2}", file=sys.stderr)
            return []
    except Exception as e:
        print(f"Error fetching logs: {e}", file=sys.stderr)
        return []


def extract_paper_trades(logs):
    """Extract paper entry/exit events."""
    trades = {
        "entries": 0,
        "exits": 0,
        "closed": 0,
        "by_symbol": defaultdict(lambda: {"entries": 0, "exits": 0, "closed": 0}),
        "by_side": defaultdict(lambda: {"entries": 0, "exits": 0, "closed": 0}),
        "by_reason": defaultdict(int),
    }

    for line in logs:
        # Count entries
        if "PAPER_ENTRY_ADMIT" in line or "admission_reason=paper_learning" in line:
            trades["entries"] += 1
            # Extract symbol if possible
            if "symbol=" in line:
                sym = line.split("symbol=")[1].split()[0]
                trades["by_symbol"][sym]["entries"] += 1
            # Extract side
            if "side=BUY" in line:
                trades["by_side"]["BUY"]["entries"] += 1
            elif "side=SELL" in line:
                trades["by_side"]["SELL"]["entries"] += 1

        # Count exits
        if "PAPER_EXIT" in line:
            trades["exits"] += 1
            if "symbol=" in line:
                sym = line.split("symbol=")[1].split()[0]
                trades["by_symbol"][sym]["exits"] += 1
            if "side=BUY" in line:
                trades["by_side"]["BUY"]["exits"] += 1
            elif "side=SELL" in line:
                trades["by_side"]["SELL"]["exits"] += 1

        # Count closed trades
        if "PAPER_CANONICAL_LEARNING_UPDATE" in line or "V5_BRIDGE_LEARNING_UPDATE" in line:
            trades["closed"] += 1
            if "outcome=" in line:
                outcome = line.split("outcome=")[1].split()[0]
                trades["by_reason"][outcome] += 1

    return trades


def extract_learning_metrics(logs):
    """Extract learning performance metrics."""
    learning = {
        "updates_total": 0,
        "segments_active": set(),
        "best_segment": None,
        "worst_segment": None,
        "rolling_pf": [],
        "rolling_expectancy": [],
        "learning_eligible": 0,
        "learning_ineligible": 0,
    }

    segments = {}

    for line in logs:
        # Count learning updates
        if "V5_BRIDGE_LEARNING_UPDATE" in line or "PAPER_CANONICAL_LEARNING_UPDATE" in line:
            learning["updates_total"] += 1
            learning["learning_eligible"] += 1

        # Extract segment performance
        if "PAPER_POLICY_ADAPTATION" in line or "segment=" in line:
            if "segment=" in line:
                try:
                    seg = line.split("segment=")[1].split()[0]
                    learning["segments_active"].add(seg)

                    # Extract PF
                    if "pf=" in line:
                        pf_str = line.split("pf=")[1].split()[0]
                        pf = float(pf_str)
                        if seg not in segments:
                            segments[seg] = {"pf": [], "expectancy": [], "n": 0}
                        segments[seg]["pf"].append(pf)

                    # Extract expectancy
                    if "expectancy=" in line:
                        exp_str = line.split("expectancy=")[1].split()[0]
                        exp = float(exp_str)
                        if seg not in segments:
                            segments[seg] = {"pf": [], "expectancy": [], "n": 0}
                        segments[seg]["expectancy"].append(exp)

                    # Extract sample count
                    if "n=" in line:
                        n_str = line.split("n=")[1].split()[0]
                        segments[seg]["n"] = int(n_str)
                except:
                    pass

        # Track rolling metrics
        if "rolling20_pf=" in line or "rolling50_pf=" in line or "rolling100_pf=" in line:
            try:
                pf = float(line.split("_pf=")[1].split()[0])
                learning["rolling_pf"].append(pf)
            except:
                pass

    # Find best/worst segments
    if segments:
        segment_list = sorted(
            segments.items(),
            key=lambda x: sum(x[1]["pf"]) / len(x[1]["pf"]) if x[1]["pf"] else 0
        )
        if segment_list:
            learning["worst_segment"] = (segment_list[0][0], segment_list[0][1])
            learning["best_segment"] = (segment_list[-1][0], segment_list[-1][1])

    learning["rolling_pf"] = learning["rolling_pf"][-10:] if learning["rolling_pf"] else []
    learning["segments_active"] = list(learning["segments_active"])

    return learning


def extract_blocking_reasons(logs):
    """Extract why entries are being rejected."""
    reasons = defaultdict(int)

    for line in logs:
        if "reject_reason=" in line:
            try:
                reason = line.split("reject_reason=")[1].split()[0]
                reasons[reason] += 1
            except:
                pass

        if "source_reject=" in line:
            try:
                reason = line.split("source_reject=")[1].split()[0]
                reasons[f"source:{reason}"] += 1
            except:
                pass

    # Sort by frequency
    return sorted(reasons.items(), key=lambda x: x[1], reverse=True)


def extract_cost_edge_diagnostics(logs):
    """Extract cost-edge expected vs required move."""
    diagnostics = []

    for line in logs:
        if "expected_move_pct=" in line and "required_move_pct=" in line:
            try:
                exp = float(line.split("expected_move_pct=")[1].split()[0])
                req = float(line.split("required_move_pct=")[1].split()[0])
                diagnostics.append({"expected": exp, "required": req, "gap": req / exp if exp > 0 else 999})
            except:
                pass

    return diagnostics[-10:] if diagnostics else []  # Last 10 samples


def extract_firebase_quota(logs):
    """Extract Firebase quota usage."""
    quota = None

    for line in logs:
        if "V5_BRIDGE_QUOTA_STATE" in line:
            try:
                reads = int(line.split("reads=")[1].split("/")[0])
                max_reads = int(line.split("reads=")[1].split("/")[1].split()[0])
                writes = int(line.split("writes=")[1].split("/")[0])
                max_writes = int(line.split("writes=")[1].split("/")[1].split()[0])

                quota = {
                    "reads": reads,
                    "max_reads": max_reads,
                    "reads_pct": (reads / max_reads * 100) if max_reads > 0 else 0,
                    "writes": writes,
                    "max_writes": max_writes,
                    "writes_pct": (writes / max_writes * 100) if max_writes > 0 else 0,
                }
            except:
                pass

    return quota


def generate_recommendations(trades, learning, blocking, cost_edge, quota):
    """Generate optimization recommendations based on metrics."""
    recs = []

    # Recommendation 1: Entry volume
    if trades["entries"] == 0:
        recs.append({
            "priority": "HIGH",
            "title": "Zero entries in last 24h",
            "issue": "PAPER_ENTRY_ADMIT count is 0",
            "action": "Check: cost-edge (expected_move too low?), ECON_BAD (blocking?), market conditions (spreads wide?)",
            "metric": f"entries_24h=0"
        })
    elif trades["entries"] < 2:
        recs.append({
            "priority": "MEDIUM",
            "title": "Very low entry rate",
            "issue": f"Only {trades['entries']} entries in 24h (target: 6+)",
            "action": "Analyze blocking reasons, check cost-edge diagnostics",
            "metric": f"entries_24h={trades['entries']}"
        })

    # Recommendation 2: Learning progress
    if learning["updates_total"] == 0:
        recs.append({
            "priority": "MEDIUM",
            "title": "No learning updates",
            "issue": "No trades closed or learning eligibility blocked",
            "action": "Check eligibility gates, verify learning_eligible gate isn't too strict",
            "metric": f"learning_updates=0"
        })
    elif learning["updates_total"] < 2:
        recs.append({
            "priority": "LOW",
            "title": "Slow learning accumulation",
            "issue": f"Only {learning['updates_total']} learning updates (need 50 for READY)",
            "action": "This follows entry rate; accelerate entries to speed learning",
            "metric": f"learning_rate={learning['updates_total']}/day"
        })

    # Recommendation 3: Blocking analysis
    if blocking:
        top_block = blocking[0]
        if top_block[1] > (trades["entries"] + 10):  # More blocks than entries
            recs.append({
                "priority": "MEDIUM",
                "title": f"Dominant block reason: {top_block[0]}",
                "issue": f"{top_block[0]} blocked {top_block[1]} candidates (vs {trades['entries']} entries)",
                "action": f"Investigate {top_block[0]} threshold/logic",
                "metric": f"{top_block[0]}_blocks={top_block[1]}"
            })

    # Recommendation 4: Cost-edge diagnostics
    if cost_edge:
        gaps = [d["gap"] for d in cost_edge if d["gap"] != 999]
        if gaps:
            avg_gap = sum(gaps) / len(gaps)
            if avg_gap > 5:  # 5x mismatch
                recs.append({
                    "priority": "HIGH",
                    "title": "Extreme cost-edge mismatch",
                    "issue": f"Required move is {avg_gap:.1f}x larger than expected (gap too wide)",
                    "action": "Cost-edge is primary bottleneck; consider: lower safety_margin, wider TP targets, or accept market starvation",
                    "metric": f"avg_gap={avg_gap:.1f}x"
                })

    # Recommendation 5: Segment performance
    if learning["best_segment"] and learning["worst_segment"]:
        best_name, best_data = learning["best_segment"]
        worst_name, worst_data = learning["worst_segment"]
        best_pf = sum(best_data["pf"]) / len(best_data["pf"]) if best_data["pf"] else 0
        worst_pf = sum(worst_data["pf"]) / len(worst_data["pf"]) if worst_data["pf"] else 0

        if best_pf > 1.2 and worst_pf < 0.8:
            recs.append({
                "priority": "LOW",
                "title": "Segment performance divergence detected",
                "issue": f"Best: {best_name} (PF={best_pf:.2f}), Worst: {worst_name} (PF={worst_pf:.2f})",
                "action": "Future: implement segment prioritization (bias entries to profitable segments)",
                "metric": f"divergence={best_pf/worst_pf:.1f}x"
            })

    # Recommendation 6: Firebase quota
    if quota and quota["writes_pct"] > 75:
        recs.append({
            "priority": "MEDIUM",
            "title": "Firebase quota approaching",
            "issue": f"Writes at {quota['writes_pct']:.0f}% of daily limit ({quota['writes']}/{quota['max_writes']})",
            "action": "Increase caching TTL, reduce metrics publishing frequency, monitor for reset at midnight PT",
            "metric": f"writes_pct={quota['writes_pct']:.0f}%"
        })

    return recs


def format_report(timestamp, trades, learning, blocking, cost_edge, quota, recs):
    """Format report as readable text."""
    report = []

    report.append("╔════════════════════════════════════════════════════════════════════════════════╗")
    report.append(f"║ DAILY TRADE & LEARNING REPORT — {timestamp.strftime('%Y-%m-%d')} (UTC)")
    report.append("╚════════════════════════════════════════════════════════════════════════════════╝")
    report.append("")

    # Summary
    report.append("📊 SUMMARY")
    report.append(f"  Entries (24h):        {trades['entries']}")
    report.append(f"  Exits (24h):          {trades['exits']}")
    report.append(f"  Closed trades:        {trades['closed']}")
    report.append(f"  Learning updates:     {learning['updates_total']}")
    report.append(f"  Active segments:      {len(learning['segments_active'])}")
    report.append("")

    # By symbol
    if trades["by_symbol"]:
        report.append("📍 BY SYMBOL")
        for sym in sorted(trades["by_symbol"].keys()):
            stats = trades["by_symbol"][sym]
            report.append(f"  {sym:12} entries={stats['entries']:2} exits={stats['exits']:2}")
        report.append("")

    # Blocking reasons
    if blocking:
        report.append("❌ BLOCKING REASONS (top 5)")
        for reason, count in blocking[:5]:
            report.append(f"  {reason:30} {count:3} times")
        report.append("")

    # Cost-edge diagnostics
    if cost_edge:
        report.append("💰 COST-EDGE DIAGNOSTICS (last 5)")
        for d in cost_edge[-5:]:
            report.append(f"  Expected: {d['expected']:7.4f}%  Required: {d['required']:7.4f}%  Gap: {d['gap']:5.1f}x")
        report.append("")

    # Firebase quota
    if quota:
        report.append("☁️  FIREBASE QUOTA")
        report.append(f"  Reads:   {quota['reads']:5} / {quota['max_reads']:5} ({quota['reads_pct']:5.1f}%)")
        report.append(f"  Writes:  {quota['writes']:5} / {quota['max_writes']:5} ({quota['writes_pct']:5.1f}%)")
        report.append("")

    # Learning segments
    if learning["best_segment"]:
        report.append("🎓 LEARNING SEGMENTS (best & worst)")
        best_name, best_data = learning["best_segment"]
        worst_name, worst_data = learning["worst_segment"]
        if best_data["pf"]:
            best_pf = sum(best_data["pf"]) / len(best_data["pf"])
            report.append(f"  BEST:  {best_name:20} PF={best_pf:.2f} (n={best_data['n']})")
        if worst_data["pf"]:
            worst_pf = sum(worst_data["pf"]) / len(worst_data["pf"])
            report.append(f"  WORST: {worst_name:20} PF={worst_pf:.2f} (n={worst_data['n']})")
        report.append("")

    # Recommendations
    if recs:
        report.append("💡 RECOMMENDATIONS")
        for i, rec in enumerate(recs, 1):
            report.append(f"  [{rec['priority']}] #{i}: {rec['title']}")
            report.append(f"      Issue:  {rec['issue']}")
            report.append(f"      Action: {rec['action']}")
            report.append(f"      Metric: {rec['metric']}")
            report.append("")
    else:
        report.append("✅ NO ISSUES — All metrics nominal")
        report.append("")

    report.append("╔════════════════════════════════════════════════════════════════════════════════╗")
    report.append("║ End of daily report. Next: tomorrow 18:00 UTC")
    report.append("╚════════════════════════════════════════════════════════════════════════════════╝")

    return "\n".join(report)


def main():
    """Generate and output daily report."""
    timestamp = datetime.utcnow()  # Use now(timezone.utc) in Python 3.12+

    print(f"Generating daily report for {timestamp.strftime('%Y-%m-%d')}...", file=sys.stderr)

    # Fetch logs
    logs = get_logs(hours=24)
    if not logs:
        print("ERROR: No logs retrieved", file=sys.stderr)
        return 1

    # Extract metrics
    trades = extract_paper_trades(logs)
    learning = extract_learning_metrics(logs)
    blocking = extract_blocking_reasons(logs)
    cost_edge = extract_cost_edge_diagnostics(logs)
    quota = extract_firebase_quota(logs)

    # Generate recommendations
    recs = generate_recommendations(trades, learning, blocking, cost_edge, quota)

    # Format and output
    report = format_report(timestamp, trades, learning, blocking, cost_edge, quota, recs)
    print(report)

    # Save to file
    report_file = f"/tmp/daily_report_{timestamp.strftime('%Y-%m-%d')}.txt"
    try:
        with open(report_file, 'w') as f:
            f.write(report)
        print(f"\nReport saved: {report_file}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not save report: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
