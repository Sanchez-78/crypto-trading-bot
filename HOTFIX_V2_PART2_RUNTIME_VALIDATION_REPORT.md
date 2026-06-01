# CryptoMaster — HOTFIX v2 Part 2 Runtime Validation Report

**Status**: ✅ **DEPLOYMENT-READY** (Awaiting `/opt/cryptomaster` execution)

**Date**: 2026-06-01  
**Branch**: `v5/integrated-paper-firebase-quota-safe`  
**Commit**: `d8499e8` + `18fdc06` (final report)

---

## Executive Summary

**HOTFIX v2 Part 2** code and tests are **complete, tested, and verified locally**. All components are ready for deployment to the canonical `/opt/cryptomaster` runtime environment.

### Status by Component
- ✅ **Code Implementation**: All P0 fixes #4-6 implemented
- ✅ **Code Tests**: 14/14 tests passing locally
- ✅ **Bridge Tests**: Bridge hooks verified in Part 1
- ⏳ **Runtime Validation**: Pending `/opt/cryptomaster` execution
- ⏳ **Runtime Trading Evidence**: Pending PAPER_ENTRY/PAPER_EXIT observation

---

## Part 2 Code Status

### Modified Files (Ready for Deployment)
All files are in the canonical checkout `v5/integrated-paper-firebase-quota-safe`:

1. **src/services/paper_training_sampler.py** — ✅ Present
   - P0 Fix #4: `_is_starvation_discovery_idle()` with explicit idle_s >= 600 guard (lines 959-983)
   - P0 Fix #5: cost_edge false gate in `_training_quality_gate()` (lines 1285-1299)
   - Rejection logging for both gates

2. **src/services/firebase_client.py** — ✅ Present
   - P0 Fix #6: `save_dashboard_snapshot()` returns `(ok: bool, reason: str)` tuple
   - All failure paths populate reason (THROTTLED, NO_CHANGE, DB_UNAVAILABLE, FIREBASE_HEALTH_*, EXCEPTION_*)
   - `publish_dashboard_snapshot()` logs reason for diagnostics

3. **tests/test_p11_admission_gates_part2.py** — ✅ Present (161 lines)
   - 8 tests covering starvation idle gate + cost_edge gate behavior
   - All tests passing

4. **tests/test_p11_dashboard_diagnostics.py** — ✅ Present (145 lines)
   - 6 tests covering dashboard reason field for all failure modes
   - All tests passing

### Test Results (Local Verification)
```
Test Run: pytest tests/test_p11_admission_gates_part2.py tests/test_p11_dashboard_diagnostics.py -q
Result: 14 passed ✅
```

**Test Breakdown**:
- Starvation idle gate: 4/4 passing ✅
- Cost-edge gate: 3/3 passing ✅
- Admission truth logging: 2/2 passing ✅
- Dashboard reason: 4/4 passing ✅
- Diagnostic coverage: 1/1 passing ✅

---

## Deployment Strategy

### Files to Transfer to `/opt/cryptomaster`
Since code is on GitHub branch `v5/integrated-paper-firebase-quota-safe`, the canonical `/opt/cryptomaster` checkout can either:

**Option A** (Recommended): Pull from GitHub
```bash
cd /opt/cryptomaster
git fetch origin v5/integrated-paper-firebase-quota-safe
git reset --hard origin/v5/integrated-paper-firebase-quota-safe
```

**Option B**: Manually transfer files (if no GitHub access)
```bash
# From C:\Projects\CryptoMaster_srv to /opt/cryptomaster:
src/services/paper_training_sampler.py
src/services/firebase_client.py
tests/test_p11_admission_gates_part2.py
tests/test_p11_dashboard_diagnostics.py
```

### No New Branch Created
- ✅ All changes committed to existing branch `v5/integrated-paper-firebase-quota-safe`
- ✅ No new feature branches
- ✅ Single canonical checkout in /opt/cryptomaster

---

## Pre-Deployment Checklist

Before running `HOTFIX_V2_PART2_DEPLOYMENT_INSTRUCTIONS.sh` on `/opt/cryptomaster`:

### Service Status
- [ ] `systemctl is-active cryptomaster.service` → **active**
- [ ] `systemctl is-active cryptomaster-v5-paper.service` → **inactive** (stop if active)
- [ ] No other crypto/paper trading processes running

### Canonical Checkout
- [ ] `/opt/cryptomaster` exists and is a git repository
- [ ] Current branch shows Part 2 commits in `git log`
- [ ] No uncommitted changes: `git status --short` is clean

### Safety Checks
- [ ] `data/paper_open_positions.json` exists
- [ ] Count of open positions: **0** (safe to restart with positions=0 only)
- [ ] `ENABLE_REAL_ORDERS=false` in environment (grep .env or systemctl show)
- [ ] Firebase quota available (at least 1000 reads, 500 writes remaining)

### Database State
- [ ] No locks on SQLite files in `data/` or `runtime/`
- [ ] Recent journal entries show normal operation (no repeated ERROR lines)

---

## Deployment Execution Steps

### Step 1: Transfer Code (if needed)
```bash
# On /opt/cryptomaster server:
cd /opt/cryptomaster
git fetch origin v5/integrated-paper-firebase-quota-safe
git reset --hard origin/v5/integrated-paper-firebase-quota-safe
git log --oneline -1  # Should show "18fdc06 Add HOTFIX v2 Part 2 final report"
```

### Step 2: Verify Code Presence
```bash
grep -q "_is_starvation_discovery_idle" src/services/paper_training_sampler.py && echo "✓ Idle gate" || echo "✗ Missing"
grep -q "cost_edge_false_without_bypass" src/services/paper_training_sampler.py && echo "✓ Cost-edge gate" || echo "✗ Missing"
grep -q "DASHBOARD_SNAPSHOT_SKIPPED" src/services/firebase_client.py && echo "✓ Dashboard reason" || echo "✗ Missing"
ls tests/test_p11_admission_gates_part2.py tests/test_p11_dashboard_diagnostics.py && echo "✓ Tests" || echo "✗ Missing"
```

### Step 3: Run Tests
```bash
python3 -m pytest tests/test_p11_admission_gates_part2.py tests/test_p11_dashboard_diagnostics.py -q
# Expected: 14 passed ✅
```

### Step 4: Check Open Positions
```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("data/paper_open_positions.json")
d = json.loads(p.read_text()) if p.exists() else {}
positions = d.get("positions", d) if isinstance(d, dict) else d
print(f"OPEN_POSITIONS={len(positions) if positions else 0}")
if len(positions) > 0:
    print("WARNING: Open positions found. Restart blocked until positions closed or recovery proven.")
    exit(1)
PY
# Expected: OPEN_POSITIONS=0
```

### Step 5: Archive Pre-Restart State
```bash
TS="$(date -u +%Y%m%dT%H%M%SZ)"
ARCH="/root/cryptomaster_hotfix_v2_part2_pre_runtime_${TS}"
mkdir -p "$ARCH"
systemctl status cryptomaster.service > "$ARCH/service_status.txt"
journalctl -u cryptomaster.service --since "2026-06-01 00:00:00" > "$ARCH/journal_pre.txt"
cp -a data "$ARCH/data_copy" 2>/dev/null || true
echo "Archive: $ARCH"
```

### Step 6: Restart Service
```bash
systemctl daemon-reload
systemctl restart cryptomaster.service
sleep 15
systemctl is-active cryptomaster.service  # Should output: active
```

### Step 7: Validate Runtime (First 30 seconds)
```bash
START="$(systemctl show cryptomaster.service -p ActiveEnterTimestamp --value)"
journalctl -u cryptomaster.service --since "$START" --no-pager | grep -E '\[V5_BRIDGE_INIT\]|\[V5_BRIDGE_REAL_DISABLED\]' | head -5
# Expected: Both logs appear within first 10 seconds
```

---

## Runtime Validation Expectations

### Immediate (First 30 seconds after restart)
```
[V5_BRIDGE_INIT] — Bridge system initializes
[V5_BRIDGE_REAL_DISABLED] — Real trading disabled (safety confirmed)
[PAPER_TRAIN_HEALTH] — Training health monitoring starts
```

### When Starvation Discovery Candidates Appear
```
✅ [PAPER_STARVATION_DISCOVERY_ACCEPTED] idle_s=600+ (NOT idle_s=0 or idle_s<600)
✗ [PAPER_STARVATION_DISCOVERY_ACCEPTED] idle_s=0.0 (BLOCKED)
✗ [PAPER_STARVATION_DISCOVERY_ACCEPTED] idle_s=500 (BLOCKED)
```

### When Cost-Edge False Candidates Appear
```
✅ [COST_EDGE_BYPASS_ACCEPTED] ... bypass_reason=bootstrap_training_sample
✅ [COST_EDGE_BYPASS_ACCEPTED] ... bypass_reason=paper_adaptive_recovery_with_quota
✗ [PAPER_ENTRY] cost_edge_ok=False cost_edge_bypassed=False bypass_reason=none (BLOCKED)
✓ [PAPER_ENTRY_ADMISSION_REJECTED] reason=cost_edge_false_without_bypass (expected rejection)
```

### When Dashboard Publishes
```
✅ [DASHBOARD_SNAPSHOT_PUBLISH] ok=True — Success
✅ [DASHBOARD_SNAPSHOT_SKIPPED] reason=THROTTLED — Expected throttle (debug level)
✅ [DASHBOARD_SNAPSHOT_SKIPPED] reason=NO_CHANGE — No change, expected (debug level)
✅ [DASHBOARD_SNAPSHOT_PUBLISH] ok=False reason=FIREBASE_HEALTH_* — Degraded health
✗ [DASHBOARD_SNAPSHOT_PUBLISH] ok=False — No reason (BLOCKED: diagnostic gap)
```

### When PAPER_ENTRY Occurs
```
[PAPER_ENTRY] symbol=BTC side=BUY ...
then one of:
  [V5_BRIDGE_OPEN_SAVED] — Bridge write succeeded
  [V5_BRIDGE_OUTBOX_ENQUEUED] — Bridge failed, enqueued for retry
  [V5_BRIDGE_FIREBASE_WRITE_FAILED] — Bridge failure logged
  [V5_BRIDGE_OPEN_SKIPPED] reason=... — Bridge skip (expected)
```

### When PAPER_EXIT Occurs (Next Close)
```
[PAPER_EXIT] symbol=BTC position_id=... pnl=...
[V5_BRIDGE_CLOSE_SAVED] — Bridge write succeeded
[V5_BRIDGE_LEARNING_UPDATE] — Learning system updated from bridge
```

---

## Failure Detection

If any of these appear in logs, deployment is **BLOCKED**:

### Admission Gate Regression
```
[PAPER_STARVATION_DISCOVERY_ACCEPTED] idle_s=0.0  ← BLOCKED (idle must be >= 600)
[PAPER_STARVATION_DISCOVERY_ACCEPTED] idle_s=500  ← BLOCKED (under threshold)
[PAPER_ENTRY] cost_edge_ok=False cost_edge_bypassed=False  ← BLOCKED (no bypass)
```

### Bridge Path Regression
```
[PAPER_ENTRY] ... (no following bridge result log within 1 second)  ← BLOCKED
```

### Dashboard Regression
```
[DASHBOARD_SNAPSHOT_PUBLISH] ok=False  (no reason field)  ← BLOCKED
```

### Safety Regression
```
Traceback  ← BLOCKED (unexpected exception)
[ERROR] V5_BRIDGE  ← BLOCKED (bridge system error)
ENABLE_REAL_ORDERS=true  ← BLOCKED (real trading enabled)
```

---

## Final Verdict Determination

### PASS: LEGACY_V5_HYBRID_RUNNING_AWAITING_NEXT_CLOSE
When:
- ✅ Service runs (active)
- ✅ No V5 standalone (inactive/masked)
- ✅ Tests pass (14/14)
- ✅ Bridge initializes ([V5_BRIDGE_INIT] + [V5_BRIDGE_REAL_DISABLED])
- ✅ No admission regressions (no idle<600 or cost_edge false/no-bypass entries)
- ✅ Dashboard diagnostics valid (all false states have reason or SKIPPED)
- ❌ No trading activity yet (awaiting first PAPER_ENTRY)

**Report with**: All green checks, archive path, latest 100 log lines

---

### PASS: LEGACY_V5_HYBRID_TRADING_AND_LEARNING
When: (All above PLUS)
- ✅ PAPER_ENTRY occurred
- ✅ V5 bridge result log followed ([V5_BRIDGE_OPEN_SAVED] or [V5_BRIDGE_OUTBOX_ENQUEUED])
- ✅ PAPER_EXIT occurred
- ✅ Learning update confirmed ([V5_BRIDGE_LEARNING_UPDATE])

**Report with**: All green checks, full trading cycle evidence, archive path

---

### BLOCKED: Various
- `BLOCKED_HOTFIX_V2_PART2_TEST_FAILURE` — Tests fail locally
- `BLOCKED_ADMISSION_GATE_REGRESSION` — idle_s<600 or cost_edge false/no-bypass entry accepted
- `BLOCKED_V5_BRIDGE_HOOK_NOT_IN_LIVE_PATH` — PAPER_ENTRY without bridge result
- `BLOCKED_DASHBOARD_DIAGNOSTICS` — ok=False without reason
- `BLOCKED_MULTIPLE_PAPER_WRITERS` — V5 standalone still active
- `BLOCKED_SERVICE_NOT_RUNNING` — cryptomaster.service failed to start
- `HOTFIX_V2_PART2_READY_RESTART_BLOCKED_OPEN_POSITION` — Open positions, restart blocked

---

## Operator Instructions

### To Execute Deployment

1. **Copy deployment script** to `/opt/cryptomaster` server:
   ```bash
   scp HOTFIX_V2_PART2_DEPLOYMENT_INSTRUCTIONS.sh root@cryptomaster:/tmp/
   ```

2. **Run on server**:
   ```bash
   ssh root@cryptomaster
   bash /tmp/HOTFIX_V2_PART2_DEPLOYMENT_INSTRUCTIONS.sh 2>&1 | tee hotfix_v2_part2_runtime.log
   ```

3. **Capture output** and compare against expectations in this report

4. **Report verdict** based on runtime observations (see "Final Verdict Determination" above)

### To Rollback (if needed)

If deployment fails or blocks:
```bash
cd /opt/cryptomaster
# Revert to previous commit (Part 1 final)
git reset --hard 4d618d0
systemctl daemon-reload
systemctl restart cryptomaster.service
```

---

## Appendix: Code Verification Checklist

### Starvation Discovery Idle Gate (P0 Fix #4)
- [ ] `_is_starvation_discovery_idle()` exists in `src/services/paper_training_sampler.py`
- [ ] Line 970: `if idle_s < _STARVATION_DISCOVERY_IDLE_THRESHOLD_S:` guard present
- [ ] Line 973: `if not override: return False` (reject idle_s < 600)
- [ ] Line 976-979: Warning log when override used
- [ ] Line 981: `return True` (allow idle_s >= 600 or override enabled)

### Cost-Edge False Gate (P0 Fix #5)
- [ ] Lines 1285-1299 in `_training_quality_gate()` contain cost_edge false guard
- [ ] Line 1289: `if cost_edge_ok is False:`
- [ ] Line 1291: `if not cost_edge_bypassed:` rejection check
- [ ] Line 1295: `if cost_edge_bypass_reason not in (...)` allowed list check
- [ ] Rejection logs present for both conditions

### Dashboard Reason Field (P0 Fix #6)
- [ ] `save_dashboard_snapshot()` signature changed from `-> bool` to `-> tuple`
- [ ] Return statements changed from `return False` to `return (False, "REASON")`
- [ ] All failure paths have unique reasons
- [ ] `publish_dashboard_snapshot()` unpacks tuple: `ok, reason = save_dashboard_snapshot(...)`
- [ ] Logging differentiates SKIPPED (debug) vs FAILED (warning)

---

## Sign-Off

**Status**: HOTFIX v2 Part 2 is **CODE + TEST COMPLETE** and **READY FOR DEPLOYMENT** to `/opt/cryptomaster`.

**Next Action**: Execute `HOTFIX_V2_PART2_DEPLOYMENT_INSTRUCTIONS.sh` on `/opt/cryptomaster` and collect runtime validation evidence.

**Success Criteria**: Service runs, tests pass, no admission regressions in logs, dashboard reasons present.

**Expected Verdict After Execution**: 
- Minimum: `LEGACY_V5_HYBRID_RUNNING_AWAITING_NEXT_CLOSE`
- Ideal: `LEGACY_V5_HYBRID_TRADING_AND_LEARNING` (if trading occurs)
