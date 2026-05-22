# Phase 2B: Firebase Probe Read Ledger

**Hard cap:** 10 total document reads  
**Status:** PLANNED (ready for execution with Firebase credentials)  
**Execution context:** Requires Firebase authentication and direct database access  

---

## Planned Read Operations

| Op # | Collection | Query/Filter | Order | Limit | Purpose | Est. Reads | Cumulative | Status |
|---|---|---|---|---|---|---|---|---|
| **1** | `trades` | (none) | (none) | 2 | Verify collection exists; inspect document structure | 2 | 2 | PLANNED |
| **2** | `trades` | `status="closed"` | (none) | 2 | Verify closed-trade filter works; inspect field names | 2 | 4 | PLANNED |
| **3** | `trades` | `status="closed"` | `exit_ts DESC` | 2 | Verify ordering works; confirm recent trade fields | 2 | 6 | PLANNED |
| **4A** | `canonical_trades` | (fallback) | (none) | 2 | Test alternative collection if `trades` not found | 2 | 8 | CONDITIONAL |
| **4B** | `{PREFIX}trades` | (fallback) | (none) | 2 | Test prefixed variant if unfiltered fails | 2 | 10 | CONDITIONAL |
| **TOTAL** | | | | | | **<= 10** | **<= 10** | |

---

## Read Operation Details

### Operation 1: Unfiltered Collection Read

**Purpose:** Verify collection exists and document structure

```firestore
Collection: "trades"
Filter: None
Order: None
Limit: 2
```

**Expected outcome:**
- ✅ 2 documents returned (or fewer if collection empty)
- Fields present: trade_id, symbol, side, entry_price, exit_price, net_pnl, status
- Document IDs: auto-generated or explicit trade_id

**Cost:** 2 reads  
**Decision threshold:** If empty or error, attempt Operation 2 with filter

---

### Operation 2: Closed-Trade Filter Verification

**Purpose:** Verify status filter and field availability for closed trades

```firestore
Collection: "trades"
Filter: status == "closed"
Order: None
Limit: 2
```

**Expected outcome:**
- ✅ 2 closed trade documents
- Fields present: All from Op 1, plus exit_reason, outcome, fee_cost, slippage_cost
- Status field value: "closed" (confirmed)

**Cost:** 2 reads  
**Cumulative:** 4 reads  
**Decision threshold:** If no closed trades found, proceed to Op 3 anyway; schema confirmed

---

### Operation 3: Recent Trades with Ordering

**Purpose:** Verify timestamp ordering and MFE/MAE field presence

```firestore
Collection: "trades"
Filter: status == "closed"
Order: exit_ts DESC (or close_time DESC if exit_ts missing)
Limit: 2
```

**Expected outcome:**
- ✅ 2 most recent closed trades
- Fields: All previous + max_seen, min_seen (or mfe_pct, mae_pct)
- Ordering: Trades sorted by exit timestamp descending (most recent first)
- Field data: max_seen and min_seen are non-zero floats (price levels)

**Cost:** 2 reads  
**Cumulative:** 6 reads  
**Decision threshold:** CRITICAL — if max_seen/min_seen absent, switch to "PARTIALLY READY" status

---

### Operation 4A: Fallback to Alternative Collection

**Purpose:** If primary "trades" collection unavailable, test "canonical_trades" alias

```firestore
Collection: "canonical_trades"
Filter: None
Order: None
Limit: 2
```

**Cost:** 2 reads (only if Op 1–3 all failed)  
**Cumulative:** 8 reads  

---

### Operation 4B: Fallback to Prefixed Collection

**Purpose:** If both above fail, test prefixed variant (shadow mode)

```firestore
Collection: "{PREFIX}trades"
Filter: None
Order: None
Limit: 2
```

**Cost:** 2 reads (only if all above failed)  
**Cumulative:** 10 reads (hard cap)  

---

## Execution Prerequisites

**Before attempting reads, verify:**

1. **Firebase authentication:** Credentials file present and valid
2. **Collection prefix:** Check `COLLECTION_PREFIX` environment variable (likely empty for production)
3. **Network access:** Firebase Firestore endpoint reachable
4. **Quota check:** Current daily read count < 50,000

**Command to check quota (local):**
```bash
python3 -c "from src.services.firebase_client import get_quota_status; print(get_quota_status())"
```

---

## Read Execution Protocol

**For each operation:**

1. Execute the query with the specified limit
2. Record:
   - Actual document count returned (may be ≤ limit)
   - Document structure (field names and types)
   - Sample field values (redact sensitive trade details)
   - Any errors or exceptions
3. Update this ledger with actual counts
4. If all planned reads succeed: Stop at Op 3 cumulative (6 reads)
5. If Op 1–3 fail: Proceed to Op 4A/4B fallback (max 10 total)

---

## Success Criteria

**Probe is successful if:**
- ✅ Collection path verified (trades or canonical_trades)
- ✅ Document structure understood (one-per-trade vs. aggregate)
- ✅ Critical fields confirmed present:
  - Unique identifier (trade_id or document ID)
  - Symbol, side, entry/exit prices and timestamps
  - Net PnL and gross PnL (or means to calculate)
  - Fee cost and slippage cost
  - Exit reason and outcome classification
  - **MFE/MAE indicators:** max_seen & min_seen OR mfe_pct & mae_pct
- ✅ Closed trades can be isolated via status filter or default collection
- ✅ Total reads <= 10

---

## Post-Probe Actions

**If SUCCESS:**
- Create FIELD_AVAILABILITY_MATRIX.csv with confirmed fields
- Create FIREBASE_SCHEMA_PROBE_REPORT.md with findings
- Create PHASE2_FULL_READ_APPROVAL_REQUEST_REVISED.md specifying Phase 2 read count
- **Proceed to Phase 2** (if operator approves revised request)

**If PARTIAL SUCCESS:**
- Report missing fields and recommended workarounds
- Specify alternative data sources or queries needed
- Revise Phase 2 request with modified scope

**If FAILURE:**
- Report unresolved blockers
- Recommend proceeding with Phase 1A analysis only (no Firebase data)
- Document why Firebase-based entry-vs-exit diagnosis not possible

---

## Notes

- Probe execution must be done by operator or in environment with Firebase credentials
- All 10 reads are "conditional" — later operations depend on success of earlier ones
- Read ledger will be updated with actual results during/after execution
- No data will be persisted locally except anonymized schema documentation
