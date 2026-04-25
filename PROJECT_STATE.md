# CryptoMaster Project State

Last updated: 2026-04-25

## Active Phase

Safety hardening before economics/integration rollout.

**Current objective:** Make production safer and easier to verify without changing EV/RDE/execution behavior.

## Completed Commits

### Commit 1 (b2bcca8): Runtime Version Marker
- **Files**: `src/services/version_info.py` (NEW), `bot2/main.py`, `src/services/pre_live_audit.py`
- **Purpose**: Startup/audit runtime marker with git commit, branch, host, Python version, timestamp
- **Status**: ✅ PUSHED to remote

### Commit 2 (f798f2e): Secret-Safe Logging
- **Files**: `src/services/safe_logging.py` (NEW), `src/services/firebase_client.py`, `src/services/market_stream.py`
- **Purpose**: Sanitize exception messages to prevent credential leakage; preserve trading metrics
- **Validation**: ✅ All 14 tests passing (Bearer case preservation, delimiter preservation, min length 8)
- **Status**: ✅ PUSHED to remote

### Commit 3 (2688087): Project State Memory
- **Files**: `PROJECT_STATE.md` (NEW)
- **Purpose**: Durable memory for workflow continuity across context compaction
- **Status**: ✅ PUSHED to remote

## Current Work

### Design Complete — Awaiting Implementation Approval

**Patch 3: Firebase Retry Queue Heartbeat** (`PATCH_3_FIREBASE_RETRY_HEARTBEAT_PLAN.md` v2)
- Status: REVISED per 10 user corrections; design complete, not implemented
- Architecture: Three-tier (enqueue → drain → write_direct), no re-entry risk
- Scope: ~220 lines (8 module vars + refactored save_batch + 6 new functions)
- Requirements: Thread-safety patch plan approved before implementation

**Emergency Analysis: Firebase Read Quota Containment** (`EMERGENCY_READ_QUOTA_CONTAINMENT_PLAN.md`)
- Status: COMPLETE; emergency plan designed, not implemented
- Root cause: Read quota (50k/day) exceeded before 11:00 UTC; previous emergency documented at 6000 reads/36min
- Phase 1 (immediate): 3 file changes (lower _can_read threshold 80%→65%, increase TTLs 3600→7200s, throttle auto_cleaner)
- Phase 2 (post-reset): Unified safe_get_with_quota_bypass() wrapper
- Expected outcome: Reduce daily reads from 50k+ to 30-35k

## Forbidden Now

Do not:
- Implement Patch 3 without explicit approval
- Implement emergency containment without explicit approval
- Change EV/RDE/execution behavior, sizing, leverage, TP/SL, score, gates
- Change Firebase schema or Android dashboard fields
- Stage unrelated files or commit `.claude/settings.local.json`
- Do full rewrites

## Next Steps

**Awaiting User Direction**

1. **Implement Patch 3 (Firebase Retry Queue Heartbeat)**
   - Requires: User approval
   - Effort: ~30-45 minutes
   - Scope: 220 lines (new + refactor)
   - Estimated impact: Prevent unbounded retry queue growth, detect stalls

2. **Implement Emergency Containment (Phase 1)**
   - Requires: User approval
   - Effort: ~20-30 minutes
   - Scope: 3 file changes, ~30 lines
   - Estimated impact: Reduce daily reads 50k+ → 30-35k

3. **Parallel: Investigate Read Storm Root Cause**
   - Check if Android app polling excessively
   - Check if external cron jobs hitting Firestore
   - Check PERF_MODE status
   - Check recent Firebase indexing changes

## Workflow Rules

1. Read `.maestro.md` and `PROJECT_STATE.md` before new work
2. Update `PROJECT_STATE.md` after every approved commit
3. Show diff before staging/committing
4. Local commit only after diff review
5. Push only after explicit approval
6. One commit per hardening area
7. Keep changes incremental and reversible

## Roadmap (Deferred)

**File**: `logs_extracted_tmp/CryptoMaster_Combined_Analysis_Integration_2026-04-25.md`

**Post-hardening sequence** (do not implement yet):
1. Canonical metrics enforcement
2. Audit enhancements/regression testing
3. Bootstrap/cell quality governance
4. Exit monetization shadow/live rollout
5. Probability calibration and feature pruning last
