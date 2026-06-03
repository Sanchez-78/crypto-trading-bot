#!/usr/bin/env python3
"""
Audit paper learning state in local Firebase backup.

Shows current metrics and recommends action.
"""
import json
import sys
from pathlib import Path


def main():
    state_file = Path("server_local_backups/paper_adaptive_learning_state.json")

    if not state_file.exists():
        print(f"❌ Learning state file not found: {state_file}")
        sys.exit(1)

    try:
        with open(state_file) as f:
            state = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load state: {e}")
        sys.exit(1)

    # Extract metrics
    lifetime_n = state.get("lifetime_n", 0)
    lifetime_pf = state.get("lifetime_pf", 1.0)
    lifecycle = state.get("lifecycle", "unknown")
    rolling50 = state.get("rolling50", [])

    # Analyze rolling50
    wins = sum(1 for r in rolling50 if len(r) > 1 and r[1] == "WIN")
    losses = sum(1 for r in rolling50 if len(r) > 1 and r[1] == "LOSS")
    flats = sum(1 for r in rolling50 if len(r) > 1 and r[1] == "FLAT")
    total_recent = len(rolling50)

    win_rate = (wins / total_recent * 100) if total_recent > 0 else 0

    # Print summary
    print("\n" + "=" * 70)
    print("📊 PAPER LEARNING STATE AUDIT")
    print("=" * 70)
    print(f"\n📈 LIFETIME STATISTICS")
    print(f"   Total trades:        {lifetime_n}")
    print(f"   Profit Factor:       {lifetime_pf:.2f}x")
    print(f"   Status:              {lifecycle}")

    print(f"\n🎯 RECENT TRADES (rolling50)")
    print(f"   Total:               {total_recent}")
    print(f"   ✅ Wins (WIN):       {wins}")
    print(f"   ❌ Losses (LOSS):    {losses}")
    print(f"   ⏸️  Neutral (FLAT):  {flats}")
    print(f"   Win Rate:            {win_rate:.1f}%")

    # Recommendation
    print(f"\n🔍 RECOMMENDATION")
    if lifetime_n == 0:
        print(f"   ✅ Fresh start - no old data to clean")
        print(f"   → Ready to begin learning")
    elif win_rate == 0 and lifetime_pf < 0.1:
        print(f"   ⚠️  Old data is not useful (WR=0%, PF<0.1)")
        print(f"   → Recommend: python3 scripts/reset_paper_learning.py")
        print(f"      This will backup old state and start fresh")
    elif win_rate > 0 and lifetime_pf > 1.0:
        print(f"   ✅ Learning is working well (WR>{win_rate:.1f}%, PF>{lifetime_pf:.2f}x)")
        print(f"   → Keep current state and continue trading")
    elif lifetime_n >= 50:
        print(f"   🟡 Has enough data but metrics are mixed")
        print(f"   → Consider reset if quality not improving")
    else:
        print(f"   🔄 Still collecting data ({lifetime_n}/50 trades)")
        print(f"   → Continue trading to collect more samples")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
