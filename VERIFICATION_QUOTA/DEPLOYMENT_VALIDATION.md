# Firebase Quota System - Deployment Validation Plan

## Fixes Applied

### Fix #1: `_mark_quota_exhausted()` Now Actually Marks Quota as Exhausted
**File**: `src/services/firebase_client.py` (lines 105-110)

**Before**:
```python
def _mark_quota_exhausted(error_msg: str):
    """Mark quota as exhausted via 429 error (reactive)."""
    import logging
    logging.warning(f"⚠️  Firebase 429 error: {error_msg} — stopping reads/writes")
```

**After**:
```python
def _mark_quota_exhausted(error_msg: str):
    """Mark quota as exhausted via 429 error (reactive)."""
    global _QUOTA_READS, _QUOTA_WRITES
    import logging
    # Set quotas to their limits to immediately prevent further operations
    _QUOTA_READS = _QUOTA_MAX_READS
    _QUOTA_WRITES = _QUOTA_MAX_WRITES
    logging.warning(f"⚠️  Firebase 429 error: {error_msg} — marked quota exhausted until midnight UTC reset")
```

**Impact**: When a 429 error occurs, quotas are immediately set to their limits, preventing cascading errors.

---

### Fix #2: `save_batch()` Now Detects 429 Errors
**File**: `src/services/firebase_client.py` (lines 308-320)

**Before**:
```python
    except Exception as e:
        print(f"⚠️  save_batch failed ({e}) — queuing for retry (no blocking sleep)")
        if len(_RETRY_QUEUE) < _MAX_RETRY_SIZE:
            _RETRY_QUEUE.extend(batch)
        else:
            print(f"⚠️  _RETRY_QUEUE full ({len(_RETRY_QUEUE)} >= {_MAX_RETRY_SIZE}) — dropping batch")
        return 0
```

**After**:
```python
    except Exception as e:
        # Detect 429 Quota Exceeded errors (reactive fallback) — mark quota exhausted immediately
        if "429" in str(e) or "Quota" in str(e):
            _mark_quota_exhausted(str(e))
        print(f"⚠️  save_batch failed ({e}) — queuing for retry (no blocking sleep)")
        if len(_RETRY_QUEUE) < _MAX_RETRY_SIZE:
            _RETRY_QUEUE.extend(batch)
        else:
            print(f"⚠️  _RETRY_QUEUE full ({len(_RETRY_QUEUE)} >= {_MAX_RETRY_SIZE}) — dropping batch")
        return 0
```

**Impact**: Write quota exhaustion is now detected and marked immediately, making the quota system consistent with reads.

---

## Deployment Steps

### Step 1: Pre-Deployment Verification
```bash
# Check syntax
python -m py_compile src/services/firebase_client.py
# Expected: No output (success)
```

### Step 2: Commit the fixes
```bash
git add src/services/firebase_client.py
git commit -m "Fix Firebase quota system: mark quota as exhausted on 429 errors (reads + writes)"
git push origin main
```

### Step 3: Restart the bot
```bash
# Kill existing processes
taskkill /F /IM python.exe

# Wait 5 seconds
timeout /t 5

# Start fresh
cd C:\Projects\CryptoMaster_srv
python start.py
```

### Step 4: Verify Startup
Wait for the log output:
```
🚀 MAIN() STARTING
🔗 Redis connected
📊 Dashboard starting on port 8000
🔄 Event bus listening
💰 Market stream connected
```

---

## Live Validation Tests

### Test 1: Verify Quota Status at Startup
**Expected**: Initial quota counters should be 0

```
Get this from logs or dashboard:
{
    "reads": 0,
    "reads_limit": 50000,
    "reads_pct": "0.0%",
    "writes": 0,
    "writes_limit": 20000,
    "writes_pct": "0.0%"
}
```

**How to verify**:
```python
# In a Python REPL:
import sys
sys.path.insert(0, '/path/to/CryptoMaster_srv')
from src.services import firebase_client
print(firebase_client.get_quota_status())
```

---

### Test 2: Verify Bot Can Trade Without 429 Errors
**Duration**: Run for 1 hour
**Expected**: 
- Multiple trades executed
- NO "429 Quota exceeded" errors in logs
- Quota incrementing correctly

**How to verify**:
1. Run bot normally
2. Monitor logs with: `tail -f bot2.log | grep -E "(Firebase|429|quota|OPEN|CLOSE)"`
3. Confirm output shows:
   ```
   📥 Firebase: loaded N trades
   💾 Firebase: saved N trades
   [OPEN] BTC/USDT
   [CLOSE] BTC/USDT
   ⚠️ Firebase reads: N/50000
   ⚠️ Firebase writes: M/20000
   ```

---

### Test 3: Verify Pre-flight Quota Checks Work
**Objective**: Confirm system prevents operations when quota would be exceeded

**How to test**:
```python
# Simulate quota near limit (programmatically)
import src.services.firebase_client as fc
fc._QUOTA_READS = 49999

# Attempt an operation that would exceed quota
result = fc.load_history()

# Expected in logs:
# "Skipping history fetch: quota limit reached (49999/50000)"
# And result should return stale cache data, not hit Firebase
```

---

### Test 4: Verify Reactive 429 Detection
**Objective**: Confirm system immediately marks quota exhausted on error

**Setup**: Simulate a 429 error (requires Firebase test tools or manual intervention)

**Expected behavior**:
```
Initial state: 
  _QUOTA_READS = 10000
  _QUOTA_WRITES = 5000

After 429 error in load_auditor_state():
  _QUOTA_READS = 50000 (immediately set to limit)
  _QUOTA_WRITES = 5000  (unchanged)
  Log: "⚠️ Firebase 429 error: ... — marked quota exhausted until midnight UTC reset"

Next _can_read() call:
  Returns (False, 50000, 50000)
  Prevents further Firebase reads
```

---

### Test 5: Verify Midnight Quota Reset
**Objective**: Confirm quota resets at 86400s UTC boundary

**How to test**:
```python
# Check current window start and reset timing
import time
import src.services.firebase_client as fc

# Get current state
print(f"Window start: {fc._QUOTA_WINDOW_START}")
print(f"Current time: {time.time()}")
print(f"Elapsed: {time.time() - fc._QUOTA_WINDOW_START:.1f}s")

# Force a quota check to trigger reset if needed
status = fc.get_quota_status()
print(f"After check: {status}")
```

**Expected at midnight UTC**:
- Logs show: "[QUOTA_RESET] ..." message
- `_QUOTA_READS` and `_QUOTA_WRITES` reset to 0
- Bot resumes Firebase reads/writes normally

---

## Monitoring Dashboard

The bot should expose quota status via the dashboard API:

```
GET http://localhost:8000/api/quota
Response:
{
    "reads": 1250,
    "reads_limit": 50000,
    "reads_pct": "2.5%",
    "writes": 450,
    "writes_limit": 20000,
    "writes_pct": "2.3%",
    "window_start_utc": "2026-04-21T00:00:00Z",
    "seconds_until_reset": 86400
}
```

---

## Success Criteria

✅ **Deployment successful if**:
1. Bot starts without syntax errors
2. Quota status shows 0/50000 reads, 0/20000 writes at startup
3. Bot executes trades without 429 errors
4. Quota counters increment correctly (visible in logs)
5. Pre-flight checks prevent operations when quota approaching limit
6. 429 errors (if they occur) are caught and marked immediately
7. Quota resets at midnight UTC (or after 86400s since window start)
8. Learning pipeline accumulates data correctly while quota guards are active

---

## Rollback Plan

If quota system causes issues:

```bash
# Revert the commits
git revert <commit_hash>
git push origin main

# Or manually edit firebase_client.py to remove quota checks:
# - Comment out _can_read() calls in load_auditor_state, load_history, save_batch
# - Comment out _record_read() and _record_write() calls
# - This preserves quota tracking but disables protection

# Restart bot
taskkill /F /IM python.exe
python start.py
```

---

## Next Steps

1. ✅ Applied fixes to firebase_client.py
2. → Commit and push to main
3. → Restart bot
4. → Monitor logs for first 1 hour (Test 2)
5. → Run programmatic tests (Tests 3-5) if issues detected
6. → Verify learning pipeline still working after 8 hours
7. → Monitor quota usage over 24 hours to understand typical consumption
