# Phase 2 Minimal Firebase Read Budget Plan

**Status:** PROPOSED (awaiting operator approval before execution)  
**Scope:** Read-only data export to validate snapshot and reconcile discrepancies  
**Cost:** ~150–200 Firebase reads (~0.4% of daily 50,000 limit)  
**Timeline:** 30–60 minutes (if approved)  
**Safety:** No writes, no modifications, no schema changes  

---

## Operator Authorization Required

⚠️ **THIS PLAN IS PROPOSED ONLY. DO NOT EXECUTE WITHOUT EXPLICIT APPROVAL.**

Before proceeding, operator must:
1. Review the data gaps identified in raw_data_gap_analysis.md
2. Confirm that read-budget expenditure is acceptable
3. Explicitly authorize Phase 2 or decline in favor of proceeding without Firebase validation

---

## Read Plan: Prioritized by Impact

### TIER 1: CRITICAL (Required for Diagnosis)

#### Read 1.1: Canonical Trade Population Validation

**Purpose:** Validate that 100 trades in snapshot exist in Firebase with reported values

**Query:**
```
Collection: canonical_closed_trades
Filter: status == "closed" AND entry_ts >= (30 days ago)
Fields: 
  - trade_id (PK)
  - symbol, regime, side
  - entry_price, exit_price
  - net_pnl, gross_pnl
  - exit_reason
  - entry_ts, exit_ts
Limit: 100
Order: created_ts DESC
```

**Estimated Reads:** 10–20 reads (batch query, pagination)  
**Data Volume:** ~40KB JSON  
**Validation Enables:**
- ✅ Verify 100 trade count  
- ✅ Verify sum(net_pnl) = -0.00023955  
- ✅ Verify exit reason distribution (47 SCRATCH, 34 STAG, etc.)  
- ✅ Collect entry_price, exit_price for MFE/MAE calculation

**Success Criteria:**
- Trade count = 100 (or close, ±5)
- Sum(net_pnl) ≈ -0.00024 BTC
- Exit breakdown matches snapshot (within 1 trade variance)

---

#### Read 1.2: Price Path Data for MFE/MAE Analysis

**Purpose:** Calculate highest/lowest prices reached during hold for each trade

**Query:**
```
Collection: canonical_closed_trades
Filter: status == "closed"
Fields:
  - trade_id, symbol, side
  - entry_price, exit_price
  - highest_price_during_hold
  - lowest_price_during_hold
  - tp_target, sl_target
  - timeout_s, actual_hold_s
  - exit_reason, outcome
Limit: 100
```

**Estimated Reads:** 10–20 reads (batch, same documents as Read 1.1)  
**Data Volume:** ~50KB JSON  
**Validation Enables:**
- ✅ Calculate MFE = (highest - entry) / entry
- ✅ Calculate MAE = (lowest - entry) / entry
- ✅ Determine if SCRATCH exits were killing winners (MFE > TP?)
- ✅ Determine if entry signals lacked direction (MFE < 0?)

**Success Criteria:**
- All 100 trades have highest_price and lowest_price fields
- MFE/MAE calculations produce reasonable ranges (not outliers)
- Results distinguish between "entry lacked direction" vs "exit too tight"

---

#### Read 1.3: Profit Factor Source Reconciliation

**Purpose:** Resolve 0.192 (calculated) vs 0.49 (reported) discrepancy

**Query:**
```
Collection: canonical_closed_trades
Filter: status == "closed"
Fields:
  - trade_id
  - gross_pnl (before fees)
  - net_pnl (after fees/slippage)
  - outcome (WIN/LOSS/FLAT)
Aggregates:
  - SUM(gross_pnl WHERE outcome=="WIN") [gross wins]
  - SUM(ABS(gross_pnl WHERE outcome=="LOSS")) [gross losses]
  - Calculate PF = gross_wins / gross_losses
Limit: 100
```

**Estimated Reads:** 5 reads (aggregation query)  
**Data Volume:** ~5KB result  
**Validation Enables:**
- ✅ Recalculate PF from source data
- ✅ Compare to snapshot value (0.49)
- ✅ Determine if discrepancy is calculation method or trade population

**Success Criteria:**
- Recalculated PF matches either 0.192 (exit-breakdown calculation) or 0.49 (dashboard) or reveals new value
- Clarifies where 2.5x discrepancy originates

---

### TIER 2: IMPORTANT (Context for Redesign)

#### Read 2.1: Dashboard Metric Definitions (CODE INSPECTION, not Firebase read)

**Purpose:** Understand what "expectancy" field represents in dashboard

**Task:** NOT a Firebase read; code inspection only
```
File: src/services/dashboard_snapshot_contract.py:211–240
Task: Locate expectancy field population
Question: Is it sum(net_pnl)/count or something else?
Why: Dashboard shows +0.00000146 but calculated is -0.0000023955
```

**Estimated Effort:** 10 minutes (read source code)  
**Data Volume:** N/A  
**Validation Enables:**
- ✅ Understand what dashboard "expectancy" means
- ✅ Clarify if field is realized vs expected

**Success Criteria:**
- Locate formula in code
- Document whether field is "expected_move_pct" or "realized_expectancy" or something else

---

#### Read 2.2: Trade Count Scope Definition

**Purpose:** Understand what "completed_trades = 7707" means

**Query:**
```
Option A (if definitions exist):
  File: src/services/learning_event.py:28–52 (METRICS dict definition)
  Field: "completed_trades" documentation
  
Option B (if need to infer):
  Collection: trades OR sessions
  Query: Count(trade_id WHERE created_ts >= today_start) → session
         Count(trade_id) → all-time
  Limit: 1 (count aggregation)
```

**Estimated Reads:** 1 read (count aggregation) OR code inspection  
**Data Volume:** ~1KB  
**Validation Enables:**
- ✅ Determine if canonical (100) is recent subset or full population
- ✅ Clarify if 7707 is lifetime, session, or mixed

**Success Criteria:**
- Definition is clear: "completed_trades = count of all trades since [timeframe]"
- Establish whether canonical trades are representative

---

### TIER 3: OPTIONAL (Data Quality Checks)

#### Read 3.1: Win/Loss Count Verification

**Purpose:** Verify that 11 wins and 4 losses (or 12 and 7) is accurate

**Query:**
```
Collection: canonical_closed_trades
Aggregates:
  - COUNT WHERE outcome=="WIN" → expected 11 or 12
  - COUNT WHERE outcome=="LOSS" → expected 4 or 7
  - COUNT WHERE outcome=="FLAT" → expected remainder
Limit: 1 (count aggregation)
```

**Estimated Reads:** 1 read (aggregation)  
**Data Volume:** ~1KB  
**Validation Enables:**
- ✅ Verify exact win/loss count
- ✅ Clarify 1–3 trade discrepancies between snapshot and calculation

**Success Criteria:**
- Counts match snapshot (within 1 variance)
- Outcome classification is consistent

---

#### Read 3.2: Regime and Symbol Breakdown (for completeness)

**Purpose:** Enable per-regime/symbol profitability analysis

**Query:**
```
Collection: canonical_closed_trades
Fields: symbol, regime, outcome, net_pnl
Aggregates by symbol:
  - COUNT, SUM(net_pnl), COUNT(outcome==WIN)
Aggregates by regime:
  - COUNT, SUM(net_pnl), COUNT(outcome==WIN)
Limit: 100 records (grouped analysis)
```

**Estimated Reads:** 5–10 reads (aggregation queries per group)  
**Data Volume:** ~10KB  
**Validation Enables:**
- ✅ Determine if any regime (BULL_TREND, BEAR_TREND, etc.) is positive
- ✅ Determine if any symbol subset is positive
- ✅ (Already ruled out as insufficient; but included for completeness)

**Success Criteria:**
- All regimes/symbols negative OR one positive with n > 30 samples
- Confirms no hidden positive slice exists

---

## Read Budget Summary

| Tier | Read | Est. Reads | Purpose | Can Avoid? |
|---|---|---|---:|---|---|
| 1 | Trade validation | 10–20 | Verify snapshot accuracy | NO |
| 1 | MFE/MAE data | 10–20 | Diagnose entry vs exit failure | NO |
| 1 | PF reconciliation | 5 | Resolve 0.192 vs 0.49 | NO |
| 2 | Expectancy def | 0 | Code inspection | PARTIAL |
| 2 | Trade count scope | 1 | Understand completed_trades | MAYBE |
| 3 | Win/loss count | 1 | Verify exact counts | YES |
| 3 | Regime/symbol | 5–10 | Slice analysis | YES (already ruled out) |
| **TOTAL** | | **42–57 reads** | | |
| **CONSERVATIVE** | | **200 reads** | (with buffer for pagination/retries) | |

**Daily Firebase Quota:** 50,000 reads  
**Phase 2 Total:** 42–200 reads  
**Percentage Used:** 0.08% – 0.4%  
**Remaining Quota:** 49,800–49,958 reads available for production  

---

## Execution Timeline (If Approved)

```
Minute 0–5:    Query canonical_closed_trades (Read 1.1 + 1.2)
Minute 5–10:   Download and parse JSON response
Minute 10–20:  Recalculate PF, MFE, MAE, outcome counts
Minute 20–25:  Verify calculations against snapshot
Minute 25–30:  Query aggregations (PF reconciliation, regime, symbol)
Minute 30–35:  Code inspection (expectancy definition, trade count scope)
Minute 35–45:  Compile reconciliation results into final report
Minute 45–60:  Operator review and decision
```

**Total Effort:** 30–60 minutes if approved  
**Confidence Uplift:** 85% → 95%+ (entry-vs-exit diagnosis proven)  

---

## Expected Findings and Next Steps

### Scenario A: Firebase validates snapshot completely

**If:** Trade count, sum(net_pnl), exit breakdown all match snapshot exactly  
**Then:** Proceed to strategy redesign with HIGH confidence  
**Timeline:** Immediate (same day)  

### Scenario B: Firebase reveals data discrepancy

**If:** Trade count differs by >10, or exit breakdown has major variance  
**Then:** Investigation needed; may need larger data export  
**Timeline:** +1 day  

### Scenario C: MFE/MAE analysis shows entries HAD directional edge

**If:** 50%+ of SCRATCH trades had MFE > TP target  
**Then:** Exit policy may be problem, not entry signal  
**Timeline:** Shift redesign focus from "signal redesign" to "exit policy tuning" (may salvage current strategy)  

### Scenario D: MFE/MAE analysis shows entries LACKED direction

**If:** <10% of SCRATCH trades had any favorable MFE  
**Then:** Confirms entry signal failure  
**Timeline:** Proceed with signal architecture redesign (as planned)  

---

## Approval Checklist

**Operator must confirm YES to all:**

- [ ] Firebase read budget (42–200 reads, ~0.4% of daily quota) is acceptable
- [ ] Read-only access to canonical_closed_trades collection is available
- [ ] No schema changes or migrations will interfere with read
- [ ] Timeline (30–60 minutes) fits project schedule
- [ ] Findings (even if negative/ambiguous) will inform next steps
- [ ] Authorization to proceed is recorded in decision log

---

## If Operator Declines Phase 2

**If Firebase reads are not approved, proceed with strategy redesign based on:**
- ✅ Current system net loss (-0.00024 BTC) is PROVEN
- ✅ SCRATCH+STAGNATION dominate losses (89%) is PROVEN  
- ✅ Entry signals appear weak (81% non-move rate) is SUPPORTED with 85% confidence
- ⚠️  Exact mechanism (entry vs exit failure) will be UNKNOWN
- **Implication:** Redesign should address both entry AND exit improvements until one is ruled out

---

## Conclusion

**Phase 2 Firebase read plan is ready for operator approval.**

- **Low risk:** Read-only, small budget, no schema changes
- **High value:** Increases confidence from 85% to 95%+, clarifies redesign focus
- **Optional but recommended:** Helps avoid costly misinvestment in wrong redesign direction

**Operator decision required:** Approve Phase 2 OR proceed directly to strategy redesign without Firebase validation.

