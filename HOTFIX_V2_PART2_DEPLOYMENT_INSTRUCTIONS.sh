#!/bin/bash
# CryptoMaster HOTFIX v2 Part 2 — Runtime Deployment & Validation for /opt/cryptomaster
# Branch: v5/integrated-paper-firebase-quota-safe
# Commit: d8499e8 (+ 18fdc06 final report)
#
# Usage: bash HOTFIX_V2_PART2_DEPLOYMENT_INSTRUCTIONS.sh

set -euo pipefail
cd /opt/cryptomaster

echo "=========================================="
echo "HOTFIX v2 Part 2: Runtime Deployment"
echo "=========================================="
echo ""

# ── 1. BASELINE ──────────────────────────────────────────────────────
echo "=== 1. BASELINE CHECK ==="
echo ""

echo "Services:"
systemctl show cryptomaster.service -p ActiveState -p UnitFileState -p MainPID -p ActiveEnterTimestamp --no-pager 2>/dev/null | head -5 || true
echo ""

echo "V5 standalone (should be inactive):"
systemctl show cryptomaster-v5-paper.service -p ActiveState 2>/dev/null || echo "[Not found - expected]"
echo ""

echo "Canonical checkout:"
git branch --show-current
git rev-parse HEAD
git log --oneline -3
echo ""

echo "Status:"
git status --short | head -5 || echo "[Clean]"
echo ""

# ── 2. VERIFY PART 2 CODE ────────────────────────────────────────────
echo "=== 2. VERIFY PART 2 CODE IN PLACE ==="
echo ""

echo "Checking for P0 fix markers..."
grep -q "_is_starvation_discovery_idle" src/services/paper_training_sampler.py && echo "✓ Starvation idle gate present" || echo "✗ Missing idle gate"
grep -q "cost_edge_false_without_bypass" src/services/paper_training_sampler.py && echo "✓ Cost-edge gate present" || echo "✗ Missing cost_edge gate"
grep -q "DASHBOARD_SNAPSHOT_SKIPPED\|reason=THROTTLED" src/services/firebase_client.py && echo "✓ Dashboard reason field present" || echo "✗ Missing dashboard reason"

echo ""
echo "Test files:"
ls -lh tests/test_p11_admission_gates_part2.py tests/test_p11_dashboard_diagnostics.py 2>/dev/null | awk '{print $9, $5}' || echo "✗ Test files missing"
echo ""

# ── 3. RUN TESTS ─────────────────────────────────────────────────────
echo "=== 3. RUN PART 2 TESTS ==="
echo ""

echo "Running admission gates + dashboard tests..."
python3 -m pytest \
  tests/test_p11_admission_gates_part2.py \
  tests/test_p11_dashboard_diagnostics.py \
  -q --tb=short 2>&1 | tail -20 || {
  echo "BLOCKED_HOTFIX_V2_PART2_TEST_FAILURE"
  exit 1
}
echo ""

# ── 4. CHECK OPEN POSITIONS ──────────────────────────────────────────
echo "=== 4. OPEN POSITIONS CHECK ==="
echo ""

python3 - <<'PY'
import json, pathlib
p = pathlib.Path("data/paper_open_positions.json")
if not p.exists():
    print("OPEN_POSITIONS=UNKNOWN_FILE_MISSING")
    exit(1)
else:
    try:
        d = json.loads(p.read_text())
        positions = d.get("positions", d) if isinstance(d, dict) else d
        count = len(positions) if isinstance(positions, (list, dict)) else 0
        print(f"OPEN_POSITIONS={count}")
        if count > 0:
            print(f"Position details (first 5):")
            items = list(positions.items()) if isinstance(positions, dict) else positions
            for trade in items[:5]:
                print(f"  {json.dumps(trade, default=str)[:120]}")
    except Exception as e:
        print(f"OPEN_POSITIONS=ERROR_{type(e).__name__}")
        exit(1)
PY

OPEN_POS=$?
if [ $OPEN_POS -ne 0 ]; then
    echo "Cannot determine open positions. Blocking restart."
    exit 1
fi
echo ""

# ── 5. ARCHIVE BEFORE RESTART ────────────────────────────────────────
echo "=== 5. PRE-RESTART ARCHIVE ==="
echo ""

TS="$(date -u +%Y%m%dT%H%M%SZ)"
ARCH="/root/cryptomaster_hotfix_v2_part2_pre_runtime_${TS}"
mkdir -p "$ARCH"

echo "Archiving to: $ARCH"
systemctl status cryptomaster.service --no-pager -l 2>/dev/null > "$ARCH/service_status.txt" || true
journalctl -u cryptomaster.service --since "2026-06-01 00:00:00 UTC" --no-pager > "$ARCH/journal_pre.txt" || true
git rev-parse HEAD > "$ARCH/head.txt"
git status --short > "$ARCH/git_status.txt"
cp -a data "$ARCH/data_copy" 2>/dev/null || true
echo "Archive saved: $ARCH"
echo ""

# ── 6. RESTART SERVICE ───────────────────────────────────────────────
echo "=== 6. RESTART cryptomaster.service ==="
echo ""

echo "Reloading systemd..."
systemctl daemon-reload

echo "Restarting cryptomaster.service..."
systemctl restart cryptomaster.service

echo "Waiting 15 seconds for startup..."
sleep 15

echo "Service status:"
systemctl is-active cryptomaster.service || echo "SERVICE_NOT_RUNNING"
echo ""

# ── 7. RUNTIME VALIDATION ────────────────────────────────────────────
echo "=== 7. RUNTIME VALIDATION ==="
echo ""

START="$(systemctl show cryptomaster.service -p ActiveEnterTimestamp --value)"
echo "Collecting logs since restart: $START"
echo ""

echo "=== CRITICAL MARKERS ==="
journalctl -u cryptomaster.service --since "$START" --no-pager 2>/dev/null | grep -E '\[V5_BRIDGE_INIT\]|\[V5_BRIDGE_REAL_DISABLED\]|REAL.*False|REAL.*false' | head -10 || echo "[Waiting for startup logs]"
echo ""

echo "=== ADMISSIONS (starvation + cost_edge) ==="
journalctl -u cryptomaster.service --since "$START" --no-pager 2>/dev/null | grep -E 'PAPER_STARVATION_DISCOVERY|PAPER_ENTRY_ADMISSION|cost_edge' | head -20 || echo "[No admissions yet]"
echo ""

echo "=== DASHBOARD ==="
journalctl -u cryptomaster.service --since "$START" --no-pager 2>/dev/null | grep -E 'DASHBOARD_SNAPSHOT|DASHBOARD_SNAPSHOT_SKIPPED' | head -20 || echo "[No dashboard events yet]"
echo ""

echo "=== V5 BRIDGE ==="
journalctl -u cryptomaster.service --since "$START" --no-pager 2>/dev/null | grep -E '\[V5_BRIDGE_OPEN|V5_BRIDGE_CLOSE|V5_BRIDGE_LEARNING\]' | head -20 || echo "[No bridge events yet]"
echo ""

echo "=== ERRORS / TRACEBACK ==="
journalctl -u cryptomaster.service --since "$START" --no-pager 2>/dev/null | grep -E 'Traceback|ERROR|error' | head -20 || echo "[No errors]"
echo ""

# ── 8. SUMMARY ───────────────────────────────────────────────────────
echo "=== 8. DEPLOYMENT SUMMARY ==="
echo ""

VERDICT="LEGACY_V5_HYBRID_RUNNING_AWAITING_NEXT_CLOSE"
SERVICE_STATUS="$(systemctl is-active cryptomaster.service || echo 'FAILED')"
V5_STATUS="$(systemctl is-active cryptomaster-v5-paper.service 2>/dev/null || echo 'inactive')"

echo "Service state: $SERVICE_STATUS"
echo "V5 standalone: $V5_STATUS"
echo "Archive: $ARCH"
echo ""

if [ "$SERVICE_STATUS" = "active" ]; then
    echo "✓ cryptomaster.service running"
else
    echo "✗ cryptomaster.service failed"
    VERDICT="BLOCKED_SERVICE_NOT_RUNNING"
fi

if [ "$V5_STATUS" != "active" ]; then
    echo "✓ V5 standalone not active (expected)"
else
    echo "✗ V5 standalone is active (BLOCKED)"
    VERDICT="BLOCKED_MULTIPLE_PAPER_WRITERS"
fi

echo ""
echo "========================================"
echo "VERDICT: $VERDICT"
echo "========================================"
echo ""
echo "Next: Monitor logs for trading activity and collect final validation evidence."
echo ""
