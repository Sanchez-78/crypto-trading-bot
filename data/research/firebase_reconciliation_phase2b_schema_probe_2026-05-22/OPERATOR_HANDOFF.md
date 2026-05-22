# Phase 2B: Operator Handoff Package

**Status:** ✅ READY FOR OPERATOR EXECUTION  
**Date:** 2026-05-22  
**Prepared by:** Claude Code Analysis  
**Safe Head:** 735ba35 (git verified)  

---

## What's Been Prepared

A complete Phase 2B package is ready for operator execution:

### Files Prepared in This Directory
- ✅ `phase2b_firebase_probe.py` — Executable Python probe script
- ✅ `PROBE_EXECUTION_STATUS.md` — Detailed execution guide
- ✅ `PRE_READ_QUERY_CANDIDATES.md` — Query candidates from code inspection (from Phase 2B planning)
- ✅ `READ_LEDGER.md` — Read operations ledger (from Phase 2B planning)
- ✅ `FIREBASE_SCHEMA_PROBE_REPORT.md` — Pre-probe analysis (from Phase 2B planning)
- ✅ `FIELD_AVAILABILITY_MATRIX.csv` — Field status matrix (from Phase 2B planning)
- ✅ `PHASE2_FULL_READ_APPROVAL_REQUEST_REVISED.md` — Revised approval template (from Phase 2B planning)

---

## What This Package Does

This package executes **minimal Firebase read-only operations** (max 10 document reads, 0.02% of daily quota) to verify:

1. **Collection Path** — Is the trades collection at `"trades"` or another path?
2. **Storage Model** — Is it one-document-per-trade or aggregate?
3. **Field Presence** — Which fields are actually stored in Firebase documents?
4. **Critical Question** — Are `max_seen`/`min_seen` persisted, or `mfe_pct`/`mae_pct` pre-calculated?

These answers determine whether **Phase 2 full read** (110+ documents) can proceed to answer the entry-vs-exit question with 95%+ confidence.

---

## Operator Tasks

### Task 1: Set Firebase Credentials (One-Time)

Obtain your Firebase service account JSON from:
- Firebase Console → Project Settings → Service Accounts
- Download as JSON file

**Encode to base64:**
```powershell
# Windows PowerShell
$cred = Get-Content "path/to/service-account.json" -Raw
$encoded = [System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($cred))
Write-Host $encoded
```

**Set environment variable:**
```powershell
$env:FIREBASE_KEY_BASE64 = "YOUR_BASE64_STRING_HERE"
```

### Task 2: Execute the Probe Script

```powershell
cd C:\Projects\CryptoMaster_srv
python phase2b_firebase_probe.py
```

**Expected execution time:** ~30 seconds  
**Expected output:** Console log + JSON results file

### Task 3: Capture Results

The script automatically saves results to:
```
data/research/firebase_reconciliation_phase2b_schema_probe_2026-05-22/PHASE2B_PROBE_RESULTS.json
```

**Save console output** to file for reference:
```powershell
python phase2b_firebase_probe.py | Tee-Object -FilePath "phase2b_console_output.txt"
```

### Task 4: Provide Results

Return the following to the analysis:
1. Console output (text log)
2. `PHASE2B_PROBE_RESULTS.json` file
3. Readiness classification from output (READY / PARTIALLY_READY / NOT_READY)

---

## What the Probe Will Report

The probe script outputs:

```
[Operation 1] Verify collection exists; inspect structure
  Query: db.collection("trades").limit(2)
  Limit: 2, Actual reads: X, Cumulative: X/10
  Notes: Found N documents. Fields: [list of fields]

[Operation 2] Verify closed-trade filter
  Query: status=="closed" filter, limit 2
  Limit: 2, Actual reads: X, Cumulative: X/10
  Notes: Found N closed trades. Fields: [list of fields]

[Operation 3] Verify ordering; check MFE/MAE fields
  Query: status=="closed" ORDER BY exit_ts DESC LIMIT 2
  Limit: 2, Actual reads: X, Cumulative: X/10
  Notes: Found N recent trades. MFE/MAE fields present: [list or NONE]

PHASE 2B PROBE SUMMARY
Total Firebase reads used: X/10
Readiness classification: [READY | PARTIALLY_READY | NOT_READY]
```

---

## Understanding Readiness Classifications

### READY (Best Case)
**Conditions:**
- Collection "trades" found with no special prefix
- Storage is one-document-per-trade
- Fields include: trade_id, symbol, side, entry/exit prices/timestamps, net_pnl, gross_pnl, fee_cost, slippage_cost, exit_reason, outcome, status
- **Critical:** max_seen and min_seen fields are present with non-zero values (price levels)

**Implication:** Proceed to Phase 2 full read (110+ documents) to perform entry-vs-exit diagnosis

**Next Step:** Generate `PHASE2_FULL_READ_APPROVAL_REQUEST_REVISED.md` with exact verified path and proceed with Phase 2

---

### PARTIALLY_READY (Middle Case)
**Conditions:**
- Collection and storage model verified
- Core fields present
- **Critical fields missing:** max_seen/min_seen
- **But alternatives available:** mfe_pct/mae_pct pre-calculated OR candle history available

**Implication:** Phase 2 possible but requires modified query to use alternative data sources

**Next Step:** Revise `PHASE2_FULL_READ_APPROVAL_REQUEST_REVISED.md` to specify alternative data source; execute Phase 2 with modified fields

---

### NOT_READY (Worst Case)
**Conditions:**
- Collection cannot be found
- OR critical fields completely absent
- OR canonical trades cannot be isolated from shadow/diagnostic rows

**Implication:** Firebase Phase 2 cannot answer entry-vs-exit question

**Next Step:** Halt Firebase Phase 2; proceed with Phase 1A analysis only (85% confidence without raw MFE/MAE data)

---

## Quota Impact

- **Phase 2B probe reads:** ≤ 10 documents (0.02% of 50k daily limit)
- **Phase 2 (if READY):** ~110 documents (0.22% of limit)
- **Combined:** ≤ 120 documents (0.24% of limit) — **well within safe margins**

---

## Safety Checks (Already Verified)

- ✅ Git head verified: 735ba35
- ✅ No uncommitted code changes
- ✅ No runtime modifications authorized
- ✅ Read-only operations only
- ✅ Hard cap enforced in code
- ✅ Firebase write operations forbidden
- ✅ FIREBASE_WRITES: FORBIDDEN
- ✅ RUNTIME_PATCH_FREEZE: ACTIVE

---

## Troubleshooting

### Error: "FIREBASE_KEY_BASE64 not set"
→ Set environment variable before running script

### Error: "429 Quota Exceeded"
→ Firebase daily quota exhausted; wait until next day (midnight Pacific / 09:00 GMT+2)

### Error: "Collection not found"
→ Probe will attempt fallback collections (canonical_trades, {PREFIX}trades)
→ If all fail, readiness = NOT_READY

### Error: "timeout" or "network error"
→ Check Firestore connectivity; may need to retry

---

## Timeline

- **Phase 2B probe execution:** ~30 seconds
- **Results analysis:** ~5 minutes
- **Phase 2 approval decision:** Immediate (based on readiness classification)
- **Phase 2 full read (if approved):** ~15 minutes
- **Phase 2 analysis (if approved):** ~15 minutes
- **Total end-to-end:** ~1 hour (if READY path)

---

## Completion Checklist

- [ ] Firebase credentials obtained and encoded
- [ ] FIREBASE_KEY_BASE64 environment variable set
- [ ] `phase2b_firebase_probe.py` executed successfully
- [ ] Console output captured
- [ ] `PHASE2B_PROBE_RESULTS.json` generated
- [ ] Readiness classification determined
- [ ] Results provided back to analysis

---

## Key Decision Point

**After Phase 2B probe completes:**

- **If READY:** Approve Phase 2 full read (110+ docs) for entry-vs-exit diagnosis
- **If PARTIALLY_READY:** Revise Phase 2 request with alternative data sources
- **If NOT_READY:** Accept Phase 1A conclusion (85% confidence) without Firebase data

This decision will determine whether the strategy redesign proceeds with 85% or 95%+ confidence in the entry-vs-exit mechanism.

