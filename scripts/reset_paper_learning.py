#!/usr/bin/env python3
"""
Reset paper learning state completely.

Backs up old state and creates fresh metrics for new learning cycle.
"""
import json
import shutil
import sys
import time
from pathlib import Path


def main():
    state_file = Path("server_local_backups/paper_adaptive_learning_state.json")

    # Ensure directory exists
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Backup existing state
    if state_file.exists():
        timestamp = int(time.time())
        backup_file = state_file.parent / f"paper_adaptive_learning_state.json.backup.{timestamp}"
        try:
            shutil.copy2(state_file, backup_file)
            print(f"✅ Backed up old state to: {backup_file}")
        except Exception as e:
            print(f"⚠️  Failed to backup: {e}")
            return 1

    # Create fresh learning state
    fresh_state = {
        "lifetime_n": 0,
        "lifetime_pf": 1.0,
        "lifecycle": "PAPER_COLLECTING",
        "rolling20": [],
        "rolling50": [],
        "rolling100": [],
        "segment_weights": {},
        "last_update": time.time(),
        "reset_timestamp": time.time(),
        "reset_reason": "user_requested_clean_restart",
    }

    try:
        with open(state_file, "w") as f:
            json.dump(fresh_state, f, indent=2)
        print(f"\n✅ Reset learning state: {state_file}")
        print(f"\n📊 NEW STATE:")
        print(f"   Lifetime trades: 0")
        print(f"   Profit Factor:   1.00x")
        print(f"   Status:          PAPER_COLLECTING")
        print(f"   Rolling50:       [] (empty)")
        print(f"\n🚀 Ready to begin new learning cycle")
        return 0
    except Exception as e:
        print(f"❌ Failed to reset state: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
