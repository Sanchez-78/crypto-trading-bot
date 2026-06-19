# CYCLE 29: Cost-Floor Investigation & TP Band Strategy

## CYCLE 28 FINDINGS

**Evidence:** Hold window shrink 600s → 300s had **ZERO EFFECT** on WR or exit distribution.

```
Baseline (600s):     WR=20.8%, Exit: 0% TP / 0% SL / 100% TO (53 trades)
After 30min (300s):  WR=20.8%, Exit: 0% TP / 0% SL / 100% TO (53 trades)
Conclusion: Problem is NOT hold window length
```

**What this means:**
- TP band (35bps) is unreachable at 300s, same as 600s
- 100% TIMEOUT persists regardless of hold window
- **ROOT CAUSE: TP band width vs actual market volatility (not hold window)**

---

## THE REAL PROBLEM: Cost Floor vs TP Zone Mismatch

### Current Configuration Analysis

**Assumed cost floor:** 15bps (fee) + 3bps (slippage) = **18bps total**

**Current TP band:** 35bps (0.35%)

**Net margin over cost:** 35 - 18 = **17bps**

**Market reality (from forensics):**
- Intra-600s avg volatility: ~18bps
- Intra-300s avg volatility: ~10bps (smaller window, fewer moves)
- Distribution: 0.00-0.39% (mostly sub-20bps)

**The math:**
```
For trade to be profitable:
  Price move (realized) > Cost floor (18bps) + Profit margin

Current situation:
  Market move available: ~18bps (avg)
  Cost floor: 18bps
  Profit margin: 0bps (break-even at best)
  TP band target: 35bps (2x the available move)
  
Result: IMPOSSIBLE to reach TP profitably on average
```

---

## CYCLE 29 STRATEGY: Two-Track Investigation

### TRACK A: Validate Actual Cost Floor (Empirical)

**Hypothesis:** Our 18bps cost floor estimate might be wrong. Real cost could be:
- Lower (10-15bps) if we're underestimating slippage
- Higher (20-25bps) if fees are steeper than modeled

**Investigation method:**
1. **Measure from closed trades:** Extract entry_price, exit_price, pnl from last 100 closed TIMEOUT trades
2. **Calculate effective cost:** `cost = (exit_price - entry_price) - pnl_realized`
3. **Distribution analysis:** Check median/p90 cost across symbols and time periods
4. **Compare:** vs modeled 18bps

**Expected outcomes:**
- **If actual cost < 15bps:** Can reduce TP floor to 25-28bps, recover profitability window
- **If actual cost = 18bps:** Need to accept tighter margins, focus on signal quality
- **If actual cost > 20bps:** Problem is worse than estimated; requires execution improvements

### TRACK B: TP Band Calibration Against Reality

**Given the constraint:** Cost floor + safety margin must be achievable in real market

**Option B1: Lower TP to match volatility**
```
Market intra-600s move: ~18bps
Cost floor: 18bps
→ TP=25bps (covers 25-18=7bps profit)
Risk: Extremely tight margin, high slippage sensitivity
```

**Option B2: Accept lower hit rate, widen SL**
```
TP=35bps (keep), SL=60bps (widen from 40)
Tradeoff: Lower TP hit rate, but SL becomes reachable earlier
Risk: Losses scale faster on wrong direction
```

**Option B3: Accept 20% WR baseline, focus on signal quality**
```
TP=35bps, SL=40bps, WR=20% (current)
Improve entry signal generation (Bayesian recalibration, better regime detection)
Risk: Signals don't improve; WR stays 20%
```

**Option B4: Hybrid - Dynamic TP with proper cost floor floor**
```
ATR-based TP but with CORRECT implementation:
  - Account for calibration override (refactor)
  - Use post-calibration TP (not pre-calibration)
  - Set floor based on measured cost floor (not hardcoded 35)
Difficulty: Requires code refactor + validation (like CYCLE 28 ATR patch, but correct)
```

---

## CYCLE 29 EXECUTION PLAN

### Phase 1: Cost Floor Measurement (Data-Driven)

**Objective:** Empirically validate 18bps cost floor estimate

**Steps:**
1. Query Firebase for last 100 TIMEOUT-closed trades
2. For each trade:
   - Entry price, exit price, realized P&L
   - Calculate: effective cost = entry - exit - pnl
   - Per-symbol breakdown (BTC/ETH/XRP/BNB/others)
3. Statistics: median, p90, distribution
4. Compare: measured cost vs 18bps model

**Deliverable:** Cost floor validation report (1 page)

**Time estimate:** 30 min (if Firebase accessible), else estimate from entry/exit spreads

### Phase 2: TP Band Decision (Cost-Aware)

**Gate:** "Is measured cost floor compatible with TP=35bps?"

**If yes (cost ≤ 28bps):**
- ✅ Current TP=35bps is viable
- Decision: Proceed to signal quality improvement (CYCLE 30+)
- Action: Keep TP, focus on Bayesian entry calibration

**If no (cost > 30bps):**
- ⚠️ TP=35bps leaves insufficient margin
- Decision: Choose B1, B2, or B4
- Action A (B1 - Lower TP): Set TP=25-28bps, deploy, 30-min test
- Action B (B2 - Widen SL): Set SL=50-60bps, deploy, 30-min test
- Action C (B4 - Refactor ATR): Full code review + calibration override fix, redeploy

### Phase 3: Deploy & Monitor (Cost-Aligned Config)

**Config selection:** Based on Phase 2 decision

**Deploy:** Env-var change (if B1/B2) or code patch (if B4)

**Monitor:** 30-60 min
- TP hit rate (should increase from 0% if viable)
- WR trajectory (expect 20% → 30%+ if cost-floor matched)
- Exit distribution shift (TP/SL vs TIMEOUT ratio)

**Gate:**
- WR ≥ 35% → ✅ Config sustainable, proceed CYCLE 30 (signal refinement)
- WR 20-35% → ⚠️ Marginal, evaluate if cost-floor is lower priority
- WR ≤ 20% → 🔴 Cost floor still blocking; escalate to execution improvements (slippage, fees)

---

## Timeline & Resource Requirements

| Phase | Task | Time | Blocker | Resource |
|-------|------|------|---------|----------|
| **1** | Cost floor measurement | 30 min | Firebase access | Runtime-forensic-agent |
| **2** | TP decision gate | 15 min | Phase 1 complete | Manual decision |
| **3** | Config deploy | 5 min (B1/B2) or 30 min (B4) | Phase 2 complete | Bash (B1/B2) or Evidence-orchestrator (B4) |
| **4** | 30-60 min monitor | 60 min | Phase 3 deploy | Live metrics polling |
| **5** | Final gate & report | 15 min | Phase 4 complete | Manual evaluation |

**Total elapsed time:** 2-3 hours (depending on Phase 3 choice)

---

## Success Criteria

✅ **CYCLE 29 SUCCESS:**
- [ ] Cost floor empirically measured (not guessed)
- [ ] TP band adjusted based on measured cost (not fixed 35bps)
- [ ] WR ≥ 30% achieved (or justified as accepted baseline)
- [ ] Next cycle (CYCLE 30) planned with clear signal-quality focus

❌ **CYCLE 29 FAILURE:**
- [ ] Cost floor ≥ 30bps (higher than expected, execution issue)
- [ ] WR stays < 20% (cost-floor incompatibility cannot be fixed by band sizing alone)
- [ ] No clear path to profitability visible

---

## Decision Framework (Today)

**Question:** Should we start CYCLE 29 now (cost floor measurement + TP band decision)?

**YES if:**
- Time available for 2-3 hour investigation (likely today)
- Want definitive answer on whether TP=35bps is viable
- Ready to make TP band change (or accept 20% WR baseline)

**NO if:**
- Time pressure; need faster decision
- Want to proceed directly to signal refinement (skip cost floor; accept 35bps as given)
- Prefer empirical testing (deploy multiple TP values, A/B test)

---

## CYCLE 29 GO/NO-GO

**Recommendation:** ✅ **PROCEED WITH CYCLE 29** (Cost Floor Investigation)

**Rationale:** 
- CYCLE 28 provided key evidence (hold window irrelevant)
- Cost floor is the **only remaining lever** for WR improvement before signal work
- 2-3 hour investment will either validate current config or unlock next improvement
- Risk: Low (only env-var changes for B1/B2, or deferred code patch for B4)
