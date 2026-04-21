# Firebase Quota System - Code Review & Verification

## Status
**⚠️ CRITICAL BUGS FOUND** - Two issues prevent quota protection from working correctly.

## Architecture Overview

The quota system implements **two-tiered defense**:

1. **Proactive**: Pre-flight checks before every operation using `_can_read()` and `_can_write()`
2. **Reactive**: Detect 429 errors and mark quota as exhausted until midnight UTC reset

### Global State (lines 42-47)
```python
_QUOTA_WINDOW_START = time.time()
_QUOTA_READS = 0
_QUOTA_WRITES = 0
_QUOTA_MAX_READS = 50000
_QUOTA_MAX_WRITES = 20000
```
✅ **CORRECT**: Initialized at module load; reset at 86400s boundaries

---

## Core Functions Review

### 1. `_reset_quota_if_new_day()` (lines 49-58)
```python
def _reset_quota_if_new_day():
    now = time.time()
    if now - _QUOTA_WINDOW_START > 86400:
        _QUOTA_WINDOW_START = now
        _QUOTA_READS = 0
        _QUOTA_WRITES = 0
```
✅ **CORRECT**: Resets counters at 24-hour UTC boundary

---

### 2. `_can_read(count=1)` & `_can_write(count=1)` (lines 60-78)
```python
def _can_read(count=1):
    _reset_quota_if_new_day()
    allowed = (_QUOTA_READS + count) <= _QUOTA_MAX_READS
    return allowed, _QUOTA_READS, _QUOTA_MAX_READS

def _can_write(count=1):
    _reset_quota_if_new_day()
    allowed = (_QUOTA_WRITES + count) <= _QUOTA_MAX_WRITES
    return allowed, _QUOTA_WRITES, _QUOTA_MAX_WRITES
```
✅ **CORRECT**: Pre-flight checks that prevent operations when quota would be exceeded

---

### 3. `_record_read(count=1)` & `_record_write(count=1)` (lines 66-86)
```python
def _record_read(count=1):
    global _QUOTA_READS
    _QUOTA_READS += count
    if _QUOTA_READS > _QUOTA_MAX_READS * 0.9:
        logging.warning(...)

def _record_write(count=1):
    global _QUOTA_WRITES
    _QUOTA_WRITES += count
    if _QUOTA_WRITES > _QUOTA_MAX_WRITES * 0.9:
        logging.warning(...)
```
✅ **CORRECT**: Increments counters; warns at 90% utilization

---

### 4. `get_quota_status()` (lines 88-98)
```python
def get_quota_status():
    _reset_quota_if_new_day()
    return {
        "reads": _QUOTA_READS,
        "reads_limit": _QUOTA_MAX_READS,
        "reads_pct": f"{_QUOTA_READS/_QUOTA_MAX_READS*100:.1f}%",
        "writes": _QUOTA_WRITES,
        "writes_limit": _QUOTA_MAX_WRITES,
        "writes_pct": f"{_QUOTA_WRITES/_QUOTA_MAX_WRITES*100:.1f}%",
    }
```
✅ **CORRECT**: Returns current usage for monitoring

---

### 5. `_mark_quota_exhausted(error_msg: str)` (lines 105-108)
```python
def _mark_quota_exhausted(error_msg: str):
    """Mark quota as exhausted via 429 error (reactive)."""
    import logging
    logging.warning(f"⚠️  Firebase 429 error: {error_msg} — stopping reads/writes")
```
❌ **CRITICAL BUG**: Only logs the error but **DOES NOT ACTUALLY MARK QUOTA AS EXHAUSTED**

**Problem**: When a 429 error occurs:
- Function logs it
- But doesn't set `_QUOTA_READS` or `_QUOTA_WRITES` to their limits
- So future `_can_read()` calls still return True
- Firebase calls continue and hit more 429 errors

**Fix Required**:
```python
def _mark_quota_exhausted(error_msg: str):
    """Mark quota as exhausted via 429 error (reactive)."""
    global _QUOTA_READS, _QUOTA_WRITES
    import logging
    # Set quotas to their limits to prevent further operations
    _QUOTA_READS = _QUOTA_MAX_READS
    _QUOTA_WRITES = _QUOTA_MAX_WRITES
    logging.warning(f"⚠️  Firebase 429 error: {error_msg} — marked quota exhausted until midnight UTC reset")
```

---

## Function Integration Review

### `load_auditor_state()` (lines 871-893)
```python
def load_auditor_state():
    allowed, current, limit = _can_read(1)
    if not allowed:
        return {}
    
    try:
        doc = db.collection(...).document("auditor").get()
        _record_read(1)
        return doc.to_dict() or {}
    except Exception as e:
        if "429" in str(e) or "Quota" in str(e):
            _mark_quota_exhausted(str(e))  # ← BUG: This doesn't actually mark it exhausted
            return {}
        ...
```
✅ Pre-flight check: **CORRECT**
❌ Reactive 429 handling: **USES BUGGY _mark_quota_exhausted()**

---

### `load_history()` (lines 210-248)
```python
def load_history(limit=HISTORY_LIMIT):
    if time.time() - _HISTORY_CACHE["ts"] < HISTORY_TTL:
        return _HISTORY_CACHE["data"]
    
    allowed, current, limit_quota = _can_read(1)
    if not allowed:
        return _HISTORY_CACHE["data"]  # Return stale cache
    
    try:
        docs = db.collection(...).stream()
        _HISTORY_CACHE["data"] = [d.to_dict() for d in docs]
        _record_read(1)
        ...
    except Exception as e:
        if "429" in str(e) or "Quota" in str(e):
            _mark_quota_exhausted(str(e))  # ← BUG: This doesn't actually mark it exhausted
        ...
    return _HISTORY_CACHE["data"]
```
✅ Pre-flight check: **CORRECT**
✅ Stale cache fallback: **CORRECT**
❌ Reactive 429 handling: **USES BUGGY _mark_quota_exhausted()**

---

### `save_batch()` (lines 251-317)
```python
def save_batch(batch):
    if _RETRY_QUEUE:
        batch = list(_RETRY_QUEUE) + list(batch)
        _RETRY_QUEUE.clear()
    
    try:
        slimmed = [_slim_trade(t) for t in batch]
        
        allowed, current, limit_writes = _can_write(len(slimmed))
        if not allowed:
            _RETRY_QUEUE.extend(batch)
            return 0
        
        fb_batch = db.batch()
        for item in slimmed:
            fb_batch.set(db.collection(...).document(), item)
        fb_batch.commit()
        _record_write(len(slimmed))
        ...
        return len(batch)
    except Exception as e:
        print(f"⚠️  save_batch failed ({e}) — queuing for retry")
        if len(_RETRY_QUEUE) < _MAX_RETRY_SIZE:
            _RETRY_QUEUE.extend(batch)
        ...
        return 0
```
✅ Pre-flight check: **CORRECT**
❌ Reactive 429 handling: **MISSING - No detection of 429 errors**

**Problem**: If a 429 error occurs during `fb_batch.commit()`:
- Catch block queues the batch
- But doesn't call `_mark_quota_exhausted()`
- So the next `save_batch()` call will try again immediately
- This is inconsistent with the read functions

**Fix Required**: Add 429 detection in the except clause:
```python
except Exception as e:
    if "429" in str(e) or "Quota" in str(e):
        _mark_quota_exhausted(str(e))
    print(f"⚠️  save_batch failed ({e}) — queuing for retry")
    ...
```

---

## Summary of Issues

| Issue | Severity | Location | Impact |
|-------|----------|----------|--------|
| `_mark_quota_exhausted()` doesn't set counters | CRITICAL | Line 105-108 | Quota exhaustion not properly marked; 429 errors cascade |
| `save_batch()` missing 429 detection | CRITICAL | Line 308-317 | Write quota exhaustion not detected reactively |
| Missing reactive fallback for writes | HIGH | `save_batch()` | No equivalent to "return stale cache" for writes |

---

## Deployment Checklist

- [ ] Fix `_mark_quota_exhausted()` to set `_QUOTA_READS` and `_QUOTA_WRITES` to limits
- [ ] Add 429 error detection to `save_batch()` except clause
- [ ] Deploy and restart bot
- [ ] Monitor `get_quota_status()` output in logs
- [ ] Verify bot trades without 429 errors even if quota approaching limit
- [ ] Test quota reset at midnight UTC (or inject reset for testing)
- [ ] Verify learning pipeline accumulates data correctly with quota guards

---

## Quota Tracking Verification Points

### Pre-Deployment
1. ✅ Code compiles without syntax errors
2. ✅ All quota tracking functions defined and callable
3. ✅ Pre-flight checks protect both reads and writes
4. ⚠️ Reactive 429 handling implemented (BUGS FOUND)

### Post-Deployment Testing
1. Verify initial quota status: `get_quota_status()` should return 0/50000 and 0/20000
2. Make a trade and check `get_quota_status()` — reads should increment
3. Monitor logs for "⚠️ Firebase reads: N/50000" warnings as approaching 90%
4. Simulate quota exhaustion (set `_QUOTA_READS = 50000` in debugger)
5. Verify bot doesn't crash; `load_history()` returns stale cache
6. Verify bot doesn't attempt new Firebase reads
7. Verify at midnight UTC (or after reset), quota resets and reads resume

---

## Next Steps

1. **Immediate**: Fix the two critical bugs identified above
2. **Deploy**: Restart bot with fixed code
3. **Monitor**: Watch logs for quota status and 429 errors
4. **Verify**: Run test cases to confirm quota protection working
5. **Measure**: Track actual read/write usage against 50k/day and 20k/day limits
