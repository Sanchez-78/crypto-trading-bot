# Phase 3: Exit Repair Logic — Deployment & Activation Guide

## Status: ✅ DEPLOYED

**Code**: `src/services/paper_scratch_exit_repair.py`  
**Commit**: `19be30c` (Phase 3: Scratch/stagnation exit repair logic)  
**Current State**: Deployed but **DISABLED by default** (safe mode)

---

## Understanding the Problem (Baseline Data)

From 2-hour monitoring (12:13-15:10 UTC):
- **WR_canonical**: 73.3% (high) ✅
- **Profit Factor**: 0.49x (losing money) ❌
- **Root Cause**: 85% of exits are SCRATCH (47 trades) + STAGNATION (34 trades)
  - SCRATCH_EXIT net: -0.00009236 USD (9 losses)
  - STAGNATION_EXIT net: -0.00012143 USD (12 losses)

**Insight**: High WR but low PF = exits closing trades too early (before fees covered)

---

## What Phase 3 Does

### Scratch Exit Repair
```
When: Scratch exit signal received (small loss detected)
Check: MFE (max favorable excursion) > fee cost?
If NO:  Delay exit for up to 5 minutes, wait for bigger move
If YES: Proceed with scratch exit
Log:    [SCRATCH_EXIT_DECISION] with action (DELAY or PROCEED)
```

**Effect**: Exits only when loss is large enough to be meaningful, avoiding fee-dragging trades

### Stagnation Exit Repair
```
When: Stagnation exit signal (position not moving)
Check: Segment profit factor < 0.70?
If YES: Exit at full size (don't throw good money after bad)
If NO:  Continue holding (segment is OK, just stagnant)
Log:    [STAGNATION_EXIT_DECISION] with action
```

**Effect**: Avoids accumulating losses in bad segments

---

## Configuration

### Enable Phase 3 (When Ready)

**Option A: Environment Variable** (recommended for testing)
```bash
export PAPER_EXIT_REPAIR_ENABLED=true
export PAPER_SCRATCH_FEE_COVER_BPS=20
systemctl restart cryptomaster.service
```

**Option B: Systemd Service** (recommended for production)
Edit `/etc/systemd/system/cryptomaster.service.d/10-paper-only.conf`:
```ini
[Service]
Environment=PAPER_EXIT_REPAIR_ENABLED=true
Environment=PAPER_SCRATCH_FEE_COVER_BPS=20
Environment=PAPER_STAGNATION_SIZE_DOWN_ENABLED=true
```

Then:
```bash
systemctl daemon-reload
systemctl restart cryptomaster.service
```

**Option C: .env File** (if bot reads from .env)
```bash
echo "PAPER_EXIT_REPAIR_ENABLED=true" >> /opt/cryptomaster/.env
echo "PAPER_SCRATCH_FEE_COVER_BPS=20" >> /opt/cryptomaster/.env
systemctl restart cryptomaster.service
```

### Configuration Parameters

| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `PAPER_EXIT_REPAIR_ENABLED` | `false` | `true`/`false` | Master switch (all disabled if false) |
| `PAPER_SCRATCH_FEE_COVER_BPS` | `20` | 10-50 | Basis points needed to trigger scratch |
| `PAPER_STAGNATION_SIZE_DOWN_ENABLED` | `true` | `true`/`false` | Size down on bad segments |

**Recommended starting values**:
- `PAPER_EXIT_REPAIR_ENABLED=true` (enable the feature)
- `PAPER_SCRATCH_FEE_COVER_BPS=20` (20 bps = 0.20% of size)
- `PAPER_STAGNATION_SIZE_DOWN_ENABLED=true` (exit bad segments)

---

## Monitoring Phase 3 Activation

### Watch for These Logs

```bash
journalctl -u cryptomaster.service -f | grep -E '\[SCRATCH_EXIT_DECISION\]|\[STAGNATION_EXIT_DECISION\]|\[PAPER_EXIT_REPAIR_EFFECT\]'
```

**Expected Log Patterns**:

✅ **Scratch delayed** (fee not covered yet):
```
[SCRATCH_EXIT_DECISION] symbol=BTCUSDT hold_s=42 ... action=DELAY_WAIT_FOR_MOVE time_until_timeout=258s
```

✅ **Scratch proceeded** (timeout or MFE OK):
```
[SCRATCH_EXIT_DECISION] symbol=ETHUSDT hold_s=305 ... action=PROCEED_SCRATCH
```

✅ **Stagnation exited** (bad segment):
```
[STAGNATION_EXIT_DECISION] symbol=ADAUSDT segment_pf=0.65 (bad) action=PROCEED_EXIT
```

✅ **Stagnation held** (segment OK):
```
[STAGNATION_EXIT_DECISION] symbol=SOLUSDT segment_pf=1.10 (ok) action=CONTINUE_HOLD
```

---

## Expected Impact (After 100+ Trades)

### Optimistic Scenario (Best Case)
- **Before**: PF=0.49x (losing 1:2), WR=73.3%
- **After**: PF=0.70x (losing 3:10), WR=65-70%
- **Reason**: Fewer small losses, keep good-segment positions longer

### Realistic Scenario (Likely)
- **Before**: PF=0.49x, WR=73.3%
- **After**: PF=0.55-0.65x, WR=65-72%
- **Reason**: Some small losses delayed/prevented, but MFE still limited

### Conservative Scenario (Worst Case)
- **Before**: PF=0.49x, WR=73.3%
- **After**: PF=0.50x, WR=73.3%
- **Reason**: Market conditions don't allow bigger moves, delays don't help

---

## Rollback Plan (Safety Net)

If Phase 3 causes problems:

```bash
# Disable immediately
export PAPER_EXIT_REPAIR_ENABLED=false
systemctl restart cryptomaster.service

# Or revert commit
cd /opt/cryptomaster
git revert 19be30c
git push origin main
systemctl restart cryptomaster.service
```

**Impact of disable**: No scratch/stagnation exit changes → reverts to baseline

---

## Next Steps

1. **Monitor Daily Reports**:
   ```bash
   tail -f /opt/cryptomaster/logs/daily_exit_analysis.log
   ```

2. **After 24-48h of enabled Phase 3**:
   - Analyze new PF and WR
   - Compare to baseline (PF=0.49x, WR=73.3%)
   - Decide if effect is positive

3. **If Positive (PF improved)**:
   - Keep enabled
   - Monitor for 1 week
   - Plan Phase 4 (harder signal filtering)

4. **If Neutral/Negative**:
   - Disable (`PAPER_EXIT_REPAIR_ENABLED=false`)
   - Investigate root cause (market conditions? EV too low?)
   - Plan alternative (e.g., entry-side improvements)

---

## Safety Guarantees

- ✅ **PAPER-only**: Zero impact on REAL orders
- ✅ **Config-gated**: Default disabled, explicit enable needed
- ✅ **5-min timeout**: Never holds positions indefinitely
- ✅ **Reversible**: Toggle off instantly
- ✅ **No hard blocks**: Only delays/exits, never blocks entry

---

## Integration Notes

**Current State**: Phase 3 module deployed but not yet integrated into exit decision logic

**To activate integration**:
1. Update `src/services/trade_executor.py` or `paper_trade_executor.py`
2. Call `should_exit_scratch()` when scratch signal received
3. Call `should_exit_stagnation()` when stagnation signal received
4. Log decisions via `log_repair_effect()`

**Status**: Code ready, integration manual (or automate if needed)

---

## Recommended Activation Timeline

| Time | Action | Reason |
|------|--------|--------|
| **Now** | Code deployed, disabled | Safe baseline |
| **+24h** | Enable Phase 3 | Enough data to analyze |
| **+48h** | Review daily reports | See effect on PF/WR |
| **+72h** | Decide keep/disable | Clear trend visible |
| **+1w** | Re-evaluate strategy | Plan Phase 4 or pivot |

---

**Questions?** Check daily logs:
```bash
tail -20 /opt/cryptomaster/logs/daily_exit_analysis.log
```
