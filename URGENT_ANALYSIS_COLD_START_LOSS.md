# URGENT ANALYSIS: Cold Start Trade Loss After Restart

**Status**: Analysis only. No implementation.  
**Severity**: CRITICAL — Bot loses trades/learning on startup  
**Date**: 2026-04-25

---

## Problem Summary

After restart, bot logs show:
- Metrics: empty → 0 trades (at startup)
- Learning Monitor: empty → 0 pairs (at startup)  
- [FIREBASE] loaded 100 trades (from load_history)
- Bootstrap: 7631 trades available (later)

**Contradiction**: Why does load_history return 100 when bootstrap shows 7631?

---

## Root Cause Analysis

### Root Cause #1: Quota Reset Timing + Phase 1 Patch (HIGH CONFIDENCE)

**Mechanism**:

1. **Yesterday's quota exhaustion persists**:
   - Day 1: Quota exceeded (50k reads used)
   - `_QUOTA_READS = 50000` stored in module state
   - Day 2: Bot restarts at ~1:00 AM UTC (before 07:00 UTC reset)
   - _quota_reads STILL = 50000 from persistent state

2. **Phase 1 patch lowered threshold**:
   - Changed `_can_read()` check from 80% (40k) to 65% (32.5k)
   - At startup with `_QUOTA_READS=50000`, check fails immediately
   - `50000 >= 50000 * 0.65` (32.5k) → TRUE → read blocked

3. **load_history() returns stale cache on quota block**:
   ```python
   # firebase_client.py:363-366
   allowed, current, limit_quota = _can_read(estimated_reads)
   if not allowed:
       logging.debug(f"Skipping history fetch: quota limit reached")
       return list(_HISTORY_CACHE["data"][:limit])  # ← returns stale cache
   ```

4. **Stale cache is EMPTY at startup**:
   ```python
   # firebase_client.py:44
   _HISTORY_CACHE = {"data": [], "ts": 0, "limit": 0}  # ← empty on init
   ```

5. **Result**: `load_history()` returns empty list → bootstrap sees 0 trades

6. **Quota reset happens later** (~07:00 UTC):
   - `_reset_quota_if_new_day()` eventually resets counters to 0
   - load_history() can then read normally
   - But by then, bootstrap has already processed empty state

**Evidence**:
- File: `firebase_client.py` line 363-366 (quota guard)
- File: `firebase_client.py` line 44 (cache initialization)
- File: `firebase_client.py` line 70-97 (_reset_quota_if_new_day)
- File: `bot2/main.py` line 1483 (load_history at startup)
- File: `bot2/main.py` line 212-215 (Phase 1 lowered threshold to 65%)

---

### Root Cause #2: Startup Order Issue (MEDIUM CONFIDENCE)

**Timing sequence** (bot2/main.py):

1. **Line 1458-1477**: Hydrate Metrics & Learning Monitor from Redis
   - Both report 0 trades, 0 pairs (Redis empty on fresh start)
2. **Line 1483**: `load_history()` called
   - Returns empty if quota blocked (see Root Cause #1)
3. **Line 1496**: `initialize_canonical_state(_history)` 
   - Initializes from empty _history
4. **Line 1500**: `bootstrap_from_history(_history)`
   - Bootstraps from empty _history
5. **Line 1512**: `log_bootstrap_status()`
   - Reads from learning_monitor/metrics modules (still empty from Redis)

**But later logs show 7631 trades** — suggests:
- A different bootstrap function loads from Firestore directly
- Or cache is refreshed after quota reset
- Or learning modules update from their own Firebase reads

---

### Root Cause #3: Phase 1 Patch Side Effect (HIGH CONFIDENCE)

**The timing**: Phase 1 (commit 4337b7a) lowered threshold from 80% to 65%.

**Scenario**:
- Pre-patch: Bot could cold-start with _QUOTA_READS up to 40k, still readable
- Post-patch: Bot cannot cold-start if _QUOTA_READS > 32.5k
- Yesterday exceeded limit → counter stayed at 50k
- Today before reset → load_history() fails silently
- Returns empty cache → bootstrap sees nothing

**Root cause**: Quota guard + stale empty cache + reset timing

---

## Files and Functions Involved

| File | Function/Location | Issue |
|------|------------------|-------|
| src/services/firebase_client.py | _can_read() line 116 | Threshold 65% (from Phase 1) |
| src/services/firebase_client.py | load_history() line 363-366 | Returns empty cache on quota block |
| src/services/firebase_client.py | _HISTORY_CACHE line 44 | Initialized to empty `{"data": []}` |
| src/services/firebase_client.py | _reset_quota_if_new_day() line 70-97 | Reset happens at 07:00 UTC, not at startup |
| bot2/main.py | main() line 1458-1477 | Hydrate Metrics/LM from Redis (may be empty) |
| bot2/main.py | main() line 1483 | load_history() called BEFORE quota reset |
| bot2/main.py | main() line 1496-1501 | Bootstrap from (possibly empty) _history |
| bot2/main.py | Line 212-215 | Phase 1 patch set threshold to 65% |

---

## Ranked Root Cause Candidates

| Rank | Cause | Confidence | Impact |
|------|-------|-----------|--------|
| 1 | Quota guard + empty cache at startup before reset | **HIGH** | Blocks load_history() on cold start if yesterday exhausted |
| 2 | Phase 1 threshold lowered from 80% → 65% | **HIGH** | Made quota guard stricter, triggered on higher residual counts |
| 3 | Startup order loads empty state before quota reset | **MEDIUM** | Bootstrap uses empty _history before reset happens |
| 4 | Redis hydration returns empty on fresh/cleared state | **MEDIUM** | Metrics/LM start empty, never populate from that source |

---

## Minimal Safe Fix Plan

### Option 1: Don't Block Reads on Startup (RECOMMENDED)

**Rationale**: At startup, fresh quota reset should be assumed safe.

```python
# firebase_client.py: load_history() line 361-366

# BEFORE
allowed, current, limit_quota = _can_read(estimated_reads)
if not allowed:
    logging.debug(f"Skipping history fetch: quota limit reached ({current}/{limit_quota})")
    return list(_HISTORY_CACHE["data"][:limit])

# AFTER: Allow at least ONE cold-start read before blocking
# Check if we're within startup window (first 5 min after quota reset)
if not allowed:
    from datetime import datetime, timezone, timedelta
    pacific_tz = timezone(timedelta(hours=-7))
    now_utc = datetime.now(timezone.utc)
    now_pacific = now_utc.astimezone(pacific_tz)
    midnight_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
    time_since_reset = (now_utc - midnight_pacific.astimezone(timezone.utc)).total_seconds()
    
    if time_since_reset > 300:  # More than 5 min after reset, honor quota block
        logging.debug(f"Skipping history fetch: quota limit reached ({current}/{limit_quota})")
        return list(_HISTORY_CACHE["data"][:limit])
    # else: within startup window, allow read
```

**Scope**: 1 file (firebase_client.py), ~15 lines  
**Risk**: Very low (only affects first 5 minutes after quota reset)

---

### Option 2: Initialize Cache with Sensible Default

**Rationale**: Cache shouldn't return empty on first read; initialize with empty signal.

```python
# firebase_client.py line 44
# BEFORE
_HISTORY_CACHE = {"data": [], "ts": 0, "limit": 0}

# AFTER  
_HISTORY_CACHE = {
    "data": [],
    "ts": time.time(),           # Mark as "just initialized"
    "limit": 0,
    "is_startup": True           # Flag for startup context
}
```

Then check this flag in load_history() to allow startup reads.

**Scope**: 2 locations, ~5 lines  
**Risk**: Low (informational flag only)

---

### Option 3: Explicitly Reset Quota at Startup (SAFEST)

**Rationale**: Don't rely on timing; force quota reset when bot starts.

```python
# bot2/main.py: main() line ~1380 (early in startup)

# Add before init_firebase():
from src.services.firebase_client import _reset_quota_if_new_day
_reset_quota_if_new_day()  # Ensure quota is fresh
```

**Scope**: 2 lines in bot2/main.py  
**Risk**: Very low (forced reset can't hurt)

---

## No EV/RDE/Execution Changes

- ✅ No decision logic modified
- ✅ No execution behavior changed
- ✅ No Firebase schema changed
- ✅ No trading parameters changed

---

## Summary

**Root Cause**: Quota guard blocks startup read because yesterday's counter persists → empty cache returned → bootstrap sees 0 trades.

**Trigger**: Phase 1 patch lowered threshold to 65%, making guard stricter. Combined with old quota counter (50k from yesterday), blocks cold start reads.

**Fix**: Allow at least one read at startup, or explicitly reset quota at boot time.

---

**Status**: Analysis complete. Awaiting approval for minimal fix implementation.
