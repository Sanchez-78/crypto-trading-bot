# URGENT PATCH PLAN: Pre-Live Audit Loop (Unimplemented)

**Status**: Analysis & plan only. Do not implement.  
**Severity**: CRITICAL — unnecessary Firestore reads every 60 seconds consuming quota  
**Date**: 2026-04-25

---

## Problem Analysis

### Observed Symptom
Prod logs repeatedly show:
```
[bot2] ── pre_live_audit
[FIREBASE] loaded 500 trades
```

### Root Cause
Pre-live audit is called in **main bot loop every 60 seconds**.

**Call site**: `bot2/main.py:1744-1746`
```python
if now - _last_pre_audit >= PRE_AUDIT_INTERVAL:
    _run_pre_live_audit()
    _last_pre_audit = now
```

**Interval**: `PRE_AUDIT_INTERVAL = 60` (line 212)

**Function**: `_run_pre_live_audit()` (lines 1147-1193)
- Calls `src.services.pre_live_audit.run_audit(n_trades=20, replay=True)`
- Loads 20+ real trades from Firestore via `load_history(limit=20)` (pre_live_audit.py:683)
- Each call = **1+ Firestore read operation**

### Quota Impact
- Every 60 seconds: 1 read operation
- Per hour: 60 reads
- Per day: 1,440+ reads
- **At 50k/day limit: ~3% of quota consumed by single periodic audit loop**

---

## Minimal Fix Plan

### Option 1: Disable by Default (Recommended)

**Mechanism**: Environment flag controls audit execution

**Implementation** (do not code):

1. **bot2/main.py** (line 212):
   ```python
   # BEFORE
   PRE_AUDIT_INTERVAL  = 60
   
   # AFTER
   ENABLE_LIVE_AUDIT   = os.getenv("ENABLE_LIVE_AUDIT", "false").lower() == "true"
   PRE_AUDIT_INTERVAL  = 60
   ```

2. **bot2/main.py** (line 1744-1746):
   ```python
   # BEFORE
   if now - _last_pre_audit >= PRE_AUDIT_INTERVAL:
       _run_pre_live_audit()
       _last_pre_audit = now
   
   # AFTER
   if ENABLE_LIVE_AUDIT and now - _last_pre_audit >= PRE_AUDIT_INTERVAL:
       _run_pre_live_audit()
       _last_pre_audit = now
   ```

3. **_run_pre_live_audit()** (line 1147):
   ```python
   # Add quota check
   def _run_pre_live_audit() -> None:
       # NEW: Skip if quota degraded/exhausted
       from src.services.firebase_client import get_quota_status
       status = get_quota_status()
       reads_pct = float(status["reads_pct"].rstrip("%"))
       if reads_pct >= 65:  # EMERGENCY threshold from Phase 1 patch
           print("[bot2] pre_live_audit skipped: quota degraded")
           return
       
       # ... rest of function
   ```

### Option 2: Increase Interval (If audit needed)

If audit must run in live loop:
```python
PRE_AUDIT_INTERVAL  = 3600  # Run every hour (not 60s)
```
- Reduces reads from 1,440/day to 24/day
- Still provides periodic health check
- Less aggressive on quota

### Option 3: Run at Startup Only

```python
# Run once at startup, skip in loop
_run_pre_live_audit()  # At init time

# In loop: remove the check entirely
# DELETE:
#   if now - _last_pre_audit >= PRE_AUDIT_INTERVAL:
#       _run_pre_live_audit()
```

---

## Files Affected

| File | Function | Change | Lines |
|------|----------|--------|-------|
| bot2/main.py | (global) | Add ENABLE_LIVE_AUDIT flag | 212 |
| bot2/main.py | (main loop) | Guard audit call with flag | 1744-1746 |
| bot2/main.py | _run_pre_live_audit | Add quota check | 1147-1155 |

---

## Implementation Scope

**Option 1** (Disable by default):
- 2 file changes
- ~8 lines added
- Default: audit disabled (ENABLE_LIVE_AUDIT=false)
- User must explicitly enable with env var for audit to run

**Option 2** (Increase interval):
- 1 line change
- ~3 seconds saved on loop per iteration
- Maintains audit functionality at reduced frequency

---

## Expected Impact

### Current (Pre-patch)
- Every 60 seconds: 1 Firestore read
- 1,440 reads/day from audit loop alone
- Contributes 2-3% of 50k daily quota

### After Option 1 (Default Disabled)
- Audit disabled by default (0 reads)
- Users can opt-in with ENABLE_LIVE_AUDIT=true env var
- Saves 1,440 reads/day
- **Estimated total post-patch reads: 28-30k/day (safe)**

### After Option 2 (Hourly Instead of Minute)
- Every 3600 seconds: 1 read
- 24 reads/day from audit loop
- Maintains health checks, drastically reduced quota impact

---

## No EV/RDE/Execution Changes

- ✅ No decision logic modified
- ✅ No trading behavior changed
- ✅ No execution parameters changed
- ✅ No Firebase schema changed
- ✅ Audit is observational only (read-only, no writes to state)

---

## Recommendation

**Option 1 (Disable by default)** is lowest risk:
- Safe default (audit off)
- Clear opt-in mechanism
- Can be enabled for debugging/CI without affecting production
- Saves ~1,440 reads/day immediately

---

**Status**: Plan only. Awaiting approval for implementation.
