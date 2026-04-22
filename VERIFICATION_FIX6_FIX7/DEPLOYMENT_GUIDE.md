# V10.13v Deployment Guide: Fix 6 + Fix 7

## Overview
This guide covers deploying V10.13v (Fix 6 + Fix 7) to the production server.

## Pre-Deployment Checklist

- [x] All changes committed to git (commit: 1943949)
- [x] All changes pushed to GitHub
- [x] Syntax validation passed
- [x] Test script created and documented
- [x] Implementation summary written
- [x] No breaking changes (purely additive)
- [x] Graceful error handling in place

## Deployment Steps

### Step 1: Pull Latest Changes on Server
```bash
ssh -i ~/.ssh/hetzner_root root@78.47.2.198
cd /path/to/CryptoMaster_srv
git fetch origin
git pull origin main
```

### Step 2: Verify Changes Deployed
```bash
# Check that the new files are present
ls -la src/services/exit_attribution.py
ls -la VERIFICATION_FIX6_FIX7/

# Verify syntax
python -m py_compile src/services/exit_attribution.py
python -m py_compile src/services/trade_executor.py
python -m py_compile src/services/realtime_decision_engine.py
```

### Step 3: Run Test Script (Optional)
```bash
cd /path/to/CryptoMaster_srv
python VERIFICATION_FIX6_FIX7/test_canonical_output.py
```

Expected output shows:
- Canonical decision logs with complete metadata
- Validation detecting negative-EV violations
- Exit attribution summary with counts, win rates, PnL

### Step 4: Restart Bot
```bash
# Kill existing bot process
ps aux | grep CryptoMaster
kill -9 <pid>

# Or use whatever orchestration script you have
python bot2/orchestrator.py start
```

### Step 5: Monitor Logs
Watch for these log markers indicating successful deployment:

**Fix 6 (Canonical Decision Logging):**
```
[V10.13v DECISION] BTCUSDT BUY BULL_TREND WITH_REGIME
  tag=MOMENTUM_UP stage=RDE
  ev_raw=0.0500 ev_coh=0.0348 ev_final=0.0348
  ...
  result=TAKE
```

**Fix 7 (Exit Attribution):**
```
[V10.13v EXIT_ATTRIBUTION]
  Total trades: N  |  Net PnL: +X.XXXXXX
  TP                   count=...  share=...  wr=...  net=...
  PARTIAL_TP_50        count=...  share=...  wr=...  net=...
  SCRATCH_EXIT         count=...  share=...  wr=...  net=...
  ...
```

## Monitoring for Issues

### Watch for These Errors
```
[V10.13v DECISION_INTEGRITY_ERROR]  - Decision validation failed
[V10.13v EXIT_INTEGRITY_ERROR]       - Exit validation failed
```

If these appear, check:
1. Recent code changes affecting decision/exit logic
2. Corrupted state in Redis or Firebase
3. Check server logs: `tail -f /var/log/cryptomaster.log`

### Expected Behavior
- Decision logs should be cleaner and more uniform
- Every exit now has a canonical `final_exit_type`
- Exit attribution summary shows clear contribution by exit type
- No negative-EV trades should appear in logs (they're rejected before logging)

## Rollback Plan

If critical issues occur, rollback is simple (changes are purely additive):

### Option 1: Revert Commit
```bash
git revert 1943949
git push origin main
# Restart bot
```

### Option 2: Disable Fixes (Keep Code)
Comment out integration calls:
- In `realtime_decision_engine.py`: Comment out `_log_canonical_decision()` calls
- In `trade_executor.py`: Comment out `build_exit_ctx()` and `update_exit_attribution()` calls
- Existing code paths unaffected

## Performance Impact

**Memory**: Minimal
- `_exit_stats` dict grows linearly with exit types (max ~16 types)
- Per type: ~200 bytes of stats

**CPU**: Negligible
- `validate_decision_ctx()`: ~1ms per decision
- `validate_exit_ctx()`: <0.5ms per close
- Dictionary operations: O(1)

**Firebase**: No change
- Exit attribution is computed locally
- Not persisted to Firebase (dashboard reads local stats)

## Post-Deployment Verification

### 1. Check Decision Logs
```bash
grep "\[V10.13v DECISION\]" /var/log/cryptomaster.log | head -20
# Should see clean canonical format with no contradictions
```

### 2. Check Exit Attribution
```bash
grep "\[V10.13v EXIT_ATTRIBUTION\]" /var/log/cryptomaster.log
# Should see exit type breakdown after sufficient trades
```

### 3. Verify No Negative-EV Trades
```bash
grep "decision=TAKE.*ev=-" /var/log/cryptomaster.log
# Should return NOTHING (all negative EVs rejected)
```

### 4. Check for Validation Errors
```bash
grep "INTEGRITY_ERROR" /var/log/cryptomaster.log
# Should be EMPTY (no validation errors)
```

## Monitoring Dashboard

Once deployed, the exit attribution summary will appear in:
1. **Console logs**: Search for `[V10.13v EXIT_ATTRIBUTION]`
2. **Firebase**: If dashboard queries local stats endpoint
3. **Learning monitor**: Can integrate exit stats into health metrics

### Understanding Exit Attribution Output

```
TP                  count=3   share=2.6%   wr=100.0%  net=+0.000329  avg=+0.000110
PARTIAL_TP_50       count=22  share=19.1%  wr=95.5%   net=+0.000156  avg=+0.000007
SCRATCH_EXIT        count=24  share=20.9%  wr=0.0%    net=-0.000018  avg=-0.000001
```

**Interpretation:**
- TP exits: **Edge generators** (100% win rate, +0.000329 total)
- PARTIAL_TP_50: **High quality** (95.5% win rate, 19% of exits)
- SCRATCH_EXIT: **Defensive** (0% win rate, -0.000018 loss but protective)
- **Verdict**: Edge concentrated in TP and partial exits (21.7% of all trades generate bulk of profits)

## Troubleshooting

### Issue: No Exit Attribution Appearing
**Cause**: No trades closed yet  
**Solution**: Wait for first trade closure after deployment

### Issue: Validation Errors in Logs
**Cause**: State mismatch or data corruption  
**Solution**: 
```bash
# Check if Firebase data is stale
python -m src.services.reset_db
# Restart bot
```

### Issue: Decision Logs Missing
**Cause**: Integration not firing or logging disabled  
**Solution**: 
```bash
# Check that functions exist
grep "_log_canonical_decision" src/services/realtime_decision_engine.py
# Should see the function calls
```

## Success Criteria

✅ **Deployment successful when:**
1. No syntax errors during import
2. Bot starts without errors
3. Canonical decision logs appear within first cycle
4. No `DECISION_INTEGRITY_ERROR` or `EXIT_INTEGRITY_ERROR` messages
5. Exit attribution summary appears after first trade closes
6. Zero negative-EV trades in logs (all rejected at gate)

## Questions & Support

For deployment issues:
1. Check logs: `tail -f /var/log/cryptomaster.log | grep V10.13v`
2. Review `IMPLEMENTATION_SUMMARY.md` for technical details
3. Check test script: `python VERIFICATION_FIX6_FIX7/test_canonical_output.py`
4. Compare with expected output in this guide

## Version Info

**Current Version**: V10.13v  
**Commit**: 1943949  
**Branch**: main  
**Changes**: 933 insertions, 5 files touched  
**Backward Compatibility**: ✅ Fully compatible (purely additive)  
**Rollback Risk**: 🟢 Low (changes isolated to logging/reporting)  

---

**Deployment Date**: [Fill in after deployment]  
**Deployed By**: [Engineer name]  
**Status**: [Pending / In Progress / Complete]  
**Issues Encountered**: [None / List if any]  
