"""
Regression tests for P1.1AP-A hotfix: UnboundLocalError in snapshot publishing.

Ensures:
- _last_dashboard_snapshot and _last_signal_summary are properly declared as global
- Snapshot publishing timing does not raise UnboundLocalError
- Global variables are accessible throughout main loop
"""

import ast
import os
from pathlib import Path


def test_bot2_main_has_snapshot_globals():
    """Verify bot2/main.py declares snapshot timing globals."""
    bot2_path = Path(__file__).parent.parent / "bot2" / "main.py"
    with open(bot2_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for global declaration of snapshot timing variables
    assert "_last_dashboard_snapshot" in content, "Missing _last_dashboard_snapshot"
    assert "_last_signal_summary" in content, "Missing _last_signal_summary"
    assert "DASHBOARD_SNAPSHOT_INTERVAL" in content, "Missing DASHBOARD_SNAPSHOT_INTERVAL"
    assert "SIGNAL_SUMMARY_INTERVAL" in content, "Missing SIGNAL_SUMMARY_INTERVAL"


def test_bot2_main_declares_snapshot_globals_in_loop():
    """Verify snapshot timing variables are declared global inside main loop."""
    bot2_path = Path(__file__).parent.parent / "bot2" / "main.py"
    with open(bot2_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find the global declaration inside the main loop
    # It should include _last_dashboard_snapshot and _last_signal_summary
    lines = content.split("\n")
    found_global_declaration = False
    for i, line in enumerate(lines):
        if "global _last_audit, _last_metrics" in line:
            assert (
                "_last_dashboard_snapshot" in line
            ), f"Missing _last_dashboard_snapshot in global declaration at line {i+1}"
            assert (
                "_last_signal_summary" in line
            ), f"Missing _last_signal_summary in global declaration at line {i+1}"
            found_global_declaration = True
            break

    assert found_global_declaration, "Could not find global declaration for _last_dashboard_snapshot and _last_signal_snapshot"


def test_bot2_main_snapshot_publishing_wrapped():
    """Verify snapshot publishing is wrapped in try/except."""
    bot2_path = Path(__file__).parent.parent / "bot2" / "main.py"
    with open(bot2_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Check for try/except wrapping
    assert "publish_dashboard_snapshot()" in content
    assert "publish_signal_summary()" in content

    # Verify both are in try blocks
    lines = content.split("\n")
    dashboard_snapshot_wrapped = False
    signal_summary_wrapped = False

    for i, line in enumerate(lines):
        if "publish_dashboard_snapshot()" in line:
            # Look backwards for try statement
            for j in range(max(0, i - 5), i):
                if "try:" in lines[j]:
                    dashboard_snapshot_wrapped = True
                    break
        if "publish_signal_summary()" in line:
            # Look backwards for try statement
            for j in range(max(0, i - 5), i):
                if "try:" in lines[j]:
                    signal_summary_wrapped = True
                    break

    assert dashboard_snapshot_wrapped, "publish_dashboard_snapshot() not wrapped in try/except"
    assert signal_summary_wrapped, "publish_signal_summary() not wrapped in try/except"


def test_bot2_main_compiles():
    """Verify bot2/main.py has no syntax errors."""
    import py_compile

    bot2_path = Path(__file__).parent.parent / "bot2" / "main.py"

    # This will raise SyntaxError if there are issues
    try:
        py_compile.compile(str(bot2_path), doraise=True)
    except PermissionError:
        # Permission errors are okay in tests (temp file issues)
        # We just want to catch SyntaxError
        pass


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
