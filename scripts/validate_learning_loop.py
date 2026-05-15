#!/usr/bin/env python3
"""
validate_learning_loop.py — Check paper training chain completeness in log output.

Usage:
    python scripts/validate_learning_loop.py --log-file logs/latest.log
    journalctl -u cryptomaster -n 1000 | python scripts/validate_learning_loop.py

Output:
    LEARNING_LOOP_OK=true/false
    missing_stages=[...]
    counts={...}

Exit code: 0 if all stages found, 1 if any missing.
"""

import sys
import argparse
import re
from collections import Counter

REQUIRED_STAGES = [
    "SIGNAL_RAW",
    "RDE_CANDIDATE",
    "TRAINING_SAMPLER_CHECK",
    "PAPER_ENTRY_ATTEMPT",
    "PAPER_TRAIN_ENTRY",
    "PAPER_TIMEOUT_SCAN",
    "PAPER_CLOSE_PATH",
    "PAPER_EXIT",
    "LEARNING_UPDATE",
    "PAPER_TRAIN_CLOSED",
]

# Pattern: any log line containing the stage tag
_STAGE_PATTERNS = {stage: re.compile(rf"\[{re.escape(stage)}\]") for stage in REQUIRED_STAGES}
# Special: LEARNING_UPDATE must have ok=True
_LEARNING_UPDATE_OK = re.compile(r"\[LEARNING_UPDATE\].*ok=True")


def scan_lines(lines: list[str]) -> tuple[bool, list[str], dict]:
    counts: Counter = Counter()
    learning_update_ok = 0

    for line in lines:
        for stage, pat in _STAGE_PATTERNS.items():
            if pat.search(line):
                counts[stage] += 1
        if _LEARNING_UPDATE_OK.search(line):
            learning_update_ok += 1

    counts["LEARNING_UPDATE_ok=True"] = learning_update_ok

    missing = [s for s in REQUIRED_STAGES if counts.get(s, 0) == 0]

    # LEARNING_UPDATE present but ok=True count is 0 → partial failure
    if counts.get("LEARNING_UPDATE", 0) > 0 and learning_update_ok == 0:
        if "LEARNING_UPDATE_ok=False" not in missing:
            missing.append("LEARNING_UPDATE_ok=True (present but ok=True never logged)")

    ok = len(missing) == 0
    return ok, missing, dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate paper training chain in logs")
    parser.add_argument("--log-file", "-f", help="Log file to scan (default: stdin)")
    args = parser.parse_args()

    if args.log_file:
        try:
            with open(args.log_file) as fh:
                lines = fh.readlines()
        except FileNotFoundError:
            print(f"ERROR: log file not found: {args.log_file}", file=sys.stderr)
            return 2
    else:
        lines = sys.stdin.readlines()

    ok, missing, counts = scan_lines(lines)

    print(f"LEARNING_LOOP_OK={str(ok).lower()}")
    if missing:
        print(f"missing_stages={missing}")
    else:
        print("missing_stages=[]")
    print(f"counts={counts}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
