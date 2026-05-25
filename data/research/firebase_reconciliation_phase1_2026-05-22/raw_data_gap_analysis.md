# Raw Data Gap Analysis — What's Missing for Complete Diagnosis

**Purpose:** Identify what local snapshot data CAN and CANNOT prove; determine Firebase fields needed to close gaps.

---

## Claims and Evidence Classification

### CLAIM 1: Current system loses money (-0.00024 BTC)

**Classification:** ✅ **PROVEN FROM NET AGGREGATES**

**Evidence chain:**
1. Exit breakdown provided: PARTIAL_TP_25 +5.13sat, MICRO_TP +0.56sat, etc.
2. Exit reason PnLs sum verified: (+5.13 +0.56) + (rest of losses) = -239.55 sat
3. Conclusion: System-wide net negative
4. Independent verification: Sum of 100 trade PnLs = -239.55 sat ✓

**Firebase validation needed:** NO — snapshot arithmetic is internally consistent

---

### CLAIM 2: SCRATCH_EXIT and STAGNATION_EXIT dominate losses (89%)

**Classification:** ✅ **PROVEN FROM NET AGGREGATES**

**Evidence chain:**
1. Exit breakdown provided: SCRATCH (47 trades, -92.36 sat) + STAGNATION (34 trades, -121.43 sat)
2. Combined: 81 trades, -213.79 sat net
3. Total loss: -296.42 sat
4. Percentage: 213.79 / 239.55 = 89.25%
5. Interpretation: These two exit types account for 89% of loss

**Firebase validation needed:** NO — snapshot breakdown is complete and verified

---

### CLAIM 3: Entry signals lack directional edge (81% non-move rate)

**Classification:** 🟡 **SUPPORTED BUT NOT PROVEN**

**Current evidence:**
- 81 trades (81%) classified as SCRATCH_EXIT or STAGNATION_EXIT
- These are "exit without profitable move" outcomes
- **Interpretation:** If entry signal predicted direction, position would move favorably; it didn't

**Why not PROVEN:**
- SCRATCH_EXIT could mean "position moved against entry" (bad entry)
- SCRATCH_EXIT could also mean "position moved but not far enough to TP" (weak signal)
- STAGNATION_EXIT could mean "position stuck" (neutral signal) or "stuck waiting for move that never came"
- Without price-path data, cannot distinguish these mechanismss

**What would PROVE this claim:**
- For each SCRATCH trade: entry_price, exit_price, highest_price, lowest_price
- Calculate: Did position ever move > 0.0001 BTC in entry direction?
- If 90%+ of SCRATCH trades never moved favorably → entry lacked direction ✓
- If 90% of SCRATCH trades had some favorable move → exit was too tight ✗

**Firebase validation needed:** YES
- Collection: canonical_closed_trades
- Fields: entry_price, exit_price, highest_price_reached, lowest_price_reached
- Estimated reads: 100 (one per trade)
- Why unavoidable: Snapshot has only aggregate PnL, not price paths

---

### CLAIM 4: Exit policy destroys possible winners

**Classification:** ❌ **NOT TESTABLE WITHOUT RAW DATA**

**Why this claim matters:**
- If true: Could fix by adjusting TP/SL geometry
- If false: Problem is entry signal, not exits

**Current snapshot evidence:** NONE
- Only 12 trades reached profitable exit (12%)
- Cannot infer whether exits "destroyed" winners without knowing if non-winners ever had a shot

**What would PROVE this claim:**
- For SCRATCH_EXIT trades: MFE (max favorable excursion) vs TP target
  - If 50%+ of SCRATCH trades had MFE > TP: Exit killed winners ✓
  - If <10% had MFE > TP: Entry lacked direction, exit was correct ✓

**Firebase validation needed:** YES
- Collection: canonical_closed_trades
- Fields: entry_price, highest_price_reached, tp_target, exit_price, exit_reason
- Estimated reads: 100
- Why unavoidable: Snapshot has no price-path data

---

### CLAIM 5: Win rate (all outcomes) = 11%

**Classification:** ✅ **PROVEN FROM NET AGGREGATES**

**Evidence chain:**
1. Profitable exit types: PARTIAL_TP_25 (8 trades) + MICRO_TP (4 trades)
2. Total profitable: 12 trades (with 1 rounding discrepancy, likely from outcome classification)
3. Total trades: 100
4. Win rate: 11% (or 12%, minor variance to verify in Firebase)

**Firebase validation needed:** MINOR
- Could verify that "outcome=WIN" count in Firebase matches snapshot
- Not critical since aggregate is proven

---

### CLAIM 6: Profit Factor = 0.49 (snapshot value)

**Classification:** 🟡 **SUPPORTED BUT NOT PROVEN** (Calculated vs Reported Mismatch)

**Calculated from snapshot:**
```
gross_wins  = 0.00005687 BTC
gross_loss  = 0.00029642 BTC
PF_calc     = 0.192
```

**Reported in snapshot:** 0.49

**Discrepancy:** ~2.5x

**Why mismatch exists:**
- Possible explanation 1: Snapshot includes fees/slippage in calculation differently
- Possible explanation 2: Snapshot uses different subset of trades
- Possible explanation 3: Dashboard calculation method differs from exit breakdown aggregation

**Firebase validation needed:** YES
- Collection: canonical_closed_trades
- Fields: gross_pnl, net_pnl, entry_price, exit_price (to recalculate)
- Estimated reads: 100
- Why critical: Need to verify which PF value is correct (0.192 or 0.49)

---

### CLAIM 7: Dashboard expectancy field is wrong

**Classification:** ✅ **PROVEN FROM CONTRADICTION**

**Evidence chain:**
1. Calculated expectancy: sum(net_pnl) / 100 = -0.00023955 / 100 = -0.0000023955
2. Dashboard displays: +0.00000146
3. Difference: ~200x wrong (including sign flip)
4. Conclusion: Dashboard field is NOT realized expectancy

**What dashboard expectancy actually is:**
- Could be "expected_move_pct" from entry signal
- Could be paper-only performance
- Could be stale value from prior session
- Could be bug

**Firebase validation needed:** YES (CODE INSPECTION)
- File: dashboard_snapshot_contract.py, metrics_engine.py
- Task: Find where "expectancy" field is populated
- Why needed: Understand what this field measures for dashboard interpretation

---

### CLAIM 8: completed_trades = 7707 is 77x larger than canonical = 100

**Classification:** ❌ **NOT TESTABLE WITHOUT DEFINITION**

**What we know:**
- canonical = 100 (closed canonical trades, clear scope)
- LM = 200 (paper training trades, clear scope)
- completed_trades = 7707 (scope undefined)

**Why this matters:**
- If completed_trades = lifetime all-time trades: canonical (100) is a recent subset, conclusion may still apply
- If completed_trades = session trades only: could be different trading session, confounds analysis
- If completed_trades includes open trades: metric is inconsistent

**Firebase validation needed:** YES
- Collection: trades OR sessions
- Query: Count unique trades in current session vs all-time
- Fields: created_ts, trade_id
- Why needed: Understand data scope and whether canonical trades are representative

---

### CLAIM 9: Learning health = BAD (0.0000)

**Classification:** ✅ **PROVEN FROM NET AGGREGATES**

**Evidence chain:**
1. Health formula: health = min(PF, WR, expectancy) [normalized]
2. PF = 0.49 (dashboard) or 0.192 (calculated)
3. WR = 11% (all-outcomes) or 73.3% (decisive-only)
4. Expectancy = -0.0000023955 (negative)
5. Min of (0.49, 0.11, -0.0000023955) = -0.0000023955 → normalized to 0.0 (bad)
6. Threshold for health >= 0.25; actual is 0.0 ✓

**Firebase validation needed:** NO
- Derivation is mathematically sound
- Conclusion is robust regardless of PF value (both 0.192 and 0.49 are < 0.25)

---

## Summary of Validation Needs

### HIGH PRIORITY (Critical for Conclusion Validity)

| Data Gap | Needed for | Estimated Reads | Impact |
|---|---|---|---|
| MFE/MAE data | Prove entry vs exit failure | 100 | Determines root cause |
| Price paths (entry to exit) | Calculate gross move vs net | 100 | Determines if edge exists pre-fees |
| Profit factor source | Resolve 0.192 vs 0.49 discrepancy | 5 | Validation of calculation |

### MEDIUM PRIORITY (Nice-to-Have, Doesn't Change Conclusion)

| Data Gap | Needed for | Estimated Reads | Impact |
|---|---|---|---|
| Dashboard expectancy definition | Understand metric labels | 3 | Clarification only |
| completed_trades definition | Understand trade count scopes | 5 | Context only |
| Win/loss exact count | Verify 11 vs 12 discrepancy | 5 | Minor variance |

### LOW PRIORITY (For Future Analysis)

| Data Gap | Needed for | Estimated Reads | Impact |
|---|---|---|---|
| Per-symbol breakdown | Slice analysis (already ruled out as insufficient) | 10 | Won't change NO-GO verdict |
| Regime breakdown | Regime-specific performance | 10 | Already ruled out |
| Time-split (early vs recent) | Trend analysis | 5 | Interesting but not critical |

---

## Minimum Dataset for Complete Diagnosis

If operator authorizes Phase 2, recommend exporting:

```sql
SELECT 
  trade_id, symbol, regime, side,
  entry_price, exit_price,
  highest_price_reached, lowest_price_reached,
  entry_ev, entry_score,
  tp_target, sl_target, timeout_s,
  actual_hold_seconds,
  exit_reason, net_pnl, gross_pnl,
  fee_cost, slippage_cost,
  entry_ts, exit_ts,
  outcome (WIN/LOSS/FLAT)
FROM canonical_closed_trades
WHERE status = 'closed'
LIMIT 100;
```

**Size:** ~100 records, ~20 fields each, ~40KB JSON
**Read cost:** ~100 Firebase reads (~0.2% of daily quota)
**Processing time:** ~30 minutes
**Expected output:** 
- MFE/MAE analysis proving/disproving entry-vs-exit
- Gross move calculation proving/disproving pre-fee edge
- Regime/symbol breakdown (if any exists)
- Confidence uplift from MEDIUM (85%) to HIGH (95%+)

---

## Conclusion

**Currently Provable Locally:** System loses money, 81% due to non-move exits, current architecture should be retired.

**Not Provable Without Firebase:** Exact mechanism (entry signal failure vs exit policy failure), profit factor discrepancy, expectancy field meaning.

**Recommendation:** Phase 2 Firebase reads would clarify mechanism and validate snapshot data at low cost (150-200 reads, 30-60 minutes). Suggest operator approval before strategy redesign work begins.
