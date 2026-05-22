# Phase 2B: Firebase Schema Probe Execution Status

**Status:** READY FOR OPERATOR EXECUTION  
**Date:** 2026-05-22  
**Safe Head:** 735ba35  
**Execution Environment:** Windows 11 Pro, Python 3.9+, firebase-admin SDK installed  

---

## Executable Probe Script

A complete, standalone Python probe script has been created at:
```
phase2b_firebase_probe.py
```

**Requirements to execute:**
1. Python 3.9+ with firebase-admin SDK installed
2. FIREBASE_KEY_BASE64 environment variable set (base64-encoded service account JSON)
3. Network access to Firestore
4. Current working directory: `C:\Projects\CryptoMaster_srv`

**Execution command:**
```powershell
cd C:\Projects\CryptoMaster_srv
$env:FIREBASE_KEY_BASE64 = "YOUR_BASE64_ENCODED_KEY_HERE"
python phase2b_firebase_probe.py
```

---

## Probe Operations (Planned)

The script will execute 4 operations with max 10 total reads:

### Operation 1: Unfiltered Collection (2 reads)
```firestore
Collection: "trades"
Filter: None
Order: None
Limit: 2
Purpose: Verify collection exists and inspect document structure
```

Expected output: Document count, field names, sample values

### Operation 2: Closed-Trade Filter (2 reads)
```firestore
Collection: "trades"
Filter: status == "closed"
Order: None
Limit: 2
Purpose: Verify status field and closed-trade isolation
```

Expected output: Confirm status field present, documents returned

### Operation 3: Timestamp Ordering (2 reads)
```firestore
Collection: "trades"
Filter: status == "closed"
Order: exit_ts DESC (fallback: timestamp DESC)
Limit: 2
Purpose: Verify timestamp ordering works and check MFE/MAE field presence
```

Expected output: Confirm exit_ts ordering, identify max_seen/min_seen/mfe_pct/mae_pct presence

### Fallback Operations 4A-4B (Conditional, up to 4 reads if above fail)
```firestore
If Operation 1-3 fail:
  4A: Collection: "canonical_trades" (alternative name)
  4B: Collection: "{PREFIX}trades" (shadowed variant)
```

---

## What Probe Results Will Determine

Upon execution, the script will:

1. **Verify Collection Path** ✓
   - Confirm "trades" collection exists (or identify correct name)
   - Identify if prefix applied (COLLECTION_PREFIX env var)

2. **Verify Storage Model** ✓
   - Confirm one-document-per-trade storage (vs. aggregate documents)
   - Sample documents to identify schema structure

3. **Verify Field Presence** ✓
   - Confirm 100% list of stored fields
   - Identify which fields are actually persisted vs. only calculated

4. **Critical: MFE/MAE Fields** ✓
   - Determine if max_seen/min_seen are persisted in documents
   - OR if mfe_pct/mae_pct are pre-calculated and stored
   - OR if neither exists (requires alternative data source)

5. **Verify Canonical Filter** ✓
   - Confirm status="closed" successfully isolates canonical trades
   - Identify if additional filters needed (bucket, source, environment)

6. **Readiness Classification** ✓
   - READY: All required fields present, MFE/MAE available
   - PARTIALLY_READY: Core fields present but MFE/MAE requires alternative source
   - NOT_READY: Schema cannot be resolved or critical fields absent

---

## Output Files Generated

Upon execution, the script produces:
- `PHASE2B_PROBE_RESULTS.json` — machine-readable ledger of all operations
- Console output with detailed field inspection

---

## Next Steps for Operator

1. **Set Firebase credentials** in environment
2. **Execute the probe script:**
   ```powershell
   python phase2b_firebase_probe.py
   ```
3. **Capture console output** and save to file
4. **Review results** for readiness classification
5. **Provide results** back for Phase 2 approval decision

---

## Manual Alternative (If Python Execution Not Available)

If Python cannot be executed, operator can manually query Firestore console:

1. Open Firebase Console → Firestore Database
2. Navigate to "trades" collection
3. Request first 2 documents (note: Firestore console doesn't show read count, but each document view = 1 read)
4. Inspect fields present in documents
5. Run filtered query: `where status == "closed", limit 2` (2 more reads)
6. Run ordered query: `order by exit_ts descending, where status == "closed", limit 2` (2 more reads)
7. Document all field names and sample values

---

## Authorization

This probe:
- ✅ Uses read-only operations only
- ✅ Hard cap of 10 total document reads (0.02% of 50k daily quota)
- ✅ No writes, updates, deletes, or modifications
- ✅ No runtime code changes
- ✅ Safe to execute immediately

