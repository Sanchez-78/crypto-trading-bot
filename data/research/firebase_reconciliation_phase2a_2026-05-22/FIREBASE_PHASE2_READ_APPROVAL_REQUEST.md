# Firebase Phase 2: Exact Read Approval Request

**Status:** READY FOR OPERATOR APPROVAL  
**Date:** 2026-05-22  
**Purpose:** Entry-vs-exit diagnosis via MFE/MAE analysis of canonical closed trades  
**Safety Level:** Read-only, no writes, no state changes, <1% of daily quota  

---

## Executive Summary

Phase 1A corrections have resolved all local arithmetic mismatches (PF reconciliation PASS, expectancy characterized, win count methodology clarified). However, **entry-vs-exit causality remains unresolved** without raw per-trade MFE/MAE data.

This approval request specifies the exact Firebase reads needed to answer:
```
Did entry signals fail to produce favorable movement? (entry broken)
OR
Did entries have favorable movement that exit logic failed to monetize? (exit broken)
```

---

## Read Operations — Exact Specification

### OPERATION 1: Canonical Closed Trades Population (CRITICAL PATH)

| Aspect | Specification |
|--------|---|
| **Collection/Path** | `canonical_closed_trades` OR `trades` collection with filters |
| **Query/Filter** | `WHERE status = "closed" AND (created_ts OR exit_ts) >= 30_days_ago` |
| **Order** | `ORDER BY exit_ts DESC` |
| **Limit** | `LIMIT 100` |
| **Fields Required** | trade_id, symbol, side, regime, entry_price, exit_price, entry_ts, exit_ts, max_seen, min_seen, net_pnl, gross_pnl, fee_cost, slippage_cost, exit_reason (or close_reason), outcome (or result) |
| **Expected Document Count** | **UNKNOWN — depends on storage model** |
| **Storage Model Assessment** | Likely one-document-per-trade (100 trade docs) BUT could be aggregated (5–10 docs). Must verify. |

**Exact Document Count Logic:**

**Case A: One-trade-per-document** (most likely):
```
- 100 trade documents (one per closed trade)
- + 1 collection metadata read (optional, to verify structure)
- TOTAL: 100–101 reads
```

**Case B: Aggregate documents** (e.g., date_closed batches):
```
- If 10 trades per document: 100 / 10 = 10 documents
- If 5 trades per document: 100 / 5 = 20 documents
- + 1 collection metadata read
- TOTAL: 11–21 reads
```

**Decision Logic:** Query first document(s) with limit 10 to discover storage model, THEN make final read count.

---

### OPERATION 1A: Discovery Query (First Step)

**Purpose:** Determine one-per-document vs. aggregate without reading all 100 trades

```firestore
Collection: canonical_closed_trades
Query: status == "closed" AND exit_ts >= (30 days ago)
Order By: exit_ts DESC
Limit: 10  (first 10 docs to inspect structure)
Fields: All (to assess completeness)
```

**Cost:** 10 document reads

**What this discovers:**
- ✅ Are max_seen / min_seen fields present in returned docs?
- ✅ Is each doc one trade, or do docs contain arrays of trades?
- ✅ Can we count 10 docs and infer total count?
- ✅ Are output fields present and well-formed?

**Decision after discovery:**
- **If each doc = one trade:** Proceed with full read (100 docs total)
- **If each doc = multiple trades:** Calculate actual doc count needed (could be 5–20 docs)
- **If fields missing:** Fall back to alternative query or report as impossible

---

### OPERATION 1B: Full Canonical Trade Read (Conditional)

**Executed only if OPERATION 1A discovery succeeds with sufficient fields**

```firestore
Collection: canonical_closed_trades
Query: status == "closed" AND exit_ts >= (30 days ago)
        AND training_bucket NOT IN ("D_NEG_EV_CONTROL", "B_RECOVERY_READY")  [optional filter]
Order By: exit_ts DESC
Limit: 100
Fields: trade_id, symbol, side, regime, entry_price, exit_price, entry_ts, exit_ts,
        max_seen, min_seen, net_pnl, gross_pnl, fee_cost, slippage_cost,
        exit_reason, outcome
```

**Expected document reads:**
- **Best case (aggregate documents):** 10–20 reads
- **Worst case (one-per-document):** 100 reads
- **Realistic estimate:** 90–110 reads (assuming mostly one-per-document, some small batching)

**Data volume:** ~40KB JSON (100 trades × ~400 bytes each)

**Validation success criteria:**
- ✅ All 100 trades retrieved (or close to it, ±5)
- ✅ MFE/MAE fields populated (max_seen, min_seen present and non-zero)
- ✅ Can calculate MFE/MAE for each trade
- ✅ sum(net_pnl) ≈ −0.00024 BTC (matches snapshot)
- ✅ Exit reason distribution matches snapshot (SCRATCH 47, STAGNATION 34, etc.)

---

## Alternative Operations (If Primary Path Unavailable)

### FALLBACK A: If canonical_closed_trades Does Not Exist

**Query alternate locations:**
```firestore
Collections to try in order:
1. trades (filter: status="closed")
2. trade_history (filter: closed=true)
3. paper_closed_trades (filter: bucket NOT D_NEG)
4. All collections query [expensive]
```

**Cost:** 3–5 test queries

---

### FALLBACK B: If MFE/MAE Not Stored

**Query price history instead:**
```firestore
For each of 100 canonical trades:
  - Retrieve candle/tick history between entry_ts and exit_ts
  - Calculate MFE/MAE locally from price history
  
Cost: High (would require 100+ reads for price data)
Recommendation: Ask if max_seen/min_seen were stored; if not, may not be worth pursuing
```

---

## Read Budget Summary

| Step | Operation | Estimated Reads | Cumulative | Purpose |
|---|---|---|---|---|
| 1 | Discovery query (10 docs) | 10 | 10 | Determine storage model |
| 2 | Full canonical trades (100 docs or batches) | 90–100 | 100–110 | MFE/MAE and diagnosis |
| 3 | Metadata / schema check | 1–5 | 101–115 | Validation |
| **TOTAL** | | | **100–115 reads** | |
| **Conservative (10% buffer)** | | | **<125 reads** | |
| **Daily quota** | 50,000 reads | | | |
| **Phase 2 usage %** | <0.3% | | | |

---

## Exact Execution Plan (No Reads Yet)

**Step-by-step, to be executed ONLY after operator approval:**

```
Step 0 (APPROVAL GATE — STOP HERE):
  ☐ Operator reviews and approves this read plan
  ☐ Operator confirms Firebase read-only access available
  ☐ Operator confirms 100–115 reads are acceptable
  
Step 1 (DISCOVERY PHASE):
  ☐ Execute Operation 1A: Query 10 canonical closed trades
  ☐ Inspect returned documents for structure
  ☐ Determine storage model (one-per-doc vs. aggregate)
  ☐ Check for max_seen, min_seen fields
  ☐ Estimate final read count
  
Step 2 (CONDITIONAL FULL READ):
  ☐ IF discovery succeeded: Execute Operation 1B (full 100-trade read)
  ☐ IF discovery failed: Report blockers and recommend alternatives
  
Step 3 (LOCAL ANALYSIS):
  ☐ Download JSON and parse trade data
  ☐ Calculate MFE/MAE for each trade
  ☐ Classify trades: "entry_had_direction" OR "entry_failed"
  ☐ Classify exit policy: "exit_correct" OR "exit_killed_winner"
  ☐ Generate diagnosis report
  
Step 4 (REPORTING):
  ☐ Output: raw_canonical_trades.json (downloaded data)
  ☐ Output: ENTRY_VS_EXIT_DIAGNOSIS_REPORT.md (analysis and conclusions)
```

**Total execution time:** ~30 minutes (including download, parse, analysis)

---

## What This Read Will Answer

### Primary Questions

**Question 1: Entry Signal Failure?**
```
Diagnosis: Count trades where MFE ≤ 0.1% (never moved favorably)
- If 90%+ of SCRATCH trades: MFE ≤ 0.1% → Entry lacked direction (BROKEN)
- If <50% of SCRATCH trades: MFE ≤ 0.1% → Some direction; exit killed winners (EXIT BROKEN)
```

**Question 2: Exit Policy Failure?**
```
Diagnosis: Count SCRATCH trades where MFE > TP_target
- If 50%+: Exit killed winners (exit too tight, BROKEN)
- If <10%: Entry never reached targets; exit is correct (ENTRY BROKEN)
```

**Question 3: Magnitude Comparison**
```
For trades with MFE > 0:
- Average MFE % to nearest decision boundary
- How close do entry moves come to TP targets?
- Why were they exited early?
```

### Confidence Uplift

**Current state (Phase 1A):**
- Entry failure suspected: 85% confidence (based on 81% non-move exit rate)
- Mechanism: Unknown (entry vs. exit)

**After Phase 2 reads:**
- Entry failure: Will be PROVEN or DISPROVEN from MFE/MAE analysis
- Confidence uplift: 85% → 95%+
- Next steps clearly defined: Entry redesign vs. exit redesign

---

## Risk Assessment

### Safety Level: LOW RISK ✓

**Read-only:** No writes, no state changes, no schema modifications
**Quota impact:** <0.3% of daily 50,000-read limit (115 reads)
**Timing:** Can be executed any time, including during live trading
**Failure mode:** If reads fail, no impact to strategy or state

### Operational Constraints

**Must be executed with:**
- ✅ Read-only Firebase client mode
- ✅ No retry loops (max 1 attempt per operation)
- ✅ Explicit quota tracking before execution
- ✅ Logs of read operations for later audit

**Must NOT:**
- ❌ Modify any trade data
- ❌ Write to any Firebase collections
- ❌ Restart or reload services
- ❌ Enable real trading

---

## Approval Checklist

**Operator must confirm ALL items before execution:**

- [ ] Read-only access to canonical_closed_trades collection is available
- [ ] Firebase account has available quota (115 reads from 50,000 daily limit)
- [ ] No schema migrations or changes will interfere with read
- [ ] Read timing (30 minutes, <125 reads) is acceptable
- [ ] Findings (entry vs. exit diagnosis) will inform strategy redesign
- [ ] Approval is recorded and traceable

---

## Next Steps After Approval

**Immediately after operator approval, execute Phase 2 reads to:**
1. Discover actual storage model
2. Retrieve 100 canonical closed trades with MFE/MAE data
3. Calculate entry-vs-exit diagnosis
4. Generate final report with definitive answers
5. Proceed with strategy redesign with high confidence

---

## Recommendation

**Phase 2 Firebase reads are RECOMMENDED.**

Despite Phase 1A corrections eliminating several false discrepancies (PF mismatch resolved, expectancy characterized), the **entry-vs-exit causality remains the critical blocker for strategy redesign**. This read operation:

- Resolves the most uncertain question
- Requires minimal reads (<0.3% of quota)
- Has zero risk to live strategy
- Provides high-confidence diagnosis (95%+)
- Directly determines redesign direction

**Ready for operator approval.**
