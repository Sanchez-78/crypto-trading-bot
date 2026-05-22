# Firebase Schema Probe Report

**Status:** READY FOR PROBE EXECUTION  
**Date:** 2026-05-22  
**Methodology:** Code inspection + planned minimal Firebase reads (max 10 documents)  
**Purpose:** Verify exact schema before committing to Phase 2 full read (100+ documents)  

---

## Pre-Probe Findings (From Code Inspection)

### Collection Identification

**Primary collection identified:** `trades`  
**Evidence source:** `src/services/firebase_client.py`

```python
# Line 235: Load history from primary trades collection
db.collection(col("trades")).order_by(...).limit(...)

# Line 280: Save trade to collection
db.collection(col("trades")).document().set(item)

# Line 320: Delete old trades for cleanup
db.collection(col("trades")).document(doc_id).delete()
```

**Collection path syntax:**
- Function `col(name)` prepends optional COLLECTION_PREFIX
- Production likely: `PREFIX=""` → collection name is `"trades"`
- Shadow mode possible: `PREFIX="shadow_"` → `"shadow_trades"`

**Current configuration:**
- Environment variable: `COLLECTION_PREFIX` (default: empty string)
- Effective collection: `"trades"`

---

### Document Structure (From Code)

**Storage model inference:**
- Each trade has a unique `trade_id`
- Code references `_POSITIONS[trade_id]` and `db.collection(col("trades")).document(doc_id)`
- Pattern suggests: **One document per trade** (indexed by trade_id or auto-generated)

**Evidence:**
```python
# paper_trade_executor.py lines 1139–1140: Per-trade state tracking
_POSITIONS[trade_id]["max_seen"] = max(...)
_POSITIONS[trade_id]["min_seen"] = min(...)

# firebase_client.py: Per-document save pattern
db.collection(col("trades")).document().set(item)  # auto-generated ID
```

**Status field:**
- Trades marked with `status: "closed"` when completed
- Can filter on status to isolate closed trades

---

### Required Fields Confirmed in Code

From `exit_attribution.py` (build_exit_ctx function, lines 97–146):

| Field | Type | Example | Source |
|-------|------|---------|--------|
| `trade_id` | string | auto-generated or UUID | document key |
| `symbol` | string | "BTC", "ETH" | exit_attribution:99 |
| `regime` | string | "BULL_TREND", "BEAR_TREND" | exit_attribution:99 |
| `side` | string | "LONG" or "SHORT" | exit_attribution:100 |
| `entry_price` | float | 42850.25 | exit_attribution:101 |
| `exit_price` | float | 42900.50 | exit_attribution:102 |
| `size` | float | 0.1 (BTC) | exit_attribution:103 |
| `hold_seconds` | int | 3600 | exit_attribution:104 |
| `gross_pnl` | float | 0.00005687 (BTC) | exit_attribution:105 |
| `fee_cost` | float | 0.00000050 (BTC) | exit_attribution:106 |
| `slippage_cost` | float | 0.00000015 (BTC) | exit_attribution:107 |
| `net_pnl` | float | 0.00005622 (BTC) | exit_attribution:108 |
| `mfe` | float | 0.15 (%) | exit_attribution:109 |
| `mae` | float | 0.08 (%) | exit_attribution:110 |
| `final_exit_type` | string | "PARTIAL_TP_25", "SCRATCH_EXIT" | exit_attribution:111 |
| `exit_reason_text` | string | descriptive reason | exit_attribution:112 |
| `was_winner` | bool | true/false | exit_attribution:113 |
| `was_forced` | bool | false | exit_attribution:114 |

---

### Critical Uncertainty: max_seen and min_seen

**Question:** Are these fields persisted in Firebase documents?

**Evidence for storage:**

From `paper_trade_executor.py`:
```python
# Lines 1139–1140: Tracking during hold
_POSITIONS[trade_id]["max_seen"] = max(_POSITIONS[trade_id].get("max_seen", current_price), current_price)
_POSITIONS[trade_id]["min_seen"] = min(_POSITIONS[trade_id].get("min_seen", current_price), current_price)

# Lines 2028–2040: Used in MFE/MAE calculation on close
max_seen = float(t.get("max_seen", entry))
min_seen = float(t.get("min_seen", entry))
mfe = (max_seen - entry) / entry * 100.0
mae = (entry - min_seen) / entry * 100.0
```

**Key question for probe:** When trade is saved to Firebase, are max_seen and min_seen included in the document?

**What probe will determine:**
- ✅ If max_seen/min_seen fields are present in fetched documents
- ✅ If they contain actual price levels (non-zero floats)
- ✅ If alternative fields exist (mfe_pct, mae_pct pre-calculated)

---

## Probe Readiness Assessment

### Pre-Probe Status: LIKELY READY

**Confidence level:** 75% (high confidence, but unverified)

**Reasoning:**
1. ✅ Collection path clearly identified from code
2. ✅ Document structure (one-per-trade) strongly implied
3. ✅ Most required fields confirmed in code
4. ⚠️ MFE/MAE field persistence not confirmed (most likely stored, but unverified)
5. ✅ Filter capability (status="closed") confirmed
6. ✅ Timestamp ordering capability confirmed

**Risk factors:**
- Could have changed in recent commits (low probability)
- Schema might differ between production and dev (possible)
- max_seen/min_seen might not be persisted (low probability)

---

## Expected Probe Outcome: READY

**If probe succeeds, expect:**
```
- Collection: "trades"
- Storage model: One document per trade
- Document count for 100 canonical trades: ~100 (one-per-document)
- Critical fields present: YES (including max_seen/min_seen)
- Can isolate canonical trades: YES (status="closed" + recent timestamp filter)
- Entry-vs-exit diagnosis possible: YES (MFE/MAE data available)
```

**Readiness classification:** READY  
**Recommended next step:** Approve and execute Phase 2 full read (100+ documents for complete diagnosis)

---

## Expected Probe Outcome: PARTIALLY READY

**If max_seen/min_seen absent, but other fields present:**
```
- Collection: "trades"
- Storage model: One document per trade
- Critical fields: Present except MFE/MAE sources
- Alternative data: Possibly available (candle history, price data, evaluation fields)
```

**Readiness classification:** PARTIALLY READY  
**Recommended next step:** Revise Phase 2 request to include candle/price data OR use pre-calculated mfe_pct/mae_pct if available

---

## Expected Probe Outcome: NOT READY

**If collection not found or critical fields absent:**
```
- Collection path unknown or incorrect
- OR essential fields (entry/exit prices, timestamps) missing
- OR canonical trades cannot be isolated from shadow/diagnostic rows
```

**Readiness classification:** NOT READY  
**Recommended next step:** Document blockers; recommend proceeding with Phase 1A analysis only

---

## Probe Questions to Answer

**Question 1: Exact collection path?**
- Expected: `"trades"`
- Will be confirmed by: Successfully querying collection

**Question 2: One-document-per-trade storage?**
- Expected: Yes (one doc = one trade)
- Will be confirmed by: Retrieving 2–3 docs and counting distinct trade_ids

**Question 3: max_seen and min_seen persisted?**
- Expected: Yes
- Will be confirmed by: Presence of non-zero float fields in documents

**Question 4: Can filter by status="closed"?**
- Expected: Yes
- Will be confirmed by: Running filtered query and receiving only closed trades

**Question 5: Can isolate canonical/recent trades?**
- Expected: Yes (via status="closed" AND recent exit_ts)
- Will be confirmed by: Query with timestamp filter returning appropriate trades

**Question 6: Cost to retrieve 100 canonical trades?**
- Expected: ~100 document reads (if one-per-document model confirmed)
- Will be inferred from: Document count multiplied by trade count needed

---

## Probe Execution Checklist

**Before starting reads:**
- [ ] Firebase credentials available and configured
- [ ] Network access to Firestore confirmed
- [ ] Current day's read quota checked (should be >> 10)
- [ ] READ_LEDGER.md prepared for results
- [ ] This report ready for findings annotation

**During reads:**
- [ ] Update READ_LEDGER.md with each operation's actual read count
- [ ] Record all returned documents' field names and sample values
- [ ] Note any errors or unexpected results

**After reads:**
- [ ] Summarize findings in FIREBASE_SCHEMA_PROBE_REPORT.md update
- [ ] Create FIELD_AVAILABILITY_MATRIX.csv with confirmed fields
- [ ] Determine readiness classification (READY / PARTIALLY READY / NOT READY)
- [ ] Generate PHASE2_FULL_READ_APPROVAL_REQUEST_REVISED.md with actual findings

---

## Reference: Code Locations

**Primary sources for schema verification:**

| Topic | File | Lines | Evidence |
|-------|------|-------|----------|
| Collection path | `src/services/firebase_client.py` | 35, 235, 280, 320 | `col("trades")` |
| Trade save | `src/services/trade_executor.py` | ~1400 | `save_trade()` |
| Exit context | `src/services/exit_attribution.py` | 97–146 | `build_exit_ctx()` |
| MFE/MAE tracking | `src/services/paper_trade_executor.py` | 1139, 2028 | `max_seen`, `min_seen` |
| Status field | `src/services/firebase_client.py` | ~270 | `"status": "closed"` |
| History load | `src/services/firebase_client.py` | ~235 | `load_history()` |

---

## Conclusion

**Phase 2B schema probe is ready for execution.**

Pre-probe analysis from code inspection indicates **75% confidence that Firebase contains the required data** in the expected format. The 10-read probe will definitively answer remaining uncertainties and enable:

1. ✅ Exact Phase 2 read budget (currently estimated 100+ reads, could be lower if aggregate documents)
2. ✅ Field mapping for entry-vs-exit MFE/MAE analysis
3. ✅ Determination of whether full Phase 2 read can proceed

**Critical dependency:** Operator must execute probe reads with Firebase credentials and report findings back to this analysis.
