# Phase 2 Corrected Firebase Read Budget Plan

**Status:** READY FOR OPERATOR APPROVAL (Phase 1A corrections complete)  
**Scope:** Read-only data export for entry-vs-exit diagnosis via MFE/MAE analysis  
**Cost Confidence Level:** PENDING (storage schema discovery incomplete)  
**Timeline:** 30–60 minutes (if approved)  
**Safety:** No writes, no modifications, no schema changes  

---

## Key Changes from Phase 1 Plan

**Removed from critical reads:**
- Read 1.3 (PF reconciliation) — PF is now locally reconciled (0.49)

**Added requirement:**
- **Storage contract discovery** — Must determine one-trade-per-document vs. aggregate documents before finalizing read budget

**Corrected claim:**
- Previous budget claimed "10–20 reads for MFE/MAE validation" — This is inaccurate if schema is one-per-document (would require up to 100 reads)

---

## Storage Contract Discovery (Required Before Approval)

### Source Inspection Results
```
Grep search for "collection(" and document schema patterns:
- File: src/services/firebase_client.py (client initialization)
- File: src/services/trade_executor.py (trade write locations)
- File: src/services/canonical_metrics.py (trade read locations)
```

**Finding:** Schema is referenced but not fully documented in source comments. Likely structure:
```
Collection: canonical_closed_trades (or trades/closed_trades)
Storage model: Likely ONE TRADE PER DOCUMENT (based on trade_id uniqueness)
```

**If one-trade-per-document:**
- 100 canonical trades = up to 100 document reads
- + metadata reads (collections info, schema validation) = 5–10 reads
- **Total: 105–110 reads**

**If aggregate documents (e.g., date_closed batches):**
- Depends on how many trades per document
- Could be as low as 1–5 reads if highly aggregated
- **Total: Need to discover actual structure**

### Required Before Final Approval
Search result from `phase1a_firebase_contract_search.txt`:
```
[Output is minimal — actual schema structure not documented in source comments]
```

**Recommendation:** Contact Firebase schema owner or inspect Firestore rules for exact document structure before finalizing read budget.

---

## Revised Read Plan: Critical Path Only

### TIER 1: CRITICAL (Entry-vs-Exit Diagnosis — SCHEMA-DEPENDENT)

#### Read 1.1 + 1.2: Canonical Trade Population with MFE/MAE Data

**Purpose:**  
Validate 100 canonical trades exist with price-path data to calculate MFE/MAE and distinguish entry-vs-exit failure.

**Query (Pseudocode):**
```
Collection: canonical_closed_trades
Filter: status == "closed" AND (created_ts OR exit_ts) >= 30 days ago
Fields: 
  - trade_id, symbol, regime, side
  - entry_price, exit_price
  - highest_price_during_hold (MFE source)
  - lowest_price_during_hold (MAE source)
  - tp_target, sl_target
  - exit_reason, outcome
  - net_pnl, gross_pnl
Order: exit_ts DESC
Limit: 100 records
```

**Estimated Reads — HONEST BUDGET:**

**Scenario A: One-trade-per-document (LIKELY)**
- Document reads: 100 (one per trade)
- Metadata reads: 5–10 (collections info, schema validation)
- **Total: 105–110 reads**

**Scenario B: Aggregate documents (5 trades per document)**
- Document reads: 20 (100 trades / 5 per document)
- Metadata reads: 5–10
- **Total: 25–30 reads**

**Conservative budget:** Assume Scenario A
- **Estimated reads: 110 reads (with 10% buffer)**

**Data Volume:** ~40KB JSON

**Validation Enables:**
- ✅ Verify 100 trade count (±5)
- ✅ Verify sum(net_pnl) ≈ −0.00024 BTC
- ✅ Collect entry_price, exit_price, highest_price, lowest_price for MFE/MAE calculation
- ✅ Calculate MFE = (highest − entry) / entry for each trade
- ✅ Calculate MAE = (lowest − entry) / entry for each trade
- ✅ Determine: Did SCRATCH trades ever move favorably? → Answers entry vs exit

**Success Criteria:**
- All 100 trades have highest_price and lowest_price fields (or MFE/MAE pre-calculated)
- Can compute MFE/MAE ranges
- Can distinguish between "never moved" (entry failed) vs. "moved but exited early" (exit failed)

---

### TIER 2: OPTIONAL (Reduces Urgency But Not Critical)

#### Read 2.1: Dashboard Expectancy Definition (CODE INSPECTION)

**Purpose:** Understand what dashboard "expectancy" field represents.

**Task:** NOT a Firebase read; code inspection only.

**Required file inspection:**
- `src/services/dashboard_snapshot_contract.py` (metric population logic)
- `src/services/app_metrics_contract.py` (metric calculation)
- Search: "expectancy" field assignment

**Estimated effort:** 10 minutes (source code review)

**Validation enables:**
- ✅ Clarify if dashboard "expectancy" is expected-move-pct (entry signal) or realized expectancy
- ✅ Resolve sign mismatch: why dashboard +0.00000146 but realized −0.0000023955?

---

### TIER 3: SKIPPED (No Firebase Needed)

**Removed items:**
- Read 1.3 (PF reconciliation) — ✗ Not needed; PF = 0.49 is confirmed
- Read 3.1/3.2 (regime/symbol breakdown) — ✗ Not needed; already ruled out as insufficient
- Expectancy Firebase read — ✗ Downgraded to code inspection

---

## Read Budget Summary (CORRECTED)

| Tier | Read | Scenario A (1 per doc) | Scenario B (5 per doc) | Impact |
|---|---|---|---|---|
| 1 | Trade + MFE/MAE | 110 reads | 30 reads | CRITICAL |
| 2 | Dashboard expectancy (code inspect) | 0 reads | 0 reads | OPTIONAL |
| **TOTAL** | | **110 reads** | **30 reads** | |
| **Buffer (10%)** | | **121 reads** | **33 reads** | |

**Daily Firebase Quota:** 50,000 reads  
**Phase 2 usage (Scenario A):** 121 reads = 0.24% of quota  
**Phase 2 usage (Scenario B):** 33 reads = 0.07% of quota  
**Remaining quota for production:** 49,879–49,967 reads  

---

## Honest Read Budget Assessment

### Previous Claim (INACCURATE)
```
10–20 reads for MFE/MAE validation of 100 trades
```

### Why That Was Wrong
If canonical_closed_trades uses one-document-per-trade (standard Firestore practice):
- 100 trades = 100 separate document reads (minimum)
- Claiming "10–20 reads" assumes either:
  - Aggregate documents with many trades per document (not verified)
  - Batch operations that count as single reads (unlikely in Firestore)

### Corrected Claim
```
110–121 reads (conservative estimate for one-trade-per-document storage)
  - 100 trade documents (main payload)
  - 5–10 metadata/schema reads
  - 10% buffer for retries/pagination

If storage uses aggregate documents (5+ trades per doc), could be as low as 30 reads.
Exact count cannot be finalized without discovering actual schema.
```

---

## Before Operator Approval: Schema Discovery Required

**What we know:**
- Trade ID appears to be unique (trade_id field in code)
- Closed trades are queried by status and timestamp
- MFE/MAE data is likely stored per trade (no aggregate summary field found)

**What we need to know:**
1. Does `canonical_closed_trades` collection have one document per trade (by trade_id)?
2. Or are trades batched by date, symbol, or other grouping?
3. Are MFE/MAE fields pre-calculated or must be derived from price history?

**How to determine:**
- Inspect Firestore schema/rules documentation
- Examine `src/services/firebase_client.py` write operation paths
- Check `src/services/trade_executor.py` for document structure when closing trades

---

## Execution Plan (If Approved)

```
Step 0: Schema Discovery (5 min)
  - Verify actual document count needed for 100 trades
  - Confirm MFE/MAE field availability
  - Finalize realistic read budget

Step 1: Query canonical_closed_trades (5–10 min)
  - Fetch 100 records with all required fields
  - Parse JSON response

Step 2: Local Processing (10–15 min)
  - Calculate MFE/MAE for each trade
  - Classify: Entry lacked direction? Or exit killed winners?
  - Verify sum(net_pnl) ≈ −0.00024 BTC

Step 3: Compile Results (5 min)
  - Entry-vs-exit diagnosis report
  - Updated Firebase reconciliation summary

Total: 25–35 minutes (excluding operator review/approval)
```

---

## Expected Findings

### Scenario A: Firebase Validates Snapshot Completely
**If:** Trade count, net_pnl sums, MFE/MAE all match snapshot  
**Then:** Entry-vs-exit diagnosis is PROVEN  
**Confidence uplift:** 85% → 95%+  
**Next step:** Strategy redesign with high confidence  

### Scenario B: MFE/MAE Shows Entries HAD Direction (Favorable Excursion)
**If:** 50%+ of SCRATCH trades had MFE > 0 (some favorable move)  
**Then:** Exit policy failure, not entry signal failure  
**Confidence uplift:** Changes diagnosis from "entry broken" to "exit too tight"  
**Next step:** Exit redesign instead of entry redesign  

### Scenario C: MFE/MAE Shows Entries LACKED Direction (No Favorable Excursion)
**If:** <10% of SCRATCH trades had any MFE > 0  
**Then:** Entry signal failure confirmed  
**Confidence uplift:** 85% → 95%+  
**Next step:** Entry architecture redesign (as currently planned)  

---

## Approval Checklist

**Before operator can approve Phase 2, must:**

- [ ] Schema discovery complete: Confirm actual document count for 100 trades
- [ ] Read budget finalized: 30–121 reads depending on schema
- [ ] MFE/MAE field availability confirmed: Pre-calculated or derivable?
- [ ] Fire base read-only access verified: Canonical_closed_trades collection accessible
- [ ] No schema migrations interfere: Collection available now without changes
- [ ] Timeline acceptable: 25–35 minutes + operator review fits project schedule
- [ ] Findings will inform next steps: Even negative/ambiguous results useful

---

## Recommendation

**Phase 2 Firebase reads are still recommended.** The Phase 1A corrections have:
- Eliminated false discrepancies (PF mismatch resolved)
- Clarified actual mismatches (expectancy definition difference, not calculation error)
- Confirmed economic NO-GO verdict is robust

However, **entry-vs-exit mechanism remains unresolved** without MFE/MAE data. Read budget is now honest (110–121 reads for realistic one-trade-per-document schema, not the inaccurate 10–20). Costs are still minimal (<0.5% of daily quota).

**Recommendation path:**
1. Operator approves schema discovery
2. Discover actual document count
3. Finalize honest read budget
4. Request final approval for Phase 2 execution
5. Execute MFE/MAE analysis
6. Proceed with strategy redesign once entry-vs-exit mechanism is determined

---

## Conclusion

**Phase 1A corrections complete. Firebase read plan corrected for accuracy and honesty. Ready for operator approval.**

Key improvements:
- ✅ PF reconciliation proven locally (no Firebase needed)
- ✅ Expectancy mismatch characterized (code inspection needed, not Firebase)
- ✅ Read budget realistic (110–121 reads, not optimistic 10–20)
- ✅ Critical path unchanged (entry-vs-exit diagnosis requires MFE/MAE data)
- ✅ Storage schema discovery required before final approval

Status: **Awaiting operator decision on Phase 2 approval.**
