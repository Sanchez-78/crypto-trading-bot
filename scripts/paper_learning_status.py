#!/usr/bin/env python3
"""Paper Learning Status Report — Detailed segment performance & learning metrics

Shows:
  - Segments with samples (symbol:regime:side)
  - Win rate & profit factor per segment
  - Rolling 20/50/100 metrics
  - Learning updates (canonical + V5)
  - Expectancy per segment
  - Progress to READY status

Usage:
  python3 scripts/paper_learning_status.py
"""
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

def load_adaptive_learning_state():
    """Load paper adaptive learning state."""
    state_file = Path("server_local_backups/paper_adaptive_learning_state.json")
    if not state_file.exists():
        return {}

    try:
        with open(state_file) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading learning state: {e}", file=sys.stderr)
        return {}

def analyze_segments(learning_state):
    """Analyze all learning segments."""
    segments = {}

    for segment_key, segment_data in learning_state.items():
        if not isinstance(segment_data, dict):
            continue

        n = segment_data.get("n", 0)
        if n == 0:
            continue  # Skip empty segments

        wins = segment_data.get("wins", 0)
        losses = segment_data.get("losses", 0)
        flats = segment_data.get("flats", 0)

        # Calculate metrics
        pf = segment_data.get("rolling50_pf", 0.0)
        expectancy = segment_data.get("rolling50_expectancy", 0.0)
        rolling20_pf = segment_data.get("rolling20_pf", 0.0)
        rolling100_pf = segment_data.get("rolling100_pf", 0.0)

        win_rate = (wins / n * 100) if n > 0 else 0

        segments[segment_key] = {
            "n": n,
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "win_rate": win_rate,
            "pf": pf,
            "rolling20_pf": rolling20_pf,
            "rolling100_pf": rolling100_pf,
            "expectancy": expectancy,
            "status": "READY" if n >= 20 else f"LEARNING ({n}/20)",
        }

    return segments

def print_paper_learning_status(segments):
    """Print formatted paper learning status."""
    print("╔════════════════════════════════════════════════════════════════════════════════╗")
    print(f"║ PAPER LEARNING STATUS REPORT ({datetime.now().strftime('%Y-%m-%d %H:%M UTC')})")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")
    print()

    # Overall stats
    total_segments = len(segments)
    ready_segments = sum(1 for s in segments.values() if s["n"] >= 20)
    total_samples = sum(s["n"] for s in segments.values())
    total_learning_updates = total_samples  # Approx

    print("📊 OVERALL LEARNING STATUS")
    print(f"  Total segments:           {total_segments:>3}")
    print(f"  Ready (n >= 20):          {ready_segments:>3}")
    print(f"  Learning (n < 20):        {total_segments - ready_segments:>3}")
    print(f"  Total samples collected:  {total_samples:>3}")
    print(f"  Progress to READY:        {total_learning_updates:>3} / 50 trades needed")
    print()

    if total_learning_updates >= 50:
        print("  ✅ LEARNING READY — System can transition from PAPER to next phase")
    elif total_learning_updates >= 30:
        print("  🟡 ON TRACK — ~50% of the way to READY (collect 20+ more)")
    else:
        print("  🔄 EARLY STAGE — < 30% progress, continue data collection")
    print()

    # Top segments by sample size
    segments_by_n = sorted(segments.items(), key=lambda x: x[1]["n"], reverse=True)

    print("🎯 TOP SEGMENTS BY SAMPLES (Ready for feedback)")
    print()
    if ready_segments > 0:
        print("   READY SEGMENTS (n >= 20)")
        for segment_key, stats in segments_by_n[:10]:
            if stats["n"] >= 20:
                pf_bar = "━" * int(min(stats["pf"] * 5, 20))
                print(f"   {segment_key:40} n={stats['n']:>3} "
                      f"WR={stats['win_rate']:>5.1f}% "
                      f"PF={stats['pf']:>5.2f} {pf_bar}")
        print()

    # Learning segments
    learning_segs = [s for s in segments_by_n if s[1]["n"] < 20]
    if learning_segs:
        print("   LEARNING SEGMENTS (n < 20, collecting data)")
        for segment_key, stats in learning_segs[:10]:
            progress = int(stats["n"] / 20 * 20)
            bar = "█" * progress + "░" * (20 - progress)
            print(f"   {segment_key:40} [{bar}] {stats['n']:>2}/20")
        print()

    # Segment performance breakdown
    print("💡 SEGMENT PERFORMANCE ANALYSIS")
    print()

    # Best performers
    best_segments = sorted(segments.items(), key=lambda x: x[1]["pf"], reverse=True)[:5]
    if best_segments:
        print("   Best performers (by PF):")
        for segment_key, stats in best_segments:
            if stats["pf"] > 1.0:
                print(f"   ✅ {segment_key:40} PF={stats['pf']:.2f} n={stats['n']:>2}")
        print()

    # Struggling segments
    struggling = sorted(segments.items(), key=lambda x: x[1]["pf"])[:5]
    if struggling:
        print("   Struggling (by PF):")
        for segment_key, stats in struggling:
            if stats["pf"] < 1.0 and stats["n"] >= 5:
                print(f"   ❌ {segment_key:40} PF={stats['pf']:.2f} n={stats['n']:>2}")
        print()

    # Expectancy analysis
    print("📈 EXPECTANCY ANALYSIS")
    print()
    positive_ev = sum(1 for s in segments.values() if s["expectancy"] > 0)
    negative_ev = sum(1 for s in segments.values() if s["expectancy"] < 0)

    print(f"   Positive expectancy: {positive_ev} segments (good)")
    print(f"   Negative expectancy: {negative_ev} segments (need work)")
    print()

    if positive_ev > 0:
        best_ev = max(segments.items(), key=lambda x: x[1]["expectancy"])
        print(f"   Highest EV: {best_ev[0]} (+{best_ev[1]['expectancy']:.6f})")
    if negative_ev > 0:
        worst_ev = min(segments.items(), key=lambda x: x[1]["expectancy"])
        print(f"   Lowest EV:  {worst_ev[0]} ({worst_ev[1]['expectancy']:.6f})")
    print()

    # Rolling metrics summary
    print("🔄 ROLLING METRICS SUMMARY")
    print()

    rolling20_avg = sum(s["rolling20_pf"] for s in segments.values()) / len(segments) if segments else 0
    rolling50_avg = sum(s["rolling50_pf"] for s in segments.values()) / len(segments) if segments else 0
    rolling100_avg = sum(s["rolling100_pf"] for s in segments.values()) / len(segments) if segments else 0

    print(f"   Rolling 20:   avg PF = {rolling20_avg:.2f}")
    print(f"   Rolling 50:   avg PF = {rolling50_avg:.2f}")
    print(f"   Rolling 100:  avg PF = {rolling100_avg:.2f}")
    print()

    # Learning readiness
    print("🎓 LEARNING FEEDBACK READINESS")
    print()

    if ready_segments >= 3:
        promoted = sum(1 for s in segments.values() if s["pf"] >= 1.15)
        demoted = sum(1 for s in segments.values() if s["pf"] < 0.75)
        print(f"   ✅ READY FOR FEEDBACK")
        print(f"      Promote-able segments (PF >= 1.15): {promoted}")
        print(f"      Demote-able segments (PF < 0.75):   {demoted}")
        if promoted > 0 or demoted > 0:
            print(f"      → Could improve quality by prioritizing {promoted} profitable segments")
    else:
        print(f"   ⏳ NOT YET READY ({ready_segments}/3 minimum segments needed)")
        print(f"      Need {3 - ready_segments} more segment(s) with 20+ samples")
    print()

    # Final verdict
    print("📋 VERDICT")
    print()
    if total_learning_updates >= 50:
        print("   ✅ LEARNING COMPLETE — Ready for next phase")
        print("      Recommended: Enable learning feedback & decision phase")
    elif total_learning_updates >= 30:
        print("   🟡 ON TRACK — 60% progress to READY")
        print("      Recommended: Continue data collection 2-3 more days")
    else:
        print("   🔄 EARLY STAGE — < 30% progress")
        print("      Recommended: Continue freeze period, collect baseline")
    print()

    print("╔════════════════════════════════════════════════════════════════════════════════╗")
    print("║ End of Paper Learning Status Report")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")

def main():
    learning_state = load_adaptive_learning_state()

    if not learning_state:
        print("❌ No learning state found at server_local_backups/paper_adaptive_learning_state.json")
        print("   System may not have generated learning data yet")
        sys.exit(1)

    segments = analyze_segments(learning_state)

    if not segments:
        print("❌ No segments with samples found in learning state")
        print("   System may not have completed any paper trades yet")
        sys.exit(1)

    print_paper_learning_status(segments)

if __name__ == "__main__":
    main()
