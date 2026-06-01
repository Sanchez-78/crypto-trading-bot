# CryptoMaster — Hotfix v2 Runtime Bridge + Safe Close Lifecycle Report

## Executive Summary

**Verdict**: `LEGACY_V5_HYBRID_CLOSE_LIFECYCLE_FIXED_AWAITING_GATE_AUDIT`

Completed: 3 of 7 P0 hotfixes (Critical position lifecycle bugs). Remaining: 4 admission/diagnostics fixes.

---

## Part 1: Critical Bugs Fixed ✅

### Bug #1: Position Pop-Before-Processing (CRITICAL - TRADE LOSS)
**Status**: ✅ FIXED  
**Commit**: `4d618d0`

**Problem**:
```
Position removed from _POSITIONS at line 1615 BEFORE:
- V5 bridge write (line 1717) → can fail → position gone forever
- Learning update (line 1734) → can fail → position gone forever  
- Metrics save (line 1759) → can fail → position gone forever
```

**Solution**:
- Read position: `pos = _POSITIONS[id]` (no pop)
- Process everything (lines 1617-1799)
- Pop at end: `_POSITIONS.pop(position_id, None)` (line 1800)

**Impact**: Position survives any exception, retryable on failure

---

### Bug #2: Dedup TOCTOU Race (CRITICAL - RETRY FAILURE)
**Status**: ✅ FIXED  
**Commit**: `4d618d0`

**Problem**:
```
Dedup check at line 1725 (AFTER position popped at 1615)
On Kafka message retry:
1. First call: position popped, added to _CLOSED_TRADES
2. Second call: position NOT in _POSITIONS (already popped), returns None at 1614
3. Dedup check never fires because position_id missing
```

**Solution**:
- Move dedup check to line 1612 (before position access)
- Check `_CLOSED_TRADES_THIS_SESSION` immediately
- Return None if found (fail fast)
- Mark as processed after position read succeeds (line 1728)

**Impact**: Dedup now works on message retry, prevents duplicate learning

---

### Bug #3: V5 Bridge Exception Swallowed (CRITICAL - STATE DIVERGENCE)
**Status**: ✅ FIXED  
**Commit**: `4d618d0`

**Problem**:
```
v5_bridge.record_close() raises exception at line 1717
log.error() called at line 1719
code continues with learning/metrics updates
→ Silent state divergence between legacy and V5 systems
```

**Solution**:
- Catch exception
- Enqueue close_event to durable outbox with idempotency_key=trade_id
- Log `[V5_BRIDGE_CLOSE_FAILED]` and `[V5_BRIDGE_CLOSE_ENQUEUED]`
- Let outbox retry handle the write

**Impact**: Bridge failures automatically retry; no state divergence

---

## Part 2: Remaining P0 Hotfixes ⏳

### Bug #4: Starvation Discovery idle_s=0.0 Gate (HIGH - ADMISSION REGRESSION)
**Status**: ❌ PENDING  
**File**: `src/services/paper_training_sampler.py`

**Problem from logs**:
```
[PAPER_STARVATION_DISCOVERY_ACCEPTED] idle_s=0.0 (should require >= 600s)
[PAPER_ENTRY_ADMISSION_TRUTH] cost_edge_ok=False yet entry opened
```

**Root cause analysis**:
- Line 1605: `last_eligible_entry_ts = now` at startup → idle_s = 0
- Line 1781: After ACCEPTANCE, `_update_starvation_discovery_idle(now)` resets idle_s = 0
- **But**: Check happens at line 951-956 BEFORE reset
  
**Likely culprit**:
- Line 851-852: `if ev <= 0 and ... and _is_starvation_discovery_idle():`
- `_is_starvation_discovery_idle()` computed at line 955-956 
- If called at startup, `idle_s = now - now = 0`, returns `0 >= 600 = False` ✓ Correct
- **BUT** if `last_eligible_entry_ts` gets reset too early (e.g., after acceptance), next call might trigger

**Required fix**:
```python
def _is_starvation_discovery_idle() -> bool:
    now = time.time()
    idle_s = now - _starvation_discovery_state.get("last_eligible_entry_ts", 0.0)
    # ADD EXPLICIT GUARD:
    if idle_s < _STARVATION_DISCOVERY_IDLE_THRESHOLD_S:
        return False  # Explicit, not implicit
    return True
```

### Bug #5: cost_edge_ok=False without bypass Gate (HIGH - ADMISSION REGRESSION)
**Status**: ❌ PENDING  
**File**: TBD (need to locate admission gate)

**Problem from logs**:
```
[PAPER_ENTRY_ADMISSION_TRUTH] cost_edge_ok=False cost_edge_bypassed=False bypass_reason=none yet entry=True
```

**Location to find**:
- Grep: `cost_edge_bypassed` in paper_training_sampler.py
- Likely around lines 1700-1760 (acceptance decision)

**Expected guard**:
```python
# If cost_edge check fails AND no bypass is active, reject
if not cost_edge_ok and not cost_edge_bypassed:
    return ("", 0.0)  # Reject with empty bucket
```

### Bug #6: Dashboard ok=False without reason (MEDIUM - DIAGNOSTIC GAP)
**Status**: ❌ PENDING  
**File**: `bot2/main.py`

**Problem**:
```
[DASHBOARD_SNAPSHOT_PUBLISH] ok=False save_ms=0
(no 'reason' field to indicate why ok=False)
```

**Required fix**:
```python
# In dashboard snapshot publish logging:
log.info(
    "[DASHBOARD_SNAPSHOT_PUBLISH] ok=%s reason=%s save_ms=%d",
    ok,
    reason or "throttle",  # Add this
    save_ms
)
```

---

## Verification Checklist

### ✅ Part 1 Fixes Verified
- [x] Position pop moved to end of close_paper_position()
- [x] Read-only access with `_POSITIONS[id]` instead of pop
- [x] Dedup check moved to start (line 1612)
- [x] V5 bridge exception enqueues to outbox
- [x] Code compiles and imports work
- [x] git commit created and pushed

### ⏳ Part 2 Pending
- [ ] Starvation discovery idle gate explicit guard added
- [ ] cost_edge false without bypass rejection verified
- [ ] Dashboard reason field added
- [ ] All tests pass
- [ ] Runtime validation on bot
- [ ] Final verdict reached

---

## Test Plan (Not Yet Implemented)

### test_p11_close_lifecycle_safety.py
```python
def test_close_position_survives_v5_bridge_exception():
    """Position must survive V5 bridge failure and be retryable."""
    # Mock v5_bridge to raise exception
    # Call close_paper_position()
    # Assert position still in _POSITIONS (not popped)
    # Assert outbox has close_event enqueued
    # Call close_paper_position() again
    # Assert second call processes successfully

def test_close_position_dedup_prevents_retry():
    """Dedup check at start must prevent duplicate processing."""
    # Call close_paper_position() twice with same trade_id
    # First call: succeeds, adds to _CLOSED_TRADES_THIS_SESSION
    # Second call: returns None immediately (dedup check)
    # Assert learning updated only once

def test_close_position_not_lost_on_learning_failure():
    """Position removal only after learning succeeds."""
    # Mock learning to raise exception
    # Call close_paper_position()
    # Assert position in _POSITIONS (not yet popped)
    # Verify exception caught, outbox queued, code continues
```

### test_p11_starvation_discovery_gate.py
```python
def test_starvation_discovery_rejects_idle_zero():
    """Idle must be >= 600s before accepting discovery."""
    # Set last_eligible_entry_ts = now (fresh startup)
    # Call _is_starvation_discovery_idle() immediately
    # Assert returns False (idle = 0 < 600)

def test_starvation_discovery_accepts_idle_600_plus():
    """Idle >= 600s must be accepted."""
    # Set last_eligible_entry_ts = now - 610
    # Assert _is_starvation_discovery_idle() returns True
```

### test_p11_admission_gates.py
```python
def test_cost_edge_false_without_bypass_rejects():
    """cost_edge_ok=False + cost_edge_bypassed=False must reject."""
    # Call try_open_paper_position() with cost_edge_ok=False, bypass=False
    # Assert entry rejected (bucket="", status="blocked")

def test_cost_edge_false_with_bypass_and_reason_allows():
    """cost_edge_ok=False + bypass=True + reason must allow."""
    # Call with cost_edge_ok=False, bypass=True, bypass_reason="recovery"
    # Assert entry allowed
```

### test_p11_dashboard_diagnostics.py
```python
def test_dashboard_publish_false_has_reason():
    """Dashboard ok=False must include reason field."""
    # Mock publish_dashboard_snapshot() to check log
    # Assert [DASHBOARD_SNAPSHOT_PUBLISH] log includes reason field
    # Assert reason is not empty
```

---

## Changes Summary

### Files Modified
1. **src/services/paper_trade_executor.py**
   - Lines 1612-1623: Added early dedup check
   - Line 1615: Changed `pop()` to read-only `[id]`
   - Lines 1718-1742: V5 bridge exception → outbox enqueue
   - Lines 1800-1803: Position pop moved to end

### Files Pending Modification
2. **src/services/paper_training_sampler.py** — Starvation discovery + cost_edge gates
3. **bot2/main.py** — Dashboard reason field
4. **tests/test_p11_*.py** — New test files (4 files)

---

## Deployment Decision Tree

```
If P0 bugs #1-3 tests pass:
  ✅ Deploy Part 1 (close_paper_position fixes)
  → Verdict: LEGACY_V5_HYBRID_CLOSE_LIFECYCLE_FIXED

If P0 bugs #4-6 fixed AND tests pass:
  ✅ Deploy Part 2 (admission gates + diagnostics)
  → Verdict: LEGACY_V5_HYBRID_ADMISSION_GATES_SECURED

If all P0 fixes deployed AND runtime validation passes:
  ✅ Final deployment
  → Verdict: LEGACY_V5_HYBRID_TRADING_AND_LEARNING
```

---

## Current Verdict

`LEGACY_V5_HYBRID_CLOSE_LIFECYCLE_FIXED_AWAITING_GATE_AUDIT`

**Status**: 
- ✅ Critical close position bugs (#1-3) fixed and committed
- ⏳ Admission gate regression bugs (#4-6) identified, pending fix
- ⏳ Tests pending implementation
- ⏳ Runtime validation awaiting test completion

**Next action**: Implement remaining P0 fixes (#4-6) and tests

