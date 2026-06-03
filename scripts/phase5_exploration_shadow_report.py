#!/usr/bin/env python3
"""Phase 5D Deterministic PAPER-only Exploration Shadow Report

Plans deterministic exploration candidates (NOT random epsilon-greedy).
Shows what segments WOULD be explored if exploration was enabled.

Exploration candidates:
  - segment_n < 10 (underexplored)
  - no samples in past 6 hours (stale)
  - near-miss cost-edge (could pass with small improvement)
  - underrepresented symbol/regime/side

Usage:
  python3 scripts/phase5_exploration_shadow_report.py
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
    except Exception:
        return {}

def find_exploration_candidates(learning_state):
    """Find segments eligible for exploration."""
    candidates = []

    # Goal: cover all symbol/regime/side combinations
    # Current: only have high-PF segments
    # Missing: low-n, stale, or underrepresented segments

    for segment_key, segment_data in learning_state.items():
        n = segment_data.get("n", 0)
        last_update = segment_data.get("last_update_ts", 0)

        reasons = []

        # Criterion 1: Underexplored (n < 10)
        if n < 10:
            reasons.append(f"underexplored (n={n})")

        # Criterion 2: Stale (no update in 6 hours)
        time_since_update = (datetime.now().timestamp() - last_update) / 3600
        if time_since_update > 6:
            reasons.append(f"stale ({time_since_update:.1f}h)")

        # Criterion 3: Near-miss cost-edge
        pf = segment_data.get("rolling50_pf", 0.5)
        if 0.7 < pf < 1.0:  # Could be profitable with small tuning
            reasons.append(f"near_miss_pf={pf:.2f}")

        if reasons and n < 50:  # Don't over-explore well-trained segments
            candidates.append({
                "segment": segment_key,
                "n": n,
                "pf": round(segment_data.get("rolling50_pf", 0.5), 2),
                "reasons": reasons,
                "priority": len(reasons),  # More reasons = higher priority
            })

    # Sort by priority
    candidates.sort(key=lambda x: x["priority"], reverse=True)

    return candidates

def estimate_coverage(learning_state, candidates):
    """Estimate what symbol/regime/side coverage we'd achieve."""
    # Extract all segments into symbol/regime/side tuples
    all_segments = set()
    covered_segments = set()

    for segment_key in learning_state:
        parts = segment_key.split(":")
        if len(parts) >= 3:
            symbol, regime, side = parts[0], parts[1], parts[2]
            all_segments.add((symbol, regime, side))

    for candidate in candidates:
        parts = candidate["segment"].split(":")
        if len(parts) >= 3:
            symbol, regime, side = parts[0], parts[1], parts[2]
            covered_segments.add((symbol, regime, side))

    return {
        "total_possible": len(all_segments),
        "already_covered": len(covered_segments),
        "coverage_percent": round(len(covered_segments) / len(all_segments) * 100, 1) if all_segments else 0,
    }

def calculate_exploration_caps():
    """Calculate safe exploration caps."""
    return {
        "max_open_per_symbol": 1,
        "max_open_global": 2,
        "max_per_segment_per_30min": 1,
        "max_per_hour_global": 2,
        "outbox_health_required": "clean",
        "quota_risk_allowed": False,
        "recon_required": "OK",
        "crash_recent_allowed": False,
    }

def print_report(candidates, coverage, caps):
    """Print formatted report."""
    print("╔════════════════════════════════════════════════════════════════════════════════╗")
    print(f"║ PHASE 5D DETERMINISTIC EXPLORATION PLAN ({datetime.now().strftime('%Y-%m-%d %H:%M UTC')})")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")
    print()

    print("📊 COVERAGE ANALYSIS")
    print(f"  Possible symbol:regime:side combinations:  {coverage['total_possible']:>3}")
    print(f"  Already covered by learning:               {coverage['already_covered']:>3}")
    print(f"  Coverage:                                  {coverage['coverage_percent']:>5.1f}%")
    print()

    print("🚀 EXPLORATION CANDIDATES (Deterministic, not random)")
    if candidates:
        for candidate in candidates[:10]:
            print(f"  {candidate['segment']:35} n={candidate['n']:>2} pf={candidate['pf']:>5.2f} reasons={','.join(candidate['reasons'][:2])}")
    else:
        print("  (all segments well-explored)")
    print()

    print("⚡ ESTIMATED DAILY IMPACT")
    if candidates:
        safe_entries_per_day = min(4, len(candidates))  # 2 per hour global cap = ~4-5 per day
        print(f"  Would-have-explored entries/day:    {safe_entries_per_day:>3}")
        print(f"  New samples per day:                {safe_entries_per_day:>3}")
        print(f"  Quota impact (extra reads):         ~5-10 per day (minimal)")
    else:
        print("  (no candidates, all segments covered)")
    print()

    print("🛡️  SAFETY CAPS (Hard limits if enabled)")
    print(f"  Max open per symbol:                 {caps['max_open_per_symbol']}")
    print(f"  Max open globally:                   {caps['max_open_global']}")
    print(f"  Max per segment per 30min:           {caps['max_per_segment_per_30min']}")
    print(f"  Max per hour globally:               {caps['max_per_hour_global']}")
    print()

    print("📋 EXPLORATION CONSTRAINTS")
    print("  Mode:                                SHADOW_ONLY (no live effect)")
    print("  Readiness eligibility:               NO (readiness_eligible=false)")
    print("  Real readiness impact:               NONE (isolated learning source)")
    print("  Admission bucket:                    PAPER_DETERMINISTIC_EXPLORATION")
    print()

    print("⚠️  CURRENT STATUS")
    print("  Status:                              SHADOW_ONLY (showing what WOULD happen)")
    print("  Live effect:                         DISABLED")
    print("  Quota contamination risk:            NONE")
    print("  Readiness contamination risk:        NONE")
    print()

    print("📌 NEXT STEPS")
    print("  After 24h of shadow data review:")
    print("    1. Confirm exploration candidate quality")
    print("    2. If good: enable PAPER_DETERMINISTIC_EXPLORATION=true")
    print("    3. Monitor daily exploration activity")
    print("    4. Measure: do new segments improve profitability?")
    print()

    print("╔════════════════════════════════════════════════════════════════════════════════╗")
    print("║ End of Phase 5D Report")
    print("╚════════════════════════════════════════════════════════════════════════════════╝")

def main():
    learning_state = load_adaptive_learning_state()
    candidates = find_exploration_candidates(learning_state)
    coverage = estimate_coverage(learning_state, candidates)
    caps = calculate_exploration_caps()

    print_report(candidates, coverage, caps)

if __name__ == "__main__":
    main()
