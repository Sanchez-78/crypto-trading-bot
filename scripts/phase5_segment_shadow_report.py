#!/usr/bin/env python3
"""Phase 5B Shadow Segment Learning Feedback Report

Computes what learning feedback WOULD do without affecting trades.
Shows which segments would be promoted/demoted if learning feedback was enabled.

Usage:
  python3 scripts/phase5_segment_shadow_report.py
"""
import json
import sys
import subprocess
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

def calculate_segment_priority(segment_data):
    """Calculate priority: PROMOTE, NEUTRAL, DEMOTE, INSUFFICIENT_DATA.

    Args:
        segment_data: dict with n, wins, losses, rolling50_pf, rolling50_expectancy

    Returns:
        (priority, confidence_score)
    """
    n = segment_data.get("n", 0)
    rolling50_pf = segment_data.get("rolling50_pf", 0.5)
    rolling50_expectancy = segment_data.get("rolling50_expectancy", 0)

    # Insufficient data
    if n < 20:
        return "INSUFFICIENT_DATA", 0.0

    # Promote: good PF and positive expectancy
    if rolling50_pf >= 1.15 and rolling50_expectancy > 0:
        confidence = min(1.0, rolling50_pf / 2.0)  # 1.15 → 0.58, 2.0 → 1.0
        return "PROMOTE", confidence

    # Neutral: acceptable
    if rolling50_pf >= 0.90:
        confidence = min(1.0, rolling50_pf / 1.5)  # 0.90 → 0.60, 1.5 → 1.0
        return "NEUTRAL", confidence

    # Demote: poor PF or negative expectancy
    if rolling50_pf < 0.75 or rolling50_expectancy < -0.10:
        confidence = min(1.0, (1.0 - rolling50_pf) / 0.5)  # 0.75 → 0.5, 0.25 → 1.0
        return "DEMOTE", confidence

    # Default neutral
    return "NEUTRAL", 0.5

def analyze_segments():
    """Analyze all segments for shadow feedback."""
    learning_state = load_adaptive_learning_state()

    promoted = []
    demoted = []
    neutral = []
    insufficient = []

    for segment_key, segment_data in learning_state.items():
        priority, confidence = calculate_segment_priority(segment_data)

        entry = {
            "segment": segment_key,
            "n": segment_data.get("n", 0),
            "pf": round(segment_data.get("rolling50_pf", 0.5), 2),
            "expectancy": round(segment_data.get("rolling50_expectancy", 0), 4),
            "confidence": round(confidence, 2),
            "multiplier": 1.5 if priority == "PROMOTE" else (0.5 if priority == "DEMOTE" else 1.0),
        }

        if priority == "PROMOTE":
            promoted.append(entry)
        elif priority == "DEMOTE":
            demoted.append(entry)
        elif priority == "NEUTRAL":
            neutral.append(entry)
        else:
            insufficient.append(entry)

    # Sort by confidence
    promoted.sort(key=lambda x: x["confidence"], reverse=True)
    demoted.sort(key=lambda x: x["confidence"], reverse=True)
    neutral.sort(key=lambda x: x["n"], reverse=True)
    insufficient.sort(key=lambda x: x["n"], reverse=True)

    return {
        "promoted": promoted,
        "demoted": demoted,
        "neutral": neutral,
        "insufficient": insufficient,
    }

def estimate_impact(analysis):
    """Estimate what impact shadow feedback would have."""
    total_segments = len(analysis["promoted"]) + len(analysis["demoted"]) + \
                     len(analysis["neutral"]) + len(analysis["insufficient"])

    # If we promoted high-PF segments and demoted low-PF, we'd improve quality
    if analysis["promoted"]:
        avg_promote_pf = sum(x["pf"] for x in analysis["promoted"]) / len(analysis["promoted"])
    else:
        avg_promote_pf = 1.0

    if analysis["demoted"]:
        avg_demote_pf = sum(x["pf"] for x in analysis["demoted"]) / len(analysis["demoted"])
    else:
        avg_demote_pf = 0.5

    # Estimate: if we entered promoted segments 50% more and demoted 50% less
    # Quality impact ≈ weighted average PF shift
    quality_improvement = round(((avg_promote_pf - 1.0) * 50 / 100), 2)  # percent

    return {
        "total_segments": total_segments,
        "promoted_count": len(analysis["promoted"]),
        "demoted_count": len(analysis["demoted"]),
        "neutral_count": len(analysis["neutral"]),
        "insufficient_count": len(analysis["insufficient"]),
        "estimated_quality_improvement_percent": quality_improvement,
        "readiness_contamination_risk": "NONE (shadow-only, no live effect)",
    }

def print_report(analysis, impact):
    """Print formatted report."""
    print("╔════════════════════════════════════════════════════════════════════════════════╗")
    print(f"║ PHASE 5B SHADOW SEGMENT LEARNING FEEDBACK ({datetime.now().strftime('%Y-%m-%d %H:%M UTC')})")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")
    print()

    print("📊 SUMMARY")
    print(f"  Total segments:          {impact['total_segments']:>6}")
    print(f"  Promoted (high-PF):      {impact['promoted_count']:>6}")
    print(f"  Demoted (low-PF):        {impact['demoted_count']:>6}")
    print(f"  Neutral:                 {impact['neutral_count']:>6}")
    print(f"  Insufficient data:       {impact['insufficient_count']:>6}")
    print()

    print("🚀 TOP PROMOTED SEGMENTS (Would get 1.5x entry priority)")
    if analysis["promoted"]:
        for seg in analysis["promoted"][:5]:
            print(f"  {seg['segment']:35} PF={seg['pf']:>5.2f} n={seg['n']:>3} conf={seg['confidence']:.2f}")
    else:
        print("  (none)")
    print()

    print("📉 TOP DEMOTED SEGMENTS (Would get 0.5x entry priority)")
    if analysis["demoted"]:
        for seg in analysis["demoted"][:5]:
            print(f"  {seg['segment']:35} PF={seg['pf']:>5.2f} n={seg['n']:>3} conf={seg['confidence']:.2f}")
    else:
        print("  (none)")
    print()

    print("⚖️  NEUTRAL SEGMENTS (Would keep 1.0x priority)")
    if analysis["neutral"]:
        for seg in analysis["neutral"][:5]:
            print(f"  {seg['segment']:35} PF={seg['pf']:>5.2f} n={seg['n']:>3}")
    else:
        print("  (none)")
    print()

    print("❓ INSUFFICIENT DATA (Need >20 samples)")
    if analysis["insufficient"]:
        for seg in analysis["insufficient"][:5]:
            print(f"  {seg['segment']:35} n={seg['n']:>3} (need {20-seg['n']} more)")
    else:
        print("  (all segments have sufficient data)")
    print()

    print("💡 ESTIMATED IMPACT (if enabled)")
    print(f"  Quality improvement:     {impact['estimated_quality_improvement_percent']:>+5.1f}%")
    print(f"  Readiness contamination: {impact['readiness_contamination_risk']}")
    print()

    print("⚠️  LIVE EFFECT")
    print("  Currently: SHADOW ONLY (no live effect)")
    print("  To enable: Requires explicit configuration change after 24h review")
    print()

    print("╔════════════════════════════════════════════════════════════════════════════════╗")
    print("║ End of Phase 5B Report")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")

def main():
    analysis = analyze_segments()
    impact = estimate_impact(analysis)
    print_report(analysis, impact)

if __name__ == "__main__":
    main()
