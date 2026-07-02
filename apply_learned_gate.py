#!/usr/bin/env python3
"""
Autonomous Parameter Change Executor

Applies learned optimal parameter values to the bot configuration.
Called by monitoring daemon when autonomous decisions are made.
Safely updates code, commits, and pushes to GitHub for auto-deployment.
"""

import sys
import re
import subprocess
from pathlib import Path


def update_entry_gate(new_gate_value: float) -> bool:
    """Update entry_gate_pct in signal_generator.py and deploy."""

    sig_gen_path = Path("/opt/cryptomaster/src/services/signal_generator.py")

    if not sig_gen_path.exists():
        print(f"❌ File not found: {sig_gen_path}")
        return False

    # Read current file
    with open(sig_gen_path, 'r') as f:
        content = f.read()

    # Find and replace gate value
    # Pattern: if recent_range < 0.XXXX:
    pattern = r'(if recent_range\s*<\s*)0\.\d{4}:'
    replacement = rf'\g<1>{new_gate_value:.4f}:'

    new_content = re.sub(pattern, replacement, content)

    if new_content == content:
        print(f"❌ Could not find gate pattern in signal_generator.py")
        return False

    # Write updated file
    with open(sig_gen_path, 'w') as f:
        f.write(new_content)

    print(f"✅ Updated entry_gate_pct to {new_gate_value:.4f} ({new_gate_value*100:.2f}%)")

    # Commit and push
    try:
        subprocess.run(
            ['git', 'add', 'src/services/signal_generator.py'],
            cwd='/opt/cryptomaster',
            capture_output=True,
            check=True
        )

        commit_msg = f"""Cycle autonomous adjustment: entry_gate_pct = {new_gate_value:.4f}

Autonomous parameter adjustment based on learning system recommendation.
Applied during monitoring cycle when WR stable and gate outside learned bounds.

Gate change: {new_gate_value:.4f} ({new_gate_value*100:.2f}%)
Rationale: Learned optimal value from Phase 2 analysis
Expected: Adjust entry volume while maintaining quality

Co-Authored-By: Autonomous Learning System <learning@cryptomaster.bot>"""

        subprocess.run(
            ['git', 'commit', '-m', commit_msg],
            cwd='/opt/cryptomaster',
            capture_output=True,
            check=True
        )

        subprocess.run(
            ['git', 'push', 'origin', 'main'],
            cwd='/opt/cryptomaster',
            capture_output=True,
            check=True
        )

        print(f"✅ Committed and pushed to GitHub")
        print(f"   Auto-deployment triggered for Hetzner")
        return True

    except subprocess.CalledProcessError as e:
        print(f"❌ Git operation failed: {e}")
        # Revert file
        with open(sig_gen_path, 'w') as f:
            f.write(content)
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: apply_learned_gate.py <gate_value>")
        print("Example: apply_learned_gate.py 0.0048")
        sys.exit(1)

    try:
        new_gate = float(sys.argv[1])
        if new_gate <= 0 or new_gate > 1:
            print(f"❌ Invalid gate value: {new_gate}")
            sys.exit(1)

        success = update_entry_gate(new_gate)
        sys.exit(0 if success else 1)
    except ValueError:
        print(f"❌ Invalid gate value: {sys.argv[1]}")
        sys.exit(1)
