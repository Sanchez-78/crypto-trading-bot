#!/usr/bin/env python3
"""Phase 5 Time-of-Day Performance Report

Analyzes PAPER trading performance by hour of day (UTC).
Provides data-driven recommendations for time-based filtering.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

def load_learning_state():
    """Load learning state from JSON."""
    state_file = Path("server_local_backups/paper_adaptive_learning_state.json")
    if not state_file.exists():
        print("❌ Learning state file not found")
        return None

    with open(state_file) as f:
        return json.load(f)


def analyze_by_hour(learning_state):
    """Analyze rolling100 trades by hour of day."""
    rolling100 = learning_state.get("rolling100", [])

    hour_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "flats": 0, "total_pnl": 0})

    for entry in rolling100:
        if len(entry) < 4:
            continue

        net_pnl_pct = entry[0]
        outcome = entry[1]
        timestamp = entry[3]

        # Extract hour from timestamp
        import datetime
        dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        hour = dt.hour

        stats = hour_stats[hour]
        if outcome == "WIN":
            stats["wins"] += 1
        elif outcome == "LOSS":
            stats["losses"] += 1
        else:
            stats["flats"] += 1

        stats["total_pnl"] += net_pnl_pct

    return hour_stats


def compute_metrics(stats):
    """Compute PF and expectancy for hour stats."""
    if stats["losses"] == 0:
        pf = 1.0 if stats["wins"] > 0 else 0.0
    else:
        pf = stats["wins"] / stats["losses"] if stats["wins"] > 0 else 0.0

    n = stats["wins"] + stats["losses"] + stats["flats"]
    expectancy = stats["total_pnl"] / n if n > 0 else 0.0

    return pf, expectancy, n


def recommend_action(pf, expectancy, n):
    """Recommend action for time filtering."""
    if n < 30:
        return "SHADOW_ONLY"  # Not enough data
    elif pf < 0.70 and expectancy < 0:
        return "CONSIDER_BLOCK"
    elif pf < 0.90 and expectancy < -0.02:
        return "SIZE_DOWN_RECOMMENDED"
    else:
        return "ALLOW"


def main():
    """Generate time-of-day report."""
    state = load_learning_state()
    if not state:
        return 1

    hour_stats = analyze_by_hour(state)

    print("\n" + "=" * 80)
    print("PHASE 5: TIME-OF-DAY PERFORMANCE REPORT")
    print("=" * 80)
    print(f"Data source: {Path('server_local_backups/paper_adaptive_learning_state.json')}")
    print(f"Lifetime trades: {state.get('lifetime_n', 0)}")
    print(f"Analysis window: rolling100")
    print()

    # Print header
    print(f"{'Hour':<5} {'N':>4} {'Wins':>4} {'Loss':>4} {'Flat':>4} {'PF':>6} {'Expect%':>8} {'Recommendation':<20}")
    print("-" * 80)

    # Print by hour
    for hour in sorted(hour_stats.keys()):
        stats = hour_stats[hour]
        pf, expectancy, n = compute_metrics(stats)
        action = recommend_action(pf, expectancy, n)

        print(
            f"{hour:<5} {n:>4} {stats['wins']:>4} {stats['losses']:>4} {stats['flats']:>4} "
            f"{pf:>6.2f}x {expectancy*100:>7.2f}% {action:<20}"
        )

    print("-" * 80)
    print()
    print("RECOMMENDATIONS:")
    print("  SHADOW_ONLY: Not enough data yet (< 30 trades), monitoring only")
    print("  ALLOW: Good performance, trade normally")
    print("  SIZE_DOWN_RECOMMENDED: Borderline, consider 0.5x sizing")
    print("  CONSIDER_BLOCK: Poor performance (PF < 0.70 AND negative EV), block if enabled")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
