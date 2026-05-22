# Phase 2: Revised Full Read Approval Request

**Status:** READY FOR PROBE RESULTS (to be populated after Phase 2B)  
**Date:** 2026-05-22  
**Based on:** Phase 2A analysis + Phase 2B schema probe findings  
**Purpose:** Exact approval for full entry-vs-exit diagnosis via Firebase reads  

---

## Executive Summary

Phase 2B schema probe (max 10 reads) will verify exact Firebase schema and field availability. Once probe results are returned, this document will be completed with:

1. ✅ Verified collection path and document structure
2. ✅ Confirmed field names and data types
3. ✅ Accurate read budget for 100 canonical trades
4. ✅ Exact filter/query to isolate canonical trades
5. ✅ Readiness classification for entry-vs-exit diagnosis

**This section will be populated after Phase 2B probe execution.**

---

## Placeholder: Probe Results

*To be filled in by operator after Phase 2B reads complete*

| Item | Result | Confidence | Evidence |
|---|---|---|---|
| **Collection path** | TBD | TBD | Read 1–2 results |
| **Storage model** | TBD | TBD | Read 1–3 results |
| **max_seen/min_seen present?** | TBD | TBD | Read 3 results |
| **Canonical filter verified?** | TBD | TBD | Read 2 results |
| **Total reads used in Phase 2B** | TBD | TBD | READ_LEDGER.md |
| **Readiness classification** | TBD | TBD | FIREBASE_SCHEMA_PROBE_REPORT.md |

---

## Expected Scenarios and Revised Approvals

### Scenario A: Probe Returns READY

**If probe confirms:**
- ✅ Collection: `trades`
- ✅ Storage: One-document-per-trade
- ✅ Fields: All critical fields present, including max_seen & min_seen
- ✅ Filter: Can isolate canonical trades via status="closed" + recent exit_ts
- ✅ Phase 2B reads used: ≤ 6

**Approval request to operator:**

```text
PHASE 2 FULL READ REQUEST (READY STATUS)

Collection path: db.collection("trades")
Query/Filter: status == "closed" AND exit_ts >= (30 days ago)
Order: exit_ts DESC
Limit: 100
Fields: All (will extract trade_id, symbol, side, entry/exit, max_seen, min_seen, 
         net_pnl, gross_pnl, fee_cost, slippage_cost, exit_reason, outcome, regime)

Estimated documents to read: 100 (one per trade)
Maximum read budget: 110 reads (with 10% buffer)
Additional quota after Phase 2B: 110 reads from remaining daily budget
Daily quota: 50,000 reads
Percentage used: 110 / 50,000 = 0.22%

Outcome will determine:
- Entry signal directional edge: PROVEN or DISPROVEN
- Exit policy correctness: PROVEN or DISPROVEN
- Strategy redesign direction: Entry-focused vs Exit-focused vs Both

Timeline: 30 minutes (download + parse + analyze)
Safety: Read-only, no writes, no state changes
Restart needed: No
```

**Recommendation:** APPROVE — All preconditions met, schema verified, budget acceptable

---

### Scenario B: Probe Returns PARTIALLY READY

**If probe confirms:**
- ✅ Collection: `trades` exists
- ✅ Storage: One-document-per-trade (but or aggregate)
- ⚠️ max_seen/min_seen: ABSENT (but alternative fields present)
- ✅ Other fields: Present and complete
- ✅ Phase 2B reads used: 6

**Options:**

**Option B1: Proceed with alternative MFE/MAE calculation**
```text
If mfe_pct / mae_pct fields are pre-calculated and stored:
- Read same collection, fields available
- Entry-vs-exit diagnosis still possible
- Estimated reads: Same as Scenario A (110 reads)

If fields must be derived from price history:
- Requires separate candle/price history export
- Significantly higher read cost
- May not be practical from Firestore
- Recommendation: Skip Phase 2, proceed with Phase 1A confidence only
```

**Recommendation:** If mfe_pct/mae_pct available → APPROVE with modified fields list  
Otherwise → DECLINE Firebase Phase 2, use Phase 1A analysis only

---

### Scenario C: Probe Returns NOT READY

**If probe cannot resolve:**
- ❌ Collection path unknown or unqueryable
- ❌ Critical fields absent (entry/exit prices, timestamps, outcome)
- ❌ Canonical trades cannot be isolated
- ❌ Phase 2B reads used: 6–10 (exhausted budget on troubleshooting)

**Recommendation:** DECLINE Phase 2 — Proceed with Phase 1A analysis only

```text
Alternative path:
- Current conclusion based on Phase 1A: Entry edge STRONGLY SUSPECTED (85% confidence)
- Strategy verdict: UNCHANGED (NO-GO)
- Risk: Proceeding without 95% confidence on entry vs. exit causality
- Timeline impact: Minimal (can start redesign immediately)
```

---

## Implementation Path (After Probe)

**IF APPROVED (Scenario A or B1):**

```
Step 1: Execute Phase 2 full read
  - Connect to Firebase with verified query from Phase 2B
  - Retrieve all 100 canonical closed trades
  - Download JSON (estimate ~40KB)
  - Cumulative reads: 6 (Phase 2B) + 110 (Phase 2) = 116 total
  - Quota impact: 116 / 50,000 = 0.23%

Step 2: Local analysis
  - Parse trade documents
  - Calculate MFE/MAE for each trade
  - Classify by side (LONG/SHORT for correct directional interpretation)
  - Analyze SCRATCH/STAGNATION trades:
    * Count: How many had MFE > 0.1%?
    * Average MFE when present
    * Relationship to TP target (did they reach profitable move?)

Step 3: Generate diagnosis report
  - Output: ENTRY_VS_EXIT_DIAGNOSIS_REPORT.md
  - Include: Trade-level data, statistical summaries, conclusions
  - Answer: Entry broken? Exit broken? Both?

Step 4: Confidence uplift
  - Current: 85% (entry suspected broken)
  - After Phase 2: 95%+ (proven or disproven)
  - Enables confident redesign strategy selection
```

---

## Revised Budget and Timeline

**Phase 2B probe:**
- Reads allocated: 10 (max hard cap)
- Reads expected: 6 (if successful)
- Timeline: 5 minutes

**Phase 2 full read (if approved):**
- Reads allocated: 110 (100 trades + buffer)
- Reads expected: ~100
- Timeline: 15 minutes (read) + 15 minutes (analyze) = 30 minutes

**Combined project:**
- Total reads: ≤ 116
- Percentage of daily quota: 0.23%
- Total timeline: ~40 minutes (including download, parse, analysis)

---

## Approval Checklist (To Be Completed Post-Probe)

**After Phase 2B probe completes, verify:**

- [ ] Collection path confirmed and tested
- [ ] Document structure confirmed (one-per-trade vs. aggregate)
- [ ] Critical fields present: max_seen/min_seen OR mfe_pct/mae_pct
- [ ] Canonical filter verified (status="closed" + timestamp)
- [ ] Phase 2B reads ≤ 10 (hard cap honored)
- [ ] Readiness classification determined (READY / PARTIALLY_READY / NOT_READY)

**Operator approval of revised request:**

- [ ] Firebase read budget 110 reads acceptable
- [ ] Quota impact <0.25% of daily limit acceptable
- [ ] 30-minute execution timeline acceptable
- [ ] Entry-vs-exit diagnosis will inform next phase (redesign vs. abandon)
- [ ] Authorization recorded and traceable

---

## Next Actions

1. **Operator executes Phase 2B probe** (max 10 reads, ~5 minutes)
2. **Return results:** UPDATE this document + READ_LEDGER + FIELD_AVAILABILITY_MATRIX
3. **Determine readiness:** READY / PARTIALLY_READY / NOT_READY
4. **If READY:** Operator approves revised budget (110 additional reads)
5. **If READY:** Execute Phase 2 full read and diagnosis
6. **If NOT READY:** Proceed with Phase 1A analysis only (85% confidence)

---

## Reference

**Related documentation:**
- Phase 1A corrections: `PHASE1A_CORRECTION_REPORT.md`
- Phase 2A analysis: `firebase_reconciliation_phase2a_2026-05-22/FIREBASE_PHASE2_READ_APPROVAL_REQUEST.md`
- Phase 2B probe plan: `PRE_READ_QUERY_CANDIDATES.md`
- Phase 2B schema findings: `FIREBASE_SCHEMA_PROBE_REPORT.md`
- Phase 2B read ledger: `READ_LEDGER.md`

**All files location:** `data/research/firebase_reconciliation_phase2b_schema_probe_2026-05-22/`

---

## Conclusion

This revised approval request will be finalized with exact, verified information once Phase 2B probe completes. The probe will remove all schema uncertainties and enable confident approval or decline of Phase 2 full reads.

**Current status:** Ready for Phase 2B probe execution by operator.
