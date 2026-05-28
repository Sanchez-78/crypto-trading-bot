#!/usr/bin/env python3
"""Manual test runner for V5 acceptance using pytest library."""

import sys
import subprocess

def main():
    """Run V5 tests using pytest library directly."""

    # List of test modules
    test_modules = [
        'tests/v5_bot/test_quota_guard.py',
        'tests/v5_bot/test_outbox.py',
        'tests/v5_bot/test_learning.py',
        'tests/v5_bot/test_strategy.py',
        'tests/v5_bot/test_futures_feed.py',
        'tests/v5_bot/test_paper_lifecycle.py',
    ]

    print("=" * 70)
    print("V5 ACCEPTANCE TEST SUITE")
    print("=" * 70)
    print()

    # Run pytest
    cmd = [sys.executable, '-m', 'pytest'] + test_modules + ['-v', '--tb=short']

    result = subprocess.run(cmd, capture_output=False)

    print()
    print("=" * 70)
    if result.returncode == 0:
        print("TEST RESULT: ALL TESTS PASSED")
    else:
        print("TEST RESULT: SOME TESTS FAILED")
    print("=" * 70)

    return result.returncode

if __name__ == '__main__':
    sys.exit(main())
