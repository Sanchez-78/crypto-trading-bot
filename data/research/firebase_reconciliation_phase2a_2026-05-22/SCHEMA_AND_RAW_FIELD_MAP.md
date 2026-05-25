# Phase 2A: Firebase Schema and Raw Field Map

**Status:** DISCOVERED FROM SOURCE CODE INSPECTION  
**Date:** 2026-05-22  
**Method:** Read-only grep searches and source code tracing  

---

## High-Level Architecture

### Collections Identified

From `src/services/firebase_client.py`:
- **Pattern:** Uses `col(name)` helper function with optional COLLECTION_PREFIX for shadow mode
- **Usage:** `db.collection(col("trades"))`, `db.collection(col("closed_trades"))`, etc.

From analysis across codebase:
- `trades` or `canonical_trades` — Live/active trade records
- `closed_trades` or `canonical_closed_trades` — Completed trades
- `model_state` — Learning model/agent state
- `metrics` — Dashboard/performance metrics
- `config` — Runtime configuration

---

## Trade Document Structure

### Source Evidence

**From `src/services/paper_trade_executor.py` (lines 1133-1140, 2028-2040):**
```python
# Trade position tracking with MFE/MAE fields
_POSITIONS[trade_id]["max_seen"] = max(_POSITIONS[trade_id].get("max_seen", current_price), current_price)
_POSITIONS[trade_id]["min_seen"] = min(_POSITIONS[trade_id].get("min_seen", current_price), current_price)

# MFE/MAE calculation on trade close
mfe = (max_seen - entry) / entry * 100.0  # % favorable move
mae = (entry - min_seen) / entry * 100.0  # % adverse move
```

**From `src/services/exit_attribution.py` (lines 106-146):**
```python
# Exit context payload structure
{
    "symbol": sym,
    "regime": regime,
    "side": side,
    "entry_price": entry_price,
    "exit_price": exit_price,
    "size": size,
    "hold_seconds": hold_seconds,
    "gross_pnl": gross_pnl,
    "fee_cost": fee_cost,
    "slippage_cost": slippage_cost,
    "net_pnl": net_pnl,
    "mae": mae,
    "mfe": mfe,
    "final_exit_type": final_exit_type,
    "exit_reason_text": exit_reason_text,
    "was_winner": was_winner,
}
```

**From `src/services/app_metrics_contract.py` (lines 67-106):**
```python
# Trade profit extraction and outcome classification
def _extract_profit(trade: dict) -> float:
    for field in ("profit", "pnl", "net_pnl"):
        if field in trade:
            return float(trade[field] or 0.0)
    return float(trade.get("evaluation", {}).get("profit", 0.0) or 0.0)

# Outcome classification
outcome = _classify_outcome(trade, profit)  # Returns WIN/LOSS/FLAT
```

---

## Required Fields for Entry-vs-Exit Diagnosis

### High-Priority Fields (MUST HAVE)

| Field | Type | Source | Purpose |
|-------|------|--------|---------|
| `trade_id` | string | document key or field | Unique trade identifier |
| `symbol` | string | trade record | Asset pair (BTC, ETH, etc.) |
| `side` | string | trade record | Direction (LONG or SHORT) |
| `regime` | string | trade record | Market regime classification |
| `entry_price` | float | trade record | Entry price (BTC) |
| `exit_price` | float | trade record | Exit price (BTC) |
| `entry_ts` | float (unix seconds) | trade record | Entry timestamp |
| `exit_ts` | float (unix seconds) | trade record | Exit timestamp |
| `max_seen` | float | trade record | Highest price during hold |
| `min_seen` | float | trade record | Lowest price during hold |
| `net_pnl` | float | trade record | Net profit after fees/slippage (BTC) |
| `gross_pnl` | float | trade record | Gross profit before fees (BTC) |
| `fee_cost` | float | trade record | Total fee cost (BTC) |
| `slippage_cost` | float | trade record | Slippage cost (BTC) |
| `exit_reason` or `close_reason` | string | trade record | Why trade closed (SCRATCH, STAGNATION, TP, SL, etc.) |
| `outcome` or `result` | string | trade record | WIN, LOSS, or FLAT |

### Derived Fields (CALCULATED LOCALLY)

```
MFE = (max_seen - entry_price) / entry_price * 100  (for LONG side)
    = (entry_price - min_seen) / entry_price * 100  (for SHORT side)

MAE = (entry_price - min_seen) / entry_price * 100  (for LONG side)
    = (max_seen - entry_price) / entry_price * 100  (for SHORT side)

Entry-vs-Exit Diagnosis:
  IF MFE > 0: Entry produced favorable movement
  IF MFE <= 0: Entry produced no favorable movement (entry failed)
  
  IF MFE exists AND exit_reason in [SCRATCH, STAGNATION]:
    AND MFE > threshold: Exit killed a winner (exit failed)
    AND MFE < threshold: Entry failed, exit correct
```

---

## Storage Model Assessment

### Evidence for Storage Model

**Likelihood: ONE DOCUMENT PER TRADE**

Evidence:
1. **Unique trade_id pattern:** Code uses `_POSITIONS[trade_id]` suggesting one-to-one mapping
2. **Exit context creation:** `exit_attribution.py` builds a single context dict per closed trade (not bulk aggregation)
3. **Query patterns:** No aggregation queries found; instead individual trade reads
4. **Firestore best practice:** Standard pattern for time-series financial data

**If true:** Validating 100 canonical trades requires up to 100 document reads

### Alternative: AGGREGATE DOCUMENTS

**Less likely but possible:**
- Trades batched by date, symbol, or regime
- Each document contains multiple trades
- Would reduce document reads significantly

**Evidence against:** 
- No bulk array queries found in code
- Exit attribution builds individual contexts
- Firebase client caching patterns suggest individual document access

**Conclusion:** Assume one-per-document for budget; verify in approval.

---

## Paper Training Trade Isolation

### D_NEG_EV_CONTROL Shadow Rows

From prior context (Phase 1A corrections):
- Shadow/diagnostic rows exist for negative-EV exploration
- Must NOT be mixed with canonical economic analysis
- Collection: Likely separate or flagged with `training_bucket="D_NEG_EV_CONTROL"`

### B_RECOVERY_READY Diagnostic Rows

From Phase 1A research:
- Recovery signal diagnostics
- Should be kept separate or filtered by label

### C_WEAK Canonical Learning Rows

From code comments:
- Post-fix canonical learning trades
- Separate analysis population if retrieved

**Filter Strategy:**
```
FOR CANONICAL ECONOMIC ANALYSIS:
  WHERE outcome in (WIN, LOSS)  // Skip FLAT
  AND training_bucket NOT IN (D_NEG_EV_CONTROL, B_RECOVERY, etc.)
  AND status = "closed"
  AND created_ts OR exit_ts >= [30 days ago]  // Recent 100 trades

FOR DIAGNOSTIC-ONLY ANALYSIS (SEPARATE):
  WHERE training_bucket in (D_NEG_EV_CONTROL, B_RECOVERY_READY)
  Keep separately labelled, do NOT aggregate into economic population
```

---

## Available Local Data

### From Grep Search Results

**Found in source:**
- `exit_attribution.py`: Full exit context structure with fee/slippage/mfe/mae (lines 97-146)
- `paper_trade_executor.py`: MFE/MAE calculation and max_seen/min_seen tracking (lines 920-2225)
- `app_metrics_contract.py`: Outcome classification and profit extraction (lines 67-162)
- `canonical_metrics.py`: PF, WR, expectancy formulas (lines 103-256)

**What this means:**
- Code is calculating all required fields locally
- If these fields are persisted to Firebase, Firebase read can retrieve complete MFE/MAE data
- If fields are NOT stored, may need price-path reconstruction instead

### Local Export Availability

**Assessed:** `data/research/` outputs exist but are summary aggregates only
- No raw trade-level exports with MFE/MAE found locally
- May exist in logs but would require log analysis
- Likely faster to read from Firebase if available

---

## Conclusion: What Firebase Read Will Discover

**Required discovery step before final approval:**

1. **Does `canonical_closed_trades` collection exist?**
   - Location: Collection path and document structure

2. **Which fields are actually stored?**
   - Have `max_seen` and `min_seen` been persisted? (required for MFE/MAE)
   - Or must they be recalculated from price history?

3. **What is the document count for 100 canonical trades?**
   - One-per-document: ~100 reads
   - Aggregated: ~5-10 reads

4. **Are shadow/diagnostic rows filtered by code or label?**
   - Can we query "NOT D_NEG_EV_CONTROL" in-database?
   - Or must we post-filter in code?

**Next step:** Create exact read approval request that will answer these questions.
