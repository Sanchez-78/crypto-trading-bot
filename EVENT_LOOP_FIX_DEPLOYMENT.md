# Event Loop Binding Fix - Deployment Guide (V10.13n)

## What Was Fixed

The critical "RuntimeError: Event loop is closed" error that was blocking learning state persistence has been resolved.

### Root Cause
In `state_manager.py`, the Redis client was stored as a module-level variable (`_redis_client: Any | None = None`) that was created once and persisted across multiple event loop lifecycles. The problem:

1. `_run()` creates a fresh event loop with `asyncio.new_event_loop()`
2. Redis client (created in first loop) was cached in module scope
3. `asyncio.run()` completes and closes the first loop
4. Next `_run()` call creates a NEW loop but tries to use the Redis client from the CLOSED loop
5. Result: "RuntimeError: Event loop is closed" on pipeline operations

### The Fix
Removed persistent module-level variable and modified `_get_client()` to create a fresh Redis client on each call:

- **REMOVED**: `_redis_client: Any | None = None` module variable
- **REMOVED**: `global _redis_client` declaration
- **CHANGED**: `_get_client()` now creates fresh client each time (no caching)
- **BENEFIT**: Each event loop gets its own fresh Redis client, bound to that loop's context

### Code Change Location
File: `src/services/state_manager.py`
Lines: 71-121 (function `_get_client()`)
Commit: 13f844f

## Deployment Steps

### 1. On Production Linux Server

```bash
cd /path/to/CryptoMaster_srv
git pull origin main
```

### 2. Restart the Bot Service

```bash
systemctl restart cryptomaster
```

Or if using docker:

```bash
docker-compose restart cryptomaster
```

### 3. Verify the Fix

Monitor logs for the next 5 minutes to confirm:

```bash
# Should NOT see "Event loop is closed" errors
journalctl -u cryptomaster -f | grep -i "event loop"

# Should see learning state flushes resuming
journalctl -u cryptomaster -f | grep -i "FLUSH_LM"

# Check quota status accumulation
journalctl -u cryptomaster -f | grep -i "quota"
```

## Expected Behavior After Fix

### Immediately After Restart (Next 5 Minutes)
- ✅ No "RuntimeError: Event loop is closed" errors in logs
- ✅ Learning state flush logs: `[FLUSH_LM_OK]` messages appearing
- ✅ Firebase quota counters beginning to accumulate (moving from 0/0)

### Within Next Hour
- ✅ Learning monitor receiving updates from completed trades
- ✅ `[LEARNING: MONITOR]` section shows non-zero EV values for active pairs
- ✅ Quota accumulation: typically 5-20 writes per successful trade flush

### After Next UTC Midnight Reset
- ✅ Quota counters reset to 0/0
- ✅ Bot resumes Firebase operations normally (if not in cooldown)
- ✅ Learning system continues operating normally

## Quota Impact Analysis

The fix enables learning state persistence, which will accumulate Firebase writes:

**Projected Usage After Fix:**
- **Learning flushes**: ~1-3 writes per completed trade
- **Typical trading rate**: 50-100 trades/day in favorable conditions
- **Expected writes/day**: 50-300 (still well under 20,000/day limit)
- **Current quota**: 50,000 reads/day, 20,000 writes/day

**Safety Margin:** Even at 300 writes/day, you're using only 1.5% of daily write quota.

## What This Doesn't Fix

This fix specifically addresses:
- ✅ Event loop lifecycle issues in state_manager.py
- ✅ Learning state persistence to Firebase
- ✅ Quota accumulation and monitoring

This does NOT address:
- Market conditions causing low win rate (that's handled by risk management)
- Position exit timing (working as designed)
- Trading signal generation (working as designed)

## Rollback Plan

If issues arise after deployment:

```bash
git revert HEAD
git push origin main
systemctl restart cryptomaster
```

## References

- **Previous Work**: Summary of event loop issues and quota system validation (from previous session)
- **Module Context**: src/services/state_manager.py (Redis persistence layer)
- **Related Files**: src/services/firebase_client.py (quota tracking), bot2/main.py (main event loop)
