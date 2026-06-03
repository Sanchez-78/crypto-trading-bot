#!/usr/bin/env python3
"""Phase 5A Activity Reconciliation Report

Parses logs and SQLite state to generate canonical activity metrics.

Usage:
  python3 scripts/phase5_activity_reconciliation_report.py --window 24h
  python3 scripts/phase5_activity_reconciliation_report.py --window 1h
"""
import sys
import subprocess
import json
import sqlite3
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

def run_command(cmd, timeout=30):
    """Run shell command safely."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return ""
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return ""

def get_logs(hours=24):
    """Fetch recent logs from journalctl."""
    cmd = f"journalctl -u cryptomaster.service --since '{hours} hours ago' --no-pager 2>/dev/null"
    return run_command(cmd, timeout=30).split('\n')

def count_pattern(logs, pattern):
    """Count occurrences of pattern in logs."""
    return sum(1 for line in logs if pattern in line)

def extract_metric(line, key):
    """Extract metric value from log line."""
    if f"{key}=" not in line:
        return None
    try:
        value = line.split(f"{key}=")[1].split()[0]
        return value.strip()
    except:
        return None

def analyze_logs(hours=24):
    """Analyze logs for activity metrics."""
    logs = get_logs(hours)

    counts = {
        "raw_candidates": count_pattern(logs, "[PAPER_ENTRY_ADMISSION_TRUTH]"),
        "paper_admission_attempts": count_pattern(logs, "[PAPER_ENTRY_ADMISSION_TRUTH]"),
        "paper_entry_opened": count_pattern(logs, "[PAPER_ENTRY_ADMIT]"),
        "paper_entry_blocked": count_pattern(logs, "[PAPER_ENTRY_BLOCKED]"),
        "paper_exit_closed": count_pattern(logs, "[PAPER_EXIT]"),
        "learning_updates": count_pattern(logs, "PAPER_CANONICAL_LEARNING_UPDATE"),
        "v5_learning_updates": count_pattern(logs, "V5_BRIDGE_LEARNING_UPDATE"),
    }

    # Rejection reasons
    rejection_reasons = defaultdict(int)
    for line in logs:
        if "source_reject=" in line:
            reason = extract_metric(line, "source_reject")
            if reason:
                rejection_reasons[reason] += 1

    # Block reasons
    block_reasons = defaultdict(int)
    for line in logs:
        if "[PAPER_ENTRY_BLOCKED]" in line and "reason=" in line:
            reason = extract_metric(line, "reason")
            if reason:
                block_reasons[reason] += 1

    # Segment activity
    segments = defaultdict(lambda: {"entries": 0, "exits": 0})
    for line in logs:
        if "[PAPER_ENTRY_ADMIT]" in line:
            symbol = extract_metric(line, "symbol")
            side = extract_metric(line, "side")
            if symbol and side:
                segments[f"{symbol}:{side}"]["entries"] += 1
        if "[PAPER_EXIT]" in line:
            symbol = extract_metric(line, "symbol")
            side = extract_metric(line, "side")
            if symbol and side:
                segments[f"{symbol}:{side}"]["exits"] += 1

    # Consistency check
    exits = counts["paper_exit_closed"]
    learning = counts["learning_updates"]
    consistent = exits == learning or learning == 0

    return {
        "counts": counts,
        "rejection_reasons": dict(sorted(rejection_reasons.items(), key=lambda x: x[1], reverse=True)[:5]),
        "block_reasons": dict(sorted(block_reasons.items(), key=lambda x: x[1], reverse=True)[:5]),
        "segments": segments,
        "consistency": {
            "exits_learning_match": consistent,
            "exits": exits,
            "learning": learning,
        }
    }

def print_report(data, hours=24):
    """Print formatted report."""
    c = data["counts"]
    cons = data["consistency"]

    print("╔════════════════════════════════════════════════════════════════════════════════╗")
    print(f"║ PHASE 5A ACTIVITY RECONCILIATION — {hours}h window ({datetime.now().strftime('%Y-%m-%d %H:%M UTC')})")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")
    print()

    print("📊 RAW COUNTS")
    print(f"  Candidates:              {c['raw_candidates']:>6}")
    print(f"  Admission attempts:      {c['paper_admission_attempts']:>6}")
    print(f"  Entries opened:          {c['paper_entry_opened']:>6}")
    print(f"  Entries blocked:         {c['paper_entry_blocked']:>6}")
    print(f"  Exits closed:            {c['paper_exit_closed']:>6}")
    print(f"  Learning updates:        {c['learning_updates']:>6}")
    print()

    # Conversion funnel
    if c['raw_candidates'] > 0:
        conv_cand_to_attempt = (c['paper_admission_attempts'] / c['raw_candidates'] * 100)
    else:
        conv_cand_to_attempt = 0

    if c['paper_admission_attempts'] > 0:
        conv_attempt_to_entry = (c['paper_entry_opened'] / c['paper_admission_attempts'] * 100)
    else:
        conv_attempt_to_entry = 0

    if c['paper_entry_opened'] > 0:
        conv_entry_to_exit = (c['paper_exit_closed'] / c['paper_entry_opened'] * 100)
    else:
        conv_entry_to_exit = 0

    if c['paper_exit_closed'] > 0:
        conv_exit_to_learning = (c['learning_updates'] / c['paper_exit_closed'] * 100)
    else:
        conv_exit_to_learning = 0

    print("📈 CONVERSION FUNNEL")
    print(f"  Candidate → Attempt:     {conv_cand_to_attempt:>6.1f}%")
    print(f"  Attempt → Entry:         {conv_attempt_to_entry:>6.1f}%")
    print(f"  Entry → Exit:            {conv_entry_to_exit:>6.1f}%")
    print(f"  Exit → Learning:         {conv_exit_to_learning:>6.1f}%")
    print()

    print("⚠️  REJECTION REASONS (Top 5)")
    if data["rejection_reasons"]:
        for reason, count in data["rejection_reasons"].items():
            print(f"  {reason:40} {count:>6} times")
    else:
        print("  (none)")
    print()

    print("🚫 BLOCK REASONS (Top 5)")
    if data["block_reasons"]:
        for reason, count in data["block_reasons"].items():
            print(f"  {reason:40} {count:>6} times")
    else:
        print("  (none)")
    print()

    print("📍 TOP SEGMENTS BY ENTRIES")
    segments_sorted = sorted(data["segments"].items(), key=lambda x: x[1]["entries"], reverse=True)[:5]
    if segments_sorted:
        for segment, stats in segments_sorted:
            print(f"  {segment:30} entries={stats['entries']:>3} exits={stats['exits']:>3}")
    else:
        print("  (none)")
    print()

    print("🔄 CONSISTENCY CHECK")
    if cons["exits_learning_match"]:
        print(f"  ✅ Exits ({cons['exits']}) matches Learning ({cons['learning']})")
    else:
        print(f"  ⚠️  MISMATCH: Exits ({cons['exits']}) != Learning ({cons['learning']})")
    print()

    print("╔════════════════════════════════════════════════════════════════════════════════╗")
    print("║ End of Phase 5A Report")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")

def main():
    parser = argparse.ArgumentParser(description="Phase 5A Activity Reconciliation Report")
    parser.add_argument("--window", choices=["1h", "6h", "24h"], default="24h", help="Time window")
    args = parser.parse_args()

    hours = {"1h": 1, "6h": 6, "24h": 24}[args.window]

    data = analyze_logs(hours)
    print_report(data, hours)

if __name__ == "__main__":
    main()
