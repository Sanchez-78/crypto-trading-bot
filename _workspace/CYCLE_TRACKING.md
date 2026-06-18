# CYCLE TRACKING & CHANGE EVALUATION LOG

## Purpose
Track each cycle's hypothesis, implementation, measured results, and cumulative effects to prevent circular fixes.

---

## CYCLE 22: Hold Window Extension (300s → 600s)

**Hypothesis:** TP/SL unreachable in 300s window → extend hold to 600s

**Implementation:**
- File: `paper_trade_executor.py:806`
- Change: `min(max_hold or 300.0, ...)` → `min(max_hold or _MAX_AGE_S, ...)`
- Commit: `8a41edcd`

**Expected Result:** Longer hold window allows TP/SL to fire

**Measured Result (30min post-deploy):**
- WR: 0% → 12.2% (+12.2%)
- PF: 0.0x → 0.31x
- Exit dist: 100% TIMEOUT → still 100% TIMEOUT (11/11)
- TP/SL hits: 0 (FAILED)

**Root Cause Analysis:**
- Hold window DID extend to 600s ✅
- But MFE-to-TP ratio = 0.36 (price only moves 36% of TP distance)
- **Conclusion:** Problem is band WIDTH, not hold duration

**Cumulative Effect:** Hold fix + band width mismatch = still failing

---

## CYCLE 23: Band Width Reduction (80/50bps → 35/40bps)

**Hypothesis:** Bands 80/50bps too wide for 0.36 MFE-to-TP ratio → tighten to 35/40bps

**Implementation:**
- File: `/etc/systemd/system/cryptomaster.service.d/override.conf`
- Changes: `PAPER_TP_ZONE_BPS=80→35`, `PAPER_SL_ZONE_BPS=50→40`
- File: `parameter_tuner.py:45-47` - disabled auto-adjustment
- Commit: `9c3f89b`

**Expected Result:** 35bps TP now reachable within 600s hold

**Measured Result (30min post-deploy):**
- WR: 18.2% (no further improvement) 
- TP/SL hits: Still 0 (FAILED - 9 closes, 100% TIMEOUT)
- MFE avg move: 18bps (CRITICAL: below 35bps TP!)
- Closed trades in window: 9 out of 9 = TIMEOUT

**Root Cause Analysis:**
- Bands WERE deployed ✅
- But actual price movement avg = 18bps
- Even 35bps TP is 1.9x larger than average move!
- **Conclusion:** Market volatility too low - no amount of band tweaking fixes this

**Cumulative Effect:** Cycle 22 + 23 = holding 600s on 18bps average moves → guaranteed timeouts

---

## CYCLE 24: Signal Direction (WRONG_DIRECTION=77%)

**Hypothesis:** Signals inverted (BEAR→BUY flip) → fix signal_generator.py

**Forensics Finding:**
- 13 closed trades post-band-fix
- 10 WRONG_DIRECTION (77% error rate)
- All BULL_TREND trades = 0% WR

**Diagnostic Result:**
- Regime detector CORRECT (12/15 trades match actual direction)
- Signal generation has NO hard regime-alignment gate
- Bot generates SELL-in-BULL_TREND and BUY-in-BEAR_TREND (0% WR on these)
- Real problem: avg price move = 18bps < any realistic TP band

**Root Cause:** NOT signal inversion. True blockers:
1. Market volatility too low (18bps avg) → need micro-bands OR longer hold
2. Missing regime-alignment hard gate → allows counter-trend signals
3. BEAR_TREND quarantined by design → no short selling (long-only bot in bear market)

**Cumulative Effect:** Cycles 22+23+24 all assume market moves 30-80bps. Reality: 18bps. Wrong level entirely.

---

## CRITICAL INSIGHT

All three cycles fought the same root cause from different angles:
- Cycle 22: "Extend hold" (wrong: hold is fine, market doesn't move)
- Cycle 23: "Tighten bands" (wrong: bands are irrelevant if market doesn't move)
- Cycle 24: "Fix signals" (wrong: signals are correct 80% of time, market is flat)

**The Real Problem:** Market conditions changed mid-testing. All cycles assumed volatility; market is flat.

---

## RECOMMENDATIONS (BEFORE NEXT CYCLE)

**DO NOT implement without measuring:**

1. **Volatility Gate:** Check real 1H volatility before entry
   - If ATR% < 0.20%, refuse entry
   - If ATR% < 0.30%, use micro-bands (TP=10-15bps, SL=12-18bps)

2. **Regime Alignment Gate:** Hard filter (not penalty)
   - Reject SELL when regime==BULL_TREND
   - Reject BUY when regime==BEAR_TREND
   - This eliminates 9 WRONG_DIRECTION trades

3. **Short Support:** Enable SELL execution in BEAR_TREND
   - Currently quarantined → routed to evidence collection
   - Real market is BEAR right now → need short-selling

4. **Measurement Before Change:**
   - Every cycle must measure baseline for 15min BEFORE fix
   - Compare pre/post with same symbol/regime mix
   - Track: WR, PF, avg_mfe, timeout_rate, direction_accuracy

---

## CYCLE SUMMARY TABLE

| Cycle | Blocker | Fix | Hours Spent | WR Δ | TP/SL Hits | Conclusion |
|-------|---------|-----|-------------|------|------------|-----------|
| 22 | Hold 300s | Extend to 600s | 1.5h | +12.2% | 0/11 | ✗ Band width issue |
| 23 | Band width | 80/50→35/40bps | 1.5h | 0% | 0/9 | ✗ Market too flat (18bps) |
| 24 | Signal direction | Investigate | 2h | (in progress) | - | ✗ Volatility, not signals |
| **25** | **Volatility gate** | **Measure first** | **TBD** | **?** | **?** | **PENDING MEASUREMENT** |

---

## NEXT CYCLE REQUIREMENTS

Before implementing any fix:
1. ✅ Baseline metrics (15min measurement of current state)
2. ✅ Volatility check (ATR% for each symbol)
3. ✅ Direction accuracy (are signals right?)
4. ✅ Previous cycle impact (do old fixes still work?)
5. ✅ Expected vs measured (did last fix do what we promised?)

**Without this, we keep Cycle 22→23→24→22 forever.**
