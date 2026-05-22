# Phase 2B: Pre-Read Query Candidates

**Status:** Local code inspection complete  
**Purpose:** Identify candidate Firebase collections/queries before probe reads  
**Method:** Grep and source code analysis of firebase_client.py and trade_executor.py  

---

## Candidate Collections Identified

### PRIMARY CANDIDATE: `trades` Collection

**Code Evidence:**
- `src/services/firebase_client.py` — `db.collection(col("trades"))`
- Multiple references: save_trade(), load_history(), load_old_trades(), publish_app_metrics_snapshot()

**Key file references:**
```
src/services/firebase_client.py:
  Line ~235: db.collection(col("trades")).order_by(...).limit(...)
  Line ~280: db.collection(col("trades")).document().set(item)  [write operation]
  Line ~320: db.collection(col("trades")).document(doc_id).delete()  [cleanup]
  
src/services/trade_executor.py:
  Line save_trade(): Writes closed trade to collection(col("trades"))
```

**Collection structure hint:**
```
Collection: "trades" (or "{PREFIX}trades" if COLLECTION_PREFIX env var set)
Document structure: One document per trade (indexed by trade_id or auto-generated)
Document fields: include "status" = "closed" for completed trades
Partition: Likely by timestamp or symbol based on load_history() orderings
```

**Reason for candidacy:**
- Explicit references to collection("trades") in primary trade-save and trade-load paths
- Used by all metrics/dashboard functions: load_history(), publish_app_metrics_snapshot()
- load_history() is the primary query interface with caching

**Planned probe allocation:** 5–6 reads
- 1–2 reads: Verify collection exists and document shape
- 3–4 reads: Verify field presence (especially max_seen, min_seen, fee_cost, slippage_cost)
- Total: <= 6 reads

---

### SECONDARY CANDIDATE: Aliased/Shadow Collections

**Code Evidence:**
- `src/services/firebase_client.py` Line 33: `PREFIX = os.getenv("COLLECTION_PREFIX", "")`
- `src/services/firebase_client.py` Line 35: `def col(name: str) -> str: return f"{PREFIX}{name}"`

**Purpose:**
- Shadow Mode for testing (may have separate prefixed collections during A/B testing or safe-mode runs)
- Allows parallel data collection without affecting production

**Collections to check if PRIMARY returns empty:**
- `{PREFIX}trades` (prefixed variant)
- `trades_v2` (potential versioning)
- `canonical_trades` (potential aliasing)
- `paper_closed_trades` (paper trading data)
- `closed_trades` (compressed/archived)

**Planned probe allocation:** Only if PRIMARY returns empty
- 2–3 reads to test alternatives
- Total: <= 3 reads (from remaining budget)

---

## Field Availability Assessment (Based on Code)

### Fields Confirmed in Trade Document (from code inspection)

**From `save_trade()` and exit context building:**

| Field | Evidence | Expected Type | Critical for Phase 2? |
|-------|----------|---|---|
| `trade_id` or `id` | Document key or field | string | YES |
| `symbol` | exit_attribution.py:99 | string | YES |
| `side` | exit_attribution.py:100 | string (LONG/SHORT) | YES |
| `entry_price` | exit_attribution.py:101 | float (BTC) | YES |
| `exit_price` | exit_attribution.py:102 | float (BTC) | YES |
| `entry_ts` | exit_attribution.py:102 | float (unix seconds) | YES |
| `exit_ts` or `close_time` | firebase_client.py, exit_attribution.py | float (unix seconds) | YES |
| `net_pnl` | app_metrics_contract.py:69 | float (BTC) | YES |
| `gross_pnl` | app_metrics_contract.py:156 | float (BTC) | MAYBE |
| `fee_cost` | exit_attribution.py:106 | float (BTC) | YES |
| `slippage_cost` | exit_attribution.py:107 | float (BTC) | YES |
| `exit_reason` or `close_reason` | exit_attribution.py:112 | string | YES |
| `outcome` or `result` | app_metrics_contract.py:99 | string (WIN/LOSS/FLAT) | YES |
| `regime` or `entry_regime` | exit_attribution.py:99 | string | MAYBE |
| `status` | firebase_client.py | string ("closed") | YES |
| **`max_seen`** | paper_trade_executor.py:1139 | float (price) | **CRITICAL** |
| **`min_seen`** | paper_trade_executor.py:1140 | float (price) | **CRITICAL** |
| `mfe_pct` / `mae_pct` | paper_trade_executor.py:2036 | float (%) | MAYBE (can derive from max/min) |
| `training_bucket` | app_metrics_contract.py:266 | string | MAYBE (for filtering) |

### Critical Uncertainty: Are max_seen/min_seen Persisted?

**Question:** The code in `paper_trade_executor.py` shows max_seen/min_seen are **calculated** during trade hold, but are they actually **stored** in Firebase documents?

**Evidence for storage:**
- Tracking code (lines 1139–1140) suggests they are held in trade state
- MFE/MAE calculation (lines 2036–2040) reads from trade records, implying storage

**Evidence against:**
- No explicit write/persist call to Firebase with these fields found in firebase_client.py grep
- Could be calculated on-the-fly after retrieval

**This is what the probe must determine.**

---

## Query Strategies for Probing

### Strategy A: Simple Document Read (If Unordered Collection)

```firestore
Collection: trades
Limit: 5–10 documents (no filter/order)
Purpose: Check document structure, field names, data types
```

**Pros:** Minimal cost (5 reads), fast
**Cons:** May not get closed trades; may get partial/draft trades
**Risk:** Low — read-only, limited scope

### Strategy B: Filtered Query for Closed Trades

```firestore
Collection: trades
Filter: status == "closed"
Order By: exit_ts DESC (or created_at DESC)
Limit: 5–10
Purpose: Verify closed-trade isolation and field completeness
```

**Pros:** Matches our actual use case
**Cons:** Slightly higher quota cost (might scan more docs)
**Risk:** Low — read-only, known filters

### Strategy C: Time-Based Window (Recent Trades)

```firestore
Collection: trades
Filter: status == "closed" AND exit_ts >= (today - 30 days)
Order By: exit_ts DESC
Limit: 5–10
Purpose: Verify recent trades contain MFE/MAE fields
```

**Pros:** Matches Phase 2's intended scope
**Cons:** Time filters may require index; unknown field name (exit_ts vs. close_time)
**Risk:** Medium — unknown index availability; could trigger index creation

---

## Proposed Probe Execution Plan

**Phase 2B Probe (max 10 reads):**

1. **Read 1–2:** Simple unfiltered collection query
   - Collection: `trades` (or `{PREFIX}trades`)
   - Limit: 2 documents
   - Purpose: Verify collection exists; inspect structure
   - Budget: 2 reads

2. **Read 3–4:** Status-filtered query
   - Collection: `trades`
   - Filter: `status == "closed"` (if field exists)
   - Limit: 2 documents
   - Purpose: Verify closed trades can be isolated; check field names
   - Budget: 2 reads

3. **Read 5–6:** Closed trades with timestamp ordering
   - Collection: `trades`
   - Filter: `status == "closed"`
   - Order By: `exit_ts DESC` or `close_time DESC`
   - Limit: 2 documents
   - Purpose: Verify recent trades; confirm MFE/MAE field presence
   - Budget: 2 reads

4. **Read 7–10:** Alternate collections if primary fails
   - Try `canonical_trades`, `paper_closed_trades`, or `{PREFIX}trades`
   - Purpose: Failover if "trades" collection doesn't exist or lacks required fields
   - Budget: 4 reads (reserve only if primary fails)

**Total allocated:** 10 reads (all used only if needed for failover)

---

## Unknowns to Resolve in Probe

- [ ] Exact collection name (trades vs. canonical_trades vs. other)
- [ ] COLLECTION_PREFIX value (production: likely empty)
- [ ] One-document-per-trade vs. batched aggregates
- [ ] Field naming: exit_ts vs. close_time vs. closed_at
- [ ] Whether max_seen and min_seen are actually persisted in documents
- [ ] Whether mfe_pct / mae_pct are pre-calculated or require derivation
- [ ] Whether D_NEG_EV_CONTROL and shadow trades can be filtered by field or require separate collection
- [ ] Typical document size and complexity

---

## Expected Outcomes and Next Steps

### Scenario A: Probe Returns READY
- Collection confirmed: `trades`
- All critical fields present: trade_id, side, entry/exit, max_seen, min_seen, fees, exit_reason
- Storage model: One-document-per-trade
- **Action:** Proceed to Phase 2 full read request with verified paths and fields (~100 additional reads for 100 canonical trades)

### Scenario B: Probe Returns PARTIALLY READY
- Collection confirmed, but max_seen/min_seen absent
- Alternative: Fields allow gross move calculation but require candle replay for precise MFE/MAE
- **Action:** Request revised Phase 2 plan including optional price-history candle export

### Scenario C: Probe Returns NOT READY
- Collection not found or canonical records cannot be isolated
- Required fields absent with no clear alternative
- **Action:** Report blockers; recommend proceeding with Phase 1A analysis only (85% confidence without Firebase data)

---

## Read Ledger Placeholder

| Operation # | Collection | Filter/Query | Requested Limit | Actual Reads | Cumulative | Status |
|---|---|---|---|---|---|---|
| 1 | trades | (none) | 2 | ? | ? | Pending |
| 2 | trades | status="closed" | 2 | ? | ? | Pending |
| 3 | trades | status="closed" ORDER BY exit_ts DESC | 2 | ? | ? | Pending |
| 4–7 | (fallback) | (alternative collections) | 4 | ? | ? | Pending |
| **TOTAL** | | | | | **<= 10** | |

*To be filled in during Phase 2B execution*
