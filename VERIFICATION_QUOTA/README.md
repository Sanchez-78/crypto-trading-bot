# Firebase Quota System Verification & Deployment Guide

## Quick Summary

✅ **Firebase quota protection system has been completely verified and fixed.**

The system now enforces:
- **50,000 reads/day** limit (prevents 429 errors from excessive load_auditor_state() calls)
- **20,000 writes/day** limit (prevents 429 errors from excessive trade batch writes)

### What Was Fixed

**Two critical bugs** that prevented the quota system from actually protecting against 429 errors:

1. **_mark_quota_exhausted()** now actually marks quota as exhausted when 429 errors occur
   - Before: Only logged the error, didn't prevent further operations
   - After: Sets read/write counters to their limits, blocking all further operations

2. **save_batch()** now detects 429 errors reactively (like read functions did)
   - Before: Write quota exhaustion wasn't detected, operations queued indefinitely
   - After: 429 errors detected and quota marked exhausted immediately

---

## What Was Verified

### ✅ Unit Tests (37/37 Passing)
```bash
python test_quota_system.py
```
Tests verify:
- Quota system initializes correctly
- Pre-flight checks work (blocking operations when quota would be exceeded)
- Counters increment correctly
- Warnings appear at 90% utilization
- Quota resets at 24-hour UTC boundary
- 429 error handling marks quota as exhausted
- Status reporting works

### ✅ Code Review (QUOTA_CODE_REVIEW.md)
- All quota tracking functions examined
- Integration points verified (load_auditor_state, load_history, save_batch)
- Bugs identified and documented
- Fixes validated

### ✅ Deployment Guide (DEPLOYMENT_VALIDATION.md)
- Step-by-step deployment instructions
- Live validation tests for each component
- Success criteria and rollback plan

---

## Monitoring Tools Available

### 1. Real-time Quota Status (Python API)
```python
from src.services import firebase_client

status = firebase_client.get_quota_status()
print(f"Reads: {status['reads']}/{status['reads_limit']} ({status['reads_pct']})")
print(f"Writes: {status['writes']}/{status['writes_limit']} ({status['writes_pct']})")
```

### 2. Command-Line Monitor Tool
```bash
# One-time status check
python monitor_quota.py

# Continuous monitoring every 30 seconds
python monitor_quota.py --continuous

# JSON output for dashboard
python monitor_quota.py --json

# Verbose with diagnostics
python monitor_quota.py --verbose
```

---

## Deployment Steps

### Step 1: Verify Fixes in Source Code

The critical fixes are in `src/services/firebase_client.py`:

**Fix #1** (lines 105-110): `_mark_quota_exhausted()` now sets counters to limits
```python
def _mark_quota_exhausted(error_msg: str):
    global _QUOTA_READS, _QUOTA_WRITES
    _QUOTA_READS = _QUOTA_MAX_READS      # ← NEW
    _QUOTA_WRITES = _QUOTA_MAX_WRITES    # ← NEW
```

**Fix #2** (lines 309-311): `save_batch()` detects 429 errors
```python
except Exception as e:
    if "429" in str(e) or "Quota" in str(e):  # ← NEW
        _mark_quota_exhausted(str(e))         # ← NEW
```

### Step 2: Restart Bot with New Code

```bash
# Kill existing processes
taskkill /F /IM python.exe
timeout /t 5

# Start fresh
cd C:\Projects\CryptoMaster_srv
python start.py
```

### Step 3: Verify Startup

Wait for logs to show:
```
🚀 MAIN() STARTING
🔗 Redis connected
📊 Dashboard starting on port 8000
🔄 Event bus listening
💰 Market stream connected
```

### Step 4: Monitor First Hour

Run quota monitor in separate terminal:
```bash
python VERIFICATION_QUOTA/monitor_quota.py --continuous --interval 30
```

Expected to see:
- Quota status starts at 0/50000 reads, 0/20000 writes
- Quota counters incrementing as trades execute
- NO "429 Quota exceeded" errors in logs
- Warnings appear when approaching 90% (if trading heavily)

---

## What Happens Now

### Proactive Protection (Pre-flight Checks)

Before every Firebase operation, the system checks:
```
Can I read? → _can_read(1) → Allowed? → Yes: proceed, No: use cache
Can I write? → _can_write(N) → Allowed? → Yes: proceed, No: queue batch
```

### Reactive Protection (429 Error Detection)

If a 429 error occurs anyway:
```
Exception caught → Check if "429" in error message
→ Yes → _mark_quota_exhausted() → Set counters to limits
→ Block all further Firebase operations until midnight UTC reset
```

### Graceful Degradation

When quota approaching or exhausted:
```
load_history() → Returns stale cached trades (old data, but works)
load_auditor_state() → Returns {} (empty state, bot adapts)
save_batch() → Queues trades to _RETRY_QUEUE for later flush
```

Bot continues trading with available data until quota resets.

---

## Real-World Impact

### Before This Fix
- Bot hits 429 "Quota exceeded" errors
- Errors cascade without proper handling
- Learning pipeline blocks
- Bot becomes unresponsive

### After This Fix
- Pre-flight checks prevent operations when quota approaching
- 429 errors (if they occur) immediately mark quota as exhausted
- Bot gracefully uses cached data instead of failing
- Learning pipeline completes with available data
- At midnight UTC, quota resets and normal operations resume

---

## How to Verify Success

After 1 hour of trading:

```bash
# Check 1: Monitor shows healthy usage
python VERIFICATION_QUOTA/monitor_quota.py
# Expected: Reads under 10%, Writes under 5%, No 429 errors

# Check 2: No 429 errors in logs
grep "429\|Quota exceeded" bot2.log
# Expected: No matches (or old errors from before restart)

# Check 3: Trades executing normally
grep "\[OPEN\]" bot2.log | wc -l
# Expected: Positive number (at least 5-10)

# Check 4: Learning accumulating data
grep "lm_update\|learn" bot2.log | tail -5
# Expected: Shows learning_monitor processing trades
```

---

## Quota Usage Estimation

### Typical Daily Usage

Based on trading patterns:

**Reads** (~200-500 per day):
- load_history(): ~1 per 5 minutes = 288 reads/day
- load_auditor_state(): ~100-200 per day (on signal generation)
- **Subtotal**: ~400 reads/day (0.8% of 50,000 limit)

**Writes** (~500-1000 per day):
- save_batch(): ~N writes per batch
- 100 trades/day × 3 docs per trade = ~300 writes/day
- Metrics updates: ~200 writes/day
- **Subtotal**: ~500 writes/day (2.5% of 20,000 limit)

**Total Usage**: ~0.9% of daily quota
**Safety Margin**: ~99x buffer before quota exhaustion

### High-Activity Scenario

If trading 500 trades/day instead:
- Reads: ~500/day (1% of 50,000)
- Writes: ~1,500-2,500/day (7.5-12.5% of 20,000)
- Still sustainable with comfortable margin

---

## Monitoring Dashboard Metrics

The quota status API exposes:

```json
{
  "reads": 1250,
  "reads_limit": 50000,
  "reads_pct": "2.5%",
  "writes": 450,
  "writes_limit": 20000,
  "writes_pct": "2.3%"
}
```

Can be integrated into:
- Bot dashboard `/api/quota` endpoint
- Monitoring systems (Prometheus, Grafana)
- Alert systems (trigger at 75%, 90%, 100%)
- Daily reports

---

## Files in This Directory

1. **README.md** (this file)
   - Quick reference and deployment guide

2. **IMPLEMENTATION_SUMMARY.md**
   - Complete architecture documentation
   - Details of both bugs and fixes
   - Expected behavior and troubleshooting

3. **QUOTA_CODE_REVIEW.md**
   - Line-by-line code review
   - Identifies bugs and analyzes impact
   - Deployment checklist

4. **DEPLOYMENT_VALIDATION.md**
   - Detailed deployment steps
   - Live validation test procedures
   - Success criteria

5. **test_quota_system.py**
   - Unit test suite (37 tests, all passing)
   - Tests every aspect of quota system
   - Can be run repeatedly for regression testing

6. **monitor_quota.py**
   - Command-line monitoring tool
   - Real-time status checking
   - JSON output for integration
   - Continuous monitoring mode

---

## Commit History

```
dbadf93 - Add comprehensive quota system verification, tests, and monitoring tools
eedc30d - Fix Firebase quota system: mark quota exhausted on 429 errors (reads + writes)
```

Both commits are on `main` branch and pushed to GitHub.

---

## Quick Troubleshooting

### "⚠️ Firebase reads: 45,000/50,000 (90.0%)"

**What it means**: Quota approaching 90% utilization (warning threshold)

**Action needed**: Monitor closely. If projected daily usage would exceed 50k, investigate:
- Is signal_generator subscribing too frequently?
- Is load_auditor_state() being called more than expected?
- May need to increase cache TTL or reduce polling frequency

### "⚠️ Firebase 429 error: ... — marked quota exhausted"

**What it means**: Quota completely exhausted. System has marked it as such.

**Action needed**: 
- No urgent action needed
- Bot will continue with cached data
- At midnight UTC (86400s after window start), quota resets
- Check logs: look for "Firebase quota window reset" message

### "Skipping history fetch: quota limit reached"

**What it means**: Pre-flight check blocked read operation (quota would exceed)

**Action needed**:
- System is working as designed
- load_history() returned stale cached data instead
- No actual Firebase read performed
- Check monitor for current quota status

---

## Next Steps

1. ✅ Code reviewed and fixes verified
2. ✅ All tests passing (37/37)
3. ✅ Monitoring tools available
4. ✅ Documentation complete
5. → **Restart bot with new code**
6. → **Monitor quota status for first 24 hours**
7. → **Confirm no 429 errors occur**
8. → **Verify learning pipeline working correctly**
9. → **Long-term monitoring for quota trends**

---

## Success Criteria

After deployment, confirm:

- [ ] Bot starts without errors
- [ ] Quota shows 0/50000 reads, 0/20000 writes at startup
- [ ] Trades execute normally
- [ ] No "429 Quota exceeded" errors in logs
- [ ] Quota counters increment correctly
- [ ] No "Quota exceeded" cascade errors
- [ ] Learning pipeline accumulating trade data
- [ ] At 90% utilization, warning logs appear
- [ ] System doesn't crash even if quota exhausted
- [ ] Quota resets at midnight UTC

---

**Status**: ✅ READY FOR DEPLOYMENT  
**Last Verified**: 2026-04-21  
**Tests Passing**: 37/37 ✅
