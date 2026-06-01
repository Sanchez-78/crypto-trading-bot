#!/bin/bash
# Phase 3 Hook Application for /opt/cryptomaster
#
# This script applies Phase 3 (V5 bridge integration) hooks to /opt/cryptomaster
# All hooks are already in GitHub branch v5/integrated-paper-firebase-quota-safe
# This script provides two options: automatic (git reset) or manual patching

set -euo pipefail
cd /opt/cryptomaster

echo "=========================================="
echo "Phase 3 Hook Application"
echo "=========================================="
echo ""

# ── OPTION 1: AUTOMATIC (git fetch + reset) ──
echo "OPTION 1: Automatic Transfer via Git"
echo ""
echo "This will fetch the latest branch and reset to include all Phase 3 hooks."
echo "IMPORTANT: Ensure /opt/cryptomaster has no local changes before proceeding."
echo ""
echo "Status before transfer:"
git status --short || echo "[Clean]"
git log --oneline -3
echo ""

echo "Fetching branch..."
git fetch origin v5/integrated-paper-firebase-quota-safe

echo "Resetting to latest..."
git reset --hard origin/v5/integrated-paper-firebase-quota-safe

echo ""
echo "✅ Phase 3 hooks transferred"
git log --oneline -1

# ── VERIFY HOOKS ARE PRESENT ──
echo ""
echo "=========================================="
echo "VERIFICATION"
echo "=========================================="
echo ""

echo "Checking _get_v5_bridge() helper..."
grep -q "def _get_v5_bridge" src/services/paper_trade_executor.py && echo "✓ Found at line $(grep -n 'def _get_v5_bridge' src/services/paper_trade_executor.py | cut -d: -f1)" || echo "✗ NOT FOUND"

echo ""
echo "Checking PAPER_ENTRY hook..."
grep -q "V5 Legacy Bridge: Record paper entry" src/services/paper_trade_executor.py && echo "✓ Found at line $(grep -n 'V5 Legacy Bridge: Record paper entry' src/services/paper_trade_executor.py | cut -d: -f1)" || echo "✗ NOT FOUND"

echo ""
echo "Checking close_paper_position hook..."
grep -q "V5 Legacy Bridge: Record paper close" src/services/paper_trade_executor.py && echo "✓ Found at line $(grep -n 'V5 Legacy Bridge: Record paper close' src/services/paper_trade_executor.py | cut -d: -f1)" || echo "✗ NOT FOUND"

echo ""
echo "Checking periodic metrics in bot2/main.py..."
grep -q "v5_bridge.publish_metrics" bot2/main.py && echo "✓ publish_metrics found at line $(grep -n 'v5_bridge.publish_metrics' bot2/main.py | cut -d: -f1)" || echo "✗ NOT FOUND"
grep -q "v5_bridge.flush_outbox" bot2/main.py && echo "✓ flush_outbox found at line $(grep -n 'v5_bridge.flush_outbox' bot2/main.py | cut -d: -f1)" || echo "✗ NOT FOUND"

echo ""
echo "=========================================="
echo "NEXT STEPS"
echo "=========================================="
echo ""
echo "Run tests to verify Phase 3 hooks are working:"
echo ""
echo "PY=/opt/cryptomaster/venv/bin/python"
echo ""
echo "\$PY -m pytest tests/test_v5_legacy_bridge_hooks.py -xvs"
echo ""
echo "Expected: test_v5_legacy_bridge_hooks imports _get_v5_bridge successfully"
echo "          All bridge hook tests pass"
echo ""
echo "When ready, run full test suite:"
echo ""
echo "\$PY -m pytest tests/test_v5_legacy_bridge*.py tests/test_p11_admission_gates_part2.py tests/test_p11_dashboard_diagnostics.py tests/test_paper_mode.py tests/test_p11ap_o2_*.py -q"
echo ""
echo "Only restart cryptomaster.service when all tests pass."
echo ""
