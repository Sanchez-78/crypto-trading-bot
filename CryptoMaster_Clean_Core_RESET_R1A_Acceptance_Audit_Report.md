# CryptoMaster Clean Core RESET R1A Acceptance Audit Report

## Verdict
**FAIL_R1_ELIGIBILITY_CONTRACT**

---

## Commit Decision
**DO NOT COMMIT / DO NOT PUSH / DO NOT DEPLOY**

---

## Candidate Identity

| Item | Evidence |
|---|---|
| **Base commit** | main (b6311c2) |
| **Current branch** | main (no branch switch) |
| **R1 committed?** | **NO** — all clean_core/ and tests/clean_core/ are untracked (??) |
| **New files** | 14 clean_core modules, 6 test files = 20 new files total |
| **Legacy files touched?** | NO — start.py, main.py, src/services/ all untouched |

Status: ✅ Isolation from legacy code confirmed (no active files modified)

---

## Gate A — Routes and Source Identity

### Routes Output Verification

| Route | URL Path | Expected Category | Reported execution_truth_class | rpi_visibility | PASS/FAIL |
|---|---|---|---|---|---|
| depth(100ms) | `btcusdt@depth@100ms` | `/public` | `futures_public_book_measured` | False | ✅ PASS |
| bookTicker | `btcusdt@bookTicker` | `/public` | `futures_public_book_measured` | False | ✅ PASS |
| mark_price(1s) | `btcusdt@markPrice@1000ms` | `/market` | `futures_rpi_aware_measured` | True | ❌ **FAIL** |
| agg_trade | `btcusdt@aggTrade` | `/market` | `futures_public_book_measured` | False | ✅ PASS |

### Gate A Verdict: **PARTIAL FAIL**

**Critical defect identified:**

`mark_price_stream()` incorrectly reports `execution_truth_class=FUTURES_RPI_AWARE_MEASURED` and `rpi_visibility=True`.

**Audit contract requires:**
- markPrice@1s is `/market` stream (telemetry for funding rates only, not execution fill basis)
- RPI-aware depth would be a separate stream: `<symbol>@rpiDepth@500ms` (not implemented, correctly excluded)
- markPrice should NOT be tagged with `FUTURES_RPI_AWARE_MEASURED`

**Current code (binance_usdm_routes.py lines 89-101):**
```python
stream_name = f"{symbol.lower()}@markPrice@{update_speed_ms}ms"
url_path = f"{self.base_url}/ws/{stream_name}"

identity = MarketSourceIdentity(
    ...
    execution_truth_class=ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED,  # WRONG
    rpi_visibility=True,  # WRONG
    ...
)
```

**Impact:** markPrice stream is misclassified, confusing telemetry source with execution truth class.

---

## Gate B — Eligibility and RPI Contract

### Docstring vs Implementation Contradiction

**File: src/clean_core/provenance/eligibility.py (lines 30-38)**

Docstring declares:
```python
"""
Rules:
- Only FUTURES_RPI_AWARE_MEASURED outcomes eligible for canonical/readiness learning
```

**But actual code (lines 91-96):**
```python
if execution_truth == ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED.value:
    # Public book without RPI is measurable but not full readiness
    return LearningEligibility(
        eligible=True,  # ← contradicts docstring
        reason=LearningEligibility.VALID_CLEAN_FUTURES,
    )
```

### Accounting Readiness Eligibility Issue

**File: src/clean_core/execution/paper_accounting.py (lines 116-119)**

```python
readiness_eligible = (
    entry_fill.execution_truth_class == ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED
    and exit_fill.execution_truth_class == ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED
)
```

**Problem:** `readiness_eligible` is **ONLY True for FUTURES_RPI_AWARE_MEASURED**, meaning:
- FUTURES_PUBLIC_BOOK_MEASURED outcomes are **NOT readiness eligible** (field = False)
- Test 11 (test_accounting.py) uses FUTURES_PUBLIC_BOOK_MEASURED but **never asserts readiness_eligible value**
- Test 14 only tests FUTURES_RPI_AWARE_MEASURED (which correctly is readiness eligible)

**Audit contract requires (lines 173-175 of audit spec):**
```
Is `FUTURES_PUBLIC_BOOK_MEASURED` eligible for clean PAPER accounting when tape is synced/valid? | YES | ... | ... |
```

**Observed behavior:**
- `LearningEligibilityResolver.resolve()` returns `eligible=True` for FUTURES_PUBLIC_BOOK_MEASURED ✅
- BUT `ClosedPaperOutcome.calculate_from_fills()` sets `readiness_eligible=False` for FUTURES_PUBLIC_BOOK_MEASURED ❌

### Semantic Ambiguity

Two different "eligible" fields with different meanings:

| Field | Class | True when | Purpose |
|---|---|---|---|
| `LearningEligibility.eligible` | LearningEligibilityResolver result | FUTURES_PUBLIC_BOOK_MEASURED OR FUTURES_RPI_AWARE_MEASURED | "Can this be used for clean learning?" |
| `ClosedPaperOutcome.readiness_eligible` | ClosedPaperOutcome attribute | FUTURES_RPI_AWARE_MEASURED ONLY | "Can this inform REAL readiness?" |

**This is confusing:** both suggest eligibility but mean different things. R1 baseline should allow FUTURES_PUBLIC_BOOK_MEASURED for learning/accounting, just not for REAL readiness qualification.

### Gate B Verdict: **FAIL_R1_ELIGIBILITY_CONTRACT**

**The core contract violation:** R1 baseline cannot accept its own standard observation (FUTURES_PUBLIC_BOOK_MEASURED from public /depth and /bookTicker) as readiness_eligible, but the audit contract explicitly requires this to be accepted for "clean PAPER accounting."

---

## Gate C — Local Book Integrity

### Sequence Validation Implementation

**File: src/clean_core/market/local_book.py (lines 115-137)**

Validation rules observed:
```python
# Check previous_final_id continuity (line 127-131)
if event.previous_final_id is not None:
    if event.previous_final_id != self.last_update_id:
        → GAP_DETECTED

# Check first_update_id continuity (line 133-137)
if event.first_update_id != (self.last_update_id + 1):
    → GAP_DETECTED
```

**Audit spec requirements (lines 202-209):**
- ✅ Initial REST snapshot
- ✅ u < lastUpdateId events discarded
- ✅ First applied event: U <= lastUpdateId <= u
- ✅ Subsequent event: pu == previous u
- ✅ Gap sets GAP_DETECTED
- ✅ Zero quantity removes price level (lines 144-150)

### Zero-Quantity Removal

**File: src/clean_core/market/local_book.py (lines 144-156)**
```python
if qty == 0:
    # Deletion
    if price == self.best_bid:
        self.best_bid = None
```

**Tests:**
- test_7: event application updates book ✅
- Test does NOT explicitly test zero-qty removal (removal tested implicitly via best_bid update)

### Gate C Verdict: **PASS**

Sequence integrity is correctly implemented. Zero-quantity removal is present but not explicitly unit-tested (implicit test coverage sufficient).

---

## Gate D — Accounting Truth

### Fill Observation Structure

**File: src/clean_core/execution/paper_accounting.py (lines 9-42)**

Explicit fields:
```python
touch_price: float     # best bid/ask at decision
fill_price: float      # actual execution
slippage_bps: float    # (fill_price - touch_price) / touch_price * 10000
```

**Verification:**
- ✅ BUY fill = ask + explicit slippage only (no extra half-spread added)
- ✅ SELL fill = bid - explicit slippage only
- ✅ Mark price is NOT fill price
- ✅ Slippage is signed and separate from touch price

### Fee Schedule

**File: src/clean_core/execution/fees.py**

- ✅ Maker/taker fees in bps
- ✅ RPI fee is separate (can be positive/negative)
- ✅ Total round-trip calculated correctly

### Funding

**File: src/clean_core/execution/funding.py (lines 37-50)**

```python
@dataclass(frozen=True)
class FundingRealization:
    total_cashflow_bps: float  # signed; negative = cost, positive = rebate
```

- ✅ Funding is signed (negative = paid out, positive = earned)
- ✅ Reconciliation status prevents unreconciled funding from entering outcome

### Net PnL Calculation

**File: src/clean_core/execution/paper_accounting.py (lines 99-113)**

```python
gross_pnl_pct = ((exit_px - entry_px) / entry_px) * 100.0
fee_cost_pct = ((entry_fee_bps + exit_fee_bps) / 10000.0) * 100.0
funding_cost_pct = (funding_realization.total_cashflow_bps / 10000.0) * 100.0
net_pnl_pct = gross_pnl_pct - fee_cost_pct - funding_cost_pct
```

- ✅ Calculation is deterministic (no magic)
- ✅ No oracle-dependent values
- ✅ All components are explicit

### Gate D Verdict: **PASS**

Accounting truth is correctly implemented with all explicit costs and signed values.

---

## Gate E — Filesystem and Runtime Isolation

### State File Stability

**Before tests:**
```
data/paper_open_positions.json: ABSENT
server_local_backups/paper_adaptive_learning_state.json: 81743edab8970e57fda0283d8b91ad177b739456ebd1f50f30f40c9a4adad2a9
```

**After running all 23 tests:**
```
data/paper_open_positions.json: ABSENT
server_local_backups/paper_adaptive_learning_state.json: 81743edab8970e57fda0283d8b91ad177b739456ebd1f50f30f40c9a4adad2a9
```

**Result:** ✅ **IDENTICAL HASHES** — Zero writes to production state

### Legacy Import Verification

Grep for Firebase, legacy services, start.py:
```
firebase: NOT FOUND in any clean_core module ✅
paper_adaptive_learning: NOT FOUND ✅
market_stream: NOT FOUND ✅
start.py: NOT FOUND ✅
src.services: NOT FOUND ✅
```

Result: ✅ **ZERO legacy imports**

### Journal Isolation

Tests use `temp_dir` fixture from conftest (pytest temporary directories), not production paths.

Result: ✅ **Journal uses test isolation**

### Gate E Verdict: **PASS**

Complete isolation confirmed:
- Zero state file writes
- Zero legacy imports
- Zero service wiring
- Tests properly isolated

---

## Gate F — Test Claim Completeness

| Item | Claimed | Observed | Accurate? |
|---|---|---|---|
| **Modules** | 14 | 14 files (6 `__init__.py` + 8 functional) | ✅ YES |
| **Tests** | 23 | 23 collected and passed | ✅ YES |
| **Test failure rate** | 0 | 23/23 passed | ✅ YES |
| **Legacy imports** | None | None detected | ✅ YES |
| **State file writes** | None | Hash unchanged | ✅ YES |

### Test Distribution

- test_market_routes.py: 4 tests (Gate A) ✅
- test_local_book.py: 5 tests (Gate C) ✅
- test_accounting.py: 5 tests (Gate D) ✅
- test_provenance.py: 6 tests (epoch, journal, eligibility) ✅
- test_non_wiring.py: 3 tests (isolation) ✅

**Note:** Test 11 uses FUTURES_PUBLIC_BOOK_MEASURED but does NOT assert `readiness_eligible` value. This is a test gap related to Gate B defect (FUTURES_PUBLIC_BOOK_MEASURED readiness ambiguity).

### Gate F Verdict: **PASS**

Scope claims are accurate. All 23 tests pass. Minor test coverage gap in test 11 (missing readiness_eligible assertion for PUBLIC_BOOK_MEASURED case).

---

## Critical Defect Summary

### Defect 1: mark_price_stream() Misclassification (Gate A)

**File:** src/clean_core/market/binance_usdm_routes.py (lines 89-101)  
**Severity:** HIGH  
**Issue:** markPrice@1s stream tagged as `FUTURES_RPI_AWARE_MEASURED`, but markPrice is telemetry-only, not execution truth

**Impact:** If markPrice data is used for fill calculations (incorrectly), it would be misclassified as RPI-aware when it is not.

### Defect 2: FUTURES_PUBLIC_BOOK_MEASURED Readiness Eligibility (Gate B)

**Files:**
- src/clean_core/execution/paper_accounting.py (lines 116-119)
- src/clean_core/provenance/eligibility.py (docstring lines 30-38)

**Severity:** CRITICAL  
**Issue:** R1 baseline requires FUTURES_PUBLIC_BOOK_MEASURED to be eligible for clean PAPER accounting. But:
1. `readiness_eligible` field is **False** for FUTURES_PUBLIC_BOOK_MEASURED (accounting.py)
2. Docstring claims "Only FUTURES_RPI_AWARE_MEASURED eligible" (eligibility.py)
3. This violates audit contract (lines 173-175 of spec)

**Impact:** FUTURES_PUBLIC_BOOK_MEASURED observations (standard Futures public /depth and /bookTicker) cannot be used for readiness qualification under R1 baseline. This breaks the entire R1 foundation, which should accept standard public Futures data.

---

## Exact Narrow Corrections Required Before Commit

### Correction 1: Fix mark_price_stream() Source Classification

**File:** src/clean_core/market/binance_usdm_routes.py (lines 89-101)

Change:
```python
execution_truth_class=ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED,
rpi_visibility=True,
```

To:
```python
execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
rpi_visibility=False,  # RPI is not visible in standard markPrice stream
```

**Rationale:** markPrice@1s is published market data (not RPI-depth), suitable for funding rate tracking but not execution fill truth basis.

### Correction 2: Fix Readiness Eligibility for FUTURES_PUBLIC_BOOK_MEASURED

**File:** src/clean_core/execution/paper_accounting.py (lines 116-119)

Change:
```python
readiness_eligible = (
    entry_fill.execution_truth_class == ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED
    and exit_fill.execution_truth_class == ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED
)
```

To:
```python
# FUTURES_PUBLIC_BOOK_MEASURED is eligible for clean PAPER learning.
# FUTURES_RPI_AWARE_MEASURED is reserved for future high-confidence readiness.
readiness_eligible = (
    entry_fill.execution_truth_class in (
        ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
        ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED,
    )
    and exit_fill.execution_truth_class in (
        ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
        ExecutionTruthClass.FUTURES_RPI_AWARE_MEASURED,
    )
)
```

**Rationale:** R1 must accept standard Futures public book data as eligible. Legacy Spot remains excluded (LEGACY_SPOT_EXECUTION_UNVERIFIED).

### Correction 3: Fix Eligibility Docstring

**File:** src/clean_core/provenance/eligibility.py (lines 30-38)

Change docstring:
```python
"""
Rules:
- Only FUTURES_RPI_AWARE_MEASURED outcomes eligible for canonical/readiness learning
```

To:
```python
"""
Rules:
- FUTURES_PUBLIC_BOOK_MEASURED and FUTURES_RPI_AWARE_MEASURED outcomes eligible for learning
- LEGACY_SPOT_EXECUTION_UNVERIFIED marked ineligible (archived as discovery only)
```

**Rationale:** Docstring must match actual code behavior (lines 91-96 already accept PUBLIC_BOOK_MEASURED).

### Correction 4: Add Explicit Test for FUTURES_PUBLIC_BOOK_MEASURED Readiness

**File:** tests/clean_core/test_accounting.py

Add new test after test_14:

```python
def test_14b_public_book_is_readiness_eligible(self, market_source_futures, fee_schedule):
    """Test: FUTURES_PUBLIC_BOOK_MEASURED outcomes are readiness eligible for R1 baseline."""
    entry_fill = FillObservation(
        position_id="test_public",
        symbol="BTCUSDT",
        side="long",
        qty=1.0,
        touch_price=50000.0,
        fill_price=50000.0,
        midpoint=50000.0,
        spread_bps=0.0,
        slippage_bps=0.0,
        execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
        market_source=market_source_futures,
        timestamp_utc="2026-05-26T12:00:00Z",
    )

    exit_fill = FillObservation(
        position_id="test_public",
        symbol="BTCUSDT",
        side="long",
        qty=1.0,
        touch_price=50100.0,
        fill_price=50100.0,
        midpoint=50100.0,
        spread_bps=0.0,
        slippage_bps=0.0,
        execution_truth_class=ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED,
        market_source=market_source_futures,
        timestamp_utc="2026-05-26T13:00:00Z",
    )

    funding = FundingRealization(
        symbol="BTCUSDT",
        position_id="test_public",
        entry_time_utc="2026-05-26T12:00:00Z",
        exit_time_utc="2026-05-26T13:00:00Z",
        holding_hours=1.0,
        funding_payments=[],
        total_cashflow_bps=0.0,
        reconciliation_status="complete",
    )

    outcome = ClosedPaperOutcome.calculate_from_fills(
        position_id="test_public",
        epoch_id="test",
        entry_fill=entry_fill,
        exit_fill=exit_fill,
        fee_schedule=fee_schedule,
        funding_realization=funding,
        entry_time_utc="2026-05-26T12:00:00Z",
        exit_time_utc="2026-05-26T13:00:00Z",
        holding_minutes=60.0,
    )

    # PUBLIC_BOOK_MEASURED should be readiness eligible for R1 baseline
    assert outcome.readiness_eligible is True
    assert outcome.execution_truth_class == ExecutionTruthClass.FUTURES_PUBLIC_BOOK_MEASURED
```

**Rationale:** Explicitly test that R1 baseline accepts FUTURES_PUBLIC_BOOK_MEASURED for readiness (not just learning eligibility).

---

## Forbidden Changes

✅ **Confirmed to be absent:**
- ❌ No strategy/signal generation
- ❌ No admission policy
- ❌ No legacy EV gate bypass
- ❌ No Firebase imports
- ❌ No service wiring
- ❌ No deployment

---

## Next Action

**DO NOT implement corrections in this session.** Once this audit is reviewed by operator:

1. **Operator approval required:** Corrections are minimal (4 narrow changes: 1 route, 1 accounting eligibility rule, 1 docstring, 1 new test)
2. **Create separate correction prompt** after operator acknowledges Gate B violation
3. **Rerun full audit** after corrections applied
4. **Only then** proceed to commit

---

## Audit Metadata

| Item | Value |
|---|---|
| **Audit Date** | 2026-05-26 |
| **Auditor** | Automated acceptance gate |
| **Candidate Status** | UNCOMMITTED (all files ??) |
| **Git Status** | No active files modified |
| **Isolation Status** | ✅ VERIFIED (zero production writes) |
| **Test Status** | 23/23 passing |
| **Critical Defects** | 2 (Gate A, Gate B) |
| **High-Priority Gates Passed** | C, D, E, F |
| **Ready for Commit** | ❌ NO (must fix Gate A + B first) |

---

## Summary

**Clean Core RESET R1A foundation is technically sound in architecture and isolation, but contains two critical source-classification defects that violate the R1 baseline contract:**

1. **mark_price_stream()** misclassifies /market telemetry as FUTURES_RPI_AWARE_MEASURED (should be PUBLIC_BOOK_MEASURED)
2. **ClosedPaperOutcome.calculate_from_fills()** incorrectly marks FUTURES_PUBLIC_BOOK_MEASURED as NOT readiness-eligible, violating the audit contract that R1 baseline must accept standard Futures public book data

**All corrections are narrow (4 line-count-limited changes) and do not require architectural rework.**

Once corrected and re-audited, R1A foundation will be ready for commit.

---

**Verdict: FAIL_R1_ELIGIBILITY_CONTRACT**

**Decision: DO NOT COMMIT / DO NOT PUSH / DO NOT DEPLOY**
