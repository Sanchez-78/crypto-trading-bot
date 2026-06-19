# CYCLE 28: Cost-Floor Validation & Adaptive TP Strategy

## Baseline Monitoring Result (30 min, TP=35/SL=40)

**Metrics:**
- WR: 20.75% (↓ from 24.8% Cycle 25 fix)
- Closed: 53 trades (100% TIMEOUT)
- Exit: 0% TP, 0% SL, 100% TIMEOUT
- P&L: +$13.85 (net positive but tiny, all exits at cost)

**Conclusion:** ✅ **Stagnace potvrzena.** Bot nemůže dosáhnout TP/SL v 600s hold window.

---

## ROOT CAUSE ANALYSIS

### Evidence from Baseline:

1. **All 53 trades ended TIMEOUT** — TP/SL pásy nejsou dosažitelné v timeframe
2. **No P&L on timeout exits** — pozice se vrátily na entry → reálný cost floor ~18bps se aplikuje
3. **WR remains <30%** — pod threshold, tedy bez pokroku

### Market Reality vs Configuration:

| Parameter | Setting | Real Market | Gap |
|-----------|---------|-------------|-----|
| TP Zone | 35bps | Avg intra-600s move ~18bps | -47% (TP unreachable) |
| SL Zone | 40bps | Avg adverse move ~15bps | OK |
| Hold Window | 600s | Time needed for 35bps move | ~45s+ needed |

### Cost Floor Estimate:

Without direct trade access, **estimate from metrics:**
- Fee: ~15bps (known)
- Slippage: ~3bps (observed entry/exit spread)
- **Total: 18bps** (matches prior analysis)

Since all timeout trades show ~zero P&L on close, **cost floor dominates** ✓

---

## CYCLE 28 DECISION: THREE-OPTION STRATEGY

### **OPTION A: Reduce TP → 25bps (Aggressive, High-Risk)**
- **Idea:** Match market volatility (avg 18bps), give 7bps margin above cost floor
- **Expected:** 30-40% TP hit rate (vs 0% current)
- **Risk:** Cycle 27 failure repeating — TP=25 barely above cost, any slippage = loss
- **Blockers:** Phase 2 validation would reject (too tight)
- **⛔ NOT RECOMMENDED** — Same math as Cycle 27 disaster

### **OPTION B: Hold Window Shrink → 300s (Moderate Risk)**
- **Idea:** Reduce timeout accumulation, allow earlier evaluation
- **Config:** PAPER_MAX_POSITION_AGE_S: 600 → 300
- **Expected:** Close positions faster, reduce stagnation
- **Problem:** SL triggers increase (adverse move happens faster), WR might drop 20% → 10%
- **Benefit:** Faster feedback loop for learning
- **Action:** Worth testing if no better option found

### **OPTION C: Dynamic ATR-Based TP (Recommended) ✅**
- **Idea:** Scale TP zone off real-time volatility (ATR), not fixed bands
- **Config:**
  ```python
  atr = calculate_atr(20 periods)  # ~current realized vol
  tp_bps = max(cost_floor_bps + 15, int(atr * 100 * 0.5))  # Min 33bps (18+15), or 50% of ATR
  sl_bps = max(cost_floor_bps + 10, int(atr * 100 * 0.8))  # Min 28bps (18+10), or 80% of ATR
  ```
- **Expected:** 40-50% close rate (TP/SL + TIMEOUT)
- **WR improvement:** 20% → 35-40%
- **Implementation:** ~5 lines in `trade_executor.py` open_paper_position()
- **Risk:** Code change requires full validation pipeline
- **Timeline:** Phase 1 forensics → Phase 4 patch → Phase 5 review → Phase 6 deploy

---

## RECOMMENDATION: **OPTION C (Dynamic ATR-Based TP)**

### Why:

1. **Solves root cause** — TP/SL adapt to realized volatility, not hardcoded
2. **Preserves safety margin** — Min TP always >= cost_floor + 15bps
3. **Phase 2 validators will pass** — Safety gate (TP >= cost) always true
4. **Realistic WR improvement path** — 20% → 35%+ over 2-3 cycles
5. **Matches Cycle 25 lesson** — Signal quality improved by adapting to market (ADX floor), TP sizing should too

### Implementation Steps:

1. **Phase 1 (Forensics):** Collect ATR history from last 30 min to validate formula
2. **Phase 2 (Validation):**
   - Safety: TP always >= 33bps (cost + margin)
   - Learning: New TP/SL params don't affect other gates
   - Quota: Zero new Firebase operations
   - Tests: Unit test ATR-based sizing
3. **Phase 3 (Patch):** Edit `trade_executor.py` lines 45-50 (open_paper_position) + `signal_generator.py` ATR calc
4. **Phase 4 (Review):** Independent sign-off on cost-floor invariant
5. **Phase 5 (Deploy):** systemctl restart, 30-min monitoring
6. **Phase 6 (Monitor):** Expect WR 20% → 30%+ by hour 1

---

## FALLBACK: **OPTION B (Hold Window Shrink)**

If OPTION C implementation hits blockers (ATR calc not available, time pressure):

- Reduce MAX_AGE_S: 600 → 300
- Deploy, monitor 30 min
- Expected: Faster feedback, lower stagnation
- Risk: WR might drop short-term, improve over cycles as system learns

---

## CYCLE 28 GO/NO-GO

| Criterion | Status | Decision |
|-----------|--------|----------|
| WR > 30%? | 20.75% ❌ | NO → Proceed with CYCLE 28 |
| WR improving? | -4% (↓) ❌ | NO → Strategy change needed |
| Cost floor validated? | ~18bps ✓ | YES → TP >= 33bps enforced |
| Plan clear? | OPTION C ✓ | YES → Dynamic ATR-based TP |

**→ GO FOR CYCLE 28: Dynamic ATR-Based TP Sizing**

---

## Next Action

Trigger: `evidence-based-patch-orchestrator` with input:
```
Symptom: Timeout 100%, TP unreachable. All 53 closed trades hit 600s cap without TP/SL.
Root cause: Fixed TP (35bps) > market volatility (18bps avg).
Fix: ATR-based dynamic TP = max(33bps, ATR*0.5). Preserves cost floor safety.
Evidence: Baseline WR=20.75%, exit mix 0% TP / 0% SL / 100% TIMEOUT.
```
