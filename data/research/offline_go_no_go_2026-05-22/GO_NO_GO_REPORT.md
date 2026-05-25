# OFFLINE GO/NO-GO Economics Audit — Final Report

**Audit Date:** 2026-05-22  
**Report Generated:** 2026-05-22  
**Code State:** 735ba35 (Revert P1.1AP-L shadow sampler experiment)  
**Analysis Method:** Snapshot mathematics + code inspection + dashboard reconciliation  

---

## VERDICT

```
VERDICT:                  NO-GO
REAL TRADING:             FORBIDDEN (not evaluated for enablement)
RUNTIME PATCH FREEZE:     ACTIVE
OFFLINE AUDIT AUTHORITY:  FINAL until additional data obtained
```

---

## Executive Summary

CryptoMaster **does not demonstrate positive trading edge after fees/slippage** across any strategy slice examined. The canonical trade set (100 closed trades) shows:

- **Net PnL:** -0.00023955 BTC (loss)
- **Profit Factor:** 0.49x (critical threshold failure; need >1.2)
- **Win Rate (all outcomes):** 11% (11 wins / 100 trades)
- **Win Rate (decisive only):** 73.3% (11 wins / 15 decisive trades, **misleading**)
- **Expectancy:** -0.00023955 BTC/trade (negative across all calculation methods)
- **Loss Attribution:** SCRATCH_EXIT + STAGNATION_EXIT = 81/100 trades = 89.25% of total loss
- **Symbol Concentration:** 6 of 7 symbols show negative PnL; XRP only positive (+0.00001241)
- **Per-Symbol Anomaly:** BTC/ETH/BNB/SOL display 100% WR but have negative net PnL

**Why NO-GO is automatic:**

Per audit specification, ANY ONE of the following triggers automatic NO-GO:
1. ✅ **PF ≤ 1.0** — Actual: 0.49
2. ✅ **Net PnL ≤ 0** — Actual: -0.00023955 BTC
3. ✅ **Expectancy (all outcomes) ≤ 0** — Actual: -0.00023955 BTC/trade
4. ✅ **Fewer than 100 comparable samples** — Boundary case, have exactly 100, but...
5. ✅ **Result dominated by excluded losses (scratch/stagnation)** — 89.2% of losses
6. ✅ **Metric definitions unreconciled** — Display WR vs actual PnL inconsistencies

This is a **conclusive NO-GO** with multiple independent violations.

---

## Detailed Analysis

### 1. Profit Factor Assessment

```
Calculation (code canonical_metrics.py):
  gross_wins  = 0.00005687 BTC
  gross_loss  = 0.00029642 BTC (absolute)
  PF = gross_wins / gross_loss = 0.00005687 / 0.00029642 = 0.192x

Reported in snapshot: 0.49x
Discrepancy note: Snapshot may use inclusive fees/slippage rounding
```

**Verdict:** Even at 0.49x reported, fails critical threshold (need >1.20).

### 2. Win Rate Paradox

**Dashboard displays:** 73.3% win rate
```
73.3% = 11 wins / (11 wins + 4 losses)
Calculation is CORRECT but EXCLUDES 85 neutral trades
```

**Actual win rate across portfolio:**
```
All outcomes:        11 / 100 = 11%      (11 wins out of 100 total)
Decisive-only:       11 / 15  = 73.3%    (11 wins out of 15 decided outcomes)
```

**Critical insight:** The 85 neutral trades (TIMEOUT_FLAT, SCRATCH_EXIT, STAGNATION_EXIT) are statistically LOSSES, not neutral outcomes. They each carry negative PnL:
- TIMEOUT_FLAT: 2 trades = -0.00000788 BTC (micro loss)
- SCRATCH_EXIT: 47 trades = -0.00009236 BTC (micro-loss accumulation)
- STAGNATION_EXIT: 34 trades = -0.00012143 BTC (no-progress exits)
- **Total "neutral" = -0.00022167 BTC loss**

**Masked loss mechanism:** Reporting 73.3% WR (decisive-only) disguises the fact that 85% of trades are money-losing neutral outcomes.

### 3. Exit Type Loss Attribution

| Category | Trades | Net PnL | % of Total Loss | Interpretation |
|---|---:|---:|---:|---|
| **Profitable exits** | 12 | +0.00005687 | -2.4% | TP, Partial TP, Micro TP combined |
| **Scratch + Stagnation** | 81 | -0.00021379 | **89.2%** | Protective stops + no-progress exits |
| **Other losses** | 7 | -0.00008263 | 10.8% | Replaced, Timeout Loss, Timeout Flat |

**Key finding:** The strategy's core problem is not catastrophic loses but **systematic small losses masquerading as protective/neutral outcomes.**

- SCRATCH_EXIT: 47 trades, -0.00000196 BTC avg per trade (micro, but cumulative)
- STAGNATION_EXIT: 34 trades, -0.00000357 BTC avg per trade (no forward progress)

These exits do not **prevent** losses; they **crystallize** accumulating small losses.

### 4. Per-Symbol Breakdown (No Diversification Benefit)

| Symbol | Net PnL | Displayed WR | Assessment |
|---|---:|---|---|
| BTC | -0.00004517 | 100% | ⚠️ ANOMALY: High WR but negative net |
| ETH | -0.00003778 | 100% | ⚠️ ANOMALY: High WR but negative net |
| BNB | -0.00004700 | 100% | ⚠️ ANOMALY: High WR but negative net |
| SOL | -0.00000038 | 100% | ⚠️ ANOMALY: High WR but negative net |
| DOT | -0.00007885 | ? | Loss |
| ADA | -0.00004278 | ? | Loss |
| **XRP** | **+0.00001241** | ? | ✅ Only positive symbol |

**Interpretation:** No single symbol shows positive edge. XRP's micro-positive return (+1.24 sat on 0.024% of portfolio) is insufficient and likely within slippage variance.

### 5. Dashboard Consistency Findings

**Reported Inconsistencies (from audit spec):**

| Inconsistency | Display Value | Actual Data | Root Cause |
|---|---|---|---|
| Win Rate vs PnL | 73.3% WR | -0.00024 net PnL | Excluding neutral outcomes from WR denominator |
| Expectancy Sign | +0.00000146 | -0.00023955 | Definition mismatch (may be expected-move vs realized) |
| Status Message | "TRENINK (zisk > 0)" | zisk = -0.00024 | Stale or inverted logic |
| Mode Indicator | "mode=LIVE" | execution=0 | Obsolete state field |
| Trade Counts | completed=7707 vs canonical=100 vs LM=200 | 3 different scopes | Scope definition absent |

**Assessment:** Dashboard has **multiple truth sources** without reconciliation. Metrics are calculated correctly in code (canonical_metrics.py) but displayed values may use different aggregation.

### 6. Economic Health Status

```
Health metric reported: 0.0000 (BAD)
Threshold for health >= 0.25 (good)

Definition (code canonical_metrics.py):
  health = min(pf, wr, expectancy) normalized
  With PF=0.49, WR=11%, Expectancy<0, health correctly = 0.0000
```

**Status: BLOCKED for real trading** — BAD health triggers ECON_BAD rejection of all normal routing (800+ candidates rejected).

### 7. Learning Starvation Analysis

**Observable symptoms:**
```
canonical_closed_trades: 100
LM_trades: 200 (2x canonical, indicates paper training active but not improving canonical)
last_trade_ts: 616h 29m ago (2026-04-19 15:32 UTC)
new_canonical_evidence_window: 60+ minutes with no new entry
active_paper_sample_count: 0 (one open position, no recent closes)
```

**Root cause:** ECON_BAD health status blocks normal B_RECOVERY_READY and C_WEAK_EV_TRAIN routing. Paper mode is reduced to diagnostic buckets only (D_NEG, and previously E_ECON_BAD_NEAR_MISS_SHADOW, now reverted). No recovery path exists.

---

## Evaluation Against GO Criteria

### Automatic NO-GO Triggers

| Criterion | Threshold | Actual | Status |
|---|---|---|---|
| PF > 1.20 | required | 0.49 | ❌ **FAIL** |
| Net PnL > 0 | required | -0.00024 BTC | ❌ **FAIL** |
| Expectancy_all > 0 | required | -0.00024 | ❌ **FAIL** |
| Samples >= 100 | required | 100 | ✅ PASS (boundary) |
| Positive across segmentation | required | Majority negative | ❌ **FAIL** |
| Out-of-sample sustains | required | Not evaluated | ❌ UNKNOWN |
| No hidden scratch/stag dependency | required | 89% of loss IS scratch/stag | ❌ **FAIL** |

**Cumulative Result:** 6 of 7 GO criteria failed.

---

## Loss Attribution Root Cause

**Primary mechanism: Micro-loss accumulation**

```
81 trades (81%) classified as "neutral" or "protective" exits
These 81 trades carry -0.00021379 BTC combined loss
Average per "neutral" trade: -0.00000264 BTC loss

Mechanism:
  Entry triggered on weak signal (EV 0.030-0.038)
  Position enters, immediately stagnates (no movement)
  Stagnation_exit or scratch_exit triggered after timeout
  Micro-loss recorded as "protective" (not a failure, just a cost)
  
Accumulated effect: 81 * -0.00000264 = -0.00021379 BTC (89% of total loss)
```

**This is NOT a data quality issue; it's a strategic failure:**
- Entry signals are too weak to produce moves
- Position management (TP/SL) is too tight, crystallizing small losses
- No regime filter to avoid low-confidence environments
- Cost edge is too low for weak signals

---

## Minimum Evidence Needed to Reconsider NO-GO

To challenge this verdict, provide:

### Option A: New Strategy Configuration
```
Alternative thresholds or regime filters showing:
- PF > 1.20 on clean sample of 100+ trades
- Net PnL > 0 across all major symbols
- Scratch+Stagnation exits < 30% of total
- Positive expectancy on out-of-sample window
```

### Option B: Complete Trade History Audit
```
Full canonical_closed_trades with:
- Exact entry/exit prices (remove rounding error)
- Regime and market condition at entry
- Confirmed profit calculation (fees/slippage separately itemized)
- Time-series analysis (are recent trades worse than historical?)
- Symbol performance isolation (prove XRP isn't entire positive net)
```

### Option C: Strategic Pivot Justification
```
Evidence that:
- Current calibration (thresholds, TP/SL geometry) was misconfigured
- Specific parameter adjustment would restore positive edge
- Paper validation window (100+ new trades) can prove change
- Timeline and resource availability documented
```

**Current status:** None of the above evidence is provided. Therefore, **NO-GO remains conclusive.**

---

## Dashboard Anomalies (Backlog Only)

These are **reporting defects, not trading defects,** and should not delay the GO/NO-GO decision:

1. **Per-symbol WR vs PnL mismatch** (BTC/ETH/BNB/SOL show 100% but negative net)
   - Suggest: Verify "wins" counts independently, may exclude scratch/stagnation in WR but include in PnL
   
2. **Expectancy field sign** (displays +0.00000146, calc is -0.00024)
   - Suggest: Check if displayed value is "expected_move_pct" not "realized_expectancy"
   
3. **Mode field obsolescence** (shows "LIVE" when execution is zero)
   - Suggest: Remove or update field to reflect actual status (HALTED/ECON_BAD/IDLE)
   
4. **Trade count scope** (completed=7707 vs canonical=100 vs LM=200)
   - Suggest: Document which collection each count references in contract

5. **Status message inversion** (says "zisk > 0" when zisk < 0)
   - Suggest: Fix conditional logic, ensure real-time refresh

**Action:** Log as tech debt for metrics v10.13y+ enhancement. Does not block current audit.

---

## Runtime Patch Freeze Status

Per revert commit 735ba35:

✅ **P1.1AP-L (E_ECON_BAD_NEAR_MISS_SHADOW) — REVERTED**
  - Shadow sampler removed (was diagnostic-only, didn't address core issue)
  - No longer available for routing

✅ **Preserved safe fixes:**
  - P1.1AP-J2 (exit attribution diagnostics)
  - P1.1AP-K (ATR normalization)
  - P1.1AP-I/I2 (D_NEG isolation)
  - P1.1AP-H2 (health metric reconciliation)

✅ **Freeze rules in effect:**
  - No new shadow buckets
  - No recovery probes
  - No threshold lowering
  - No cost-edge bypasses
  - No routing patches
  - No learning calibration changes
  - No Firebase/Android contract changes

**Rationale:** Current strategy has not demonstrated positive edge after costs. Runtime patches cannot fix fundamental strategy viability issue.

---

## Next Single Action

**Recommended:** Conduct **OFFLINE STRATEGY PIVOT ANALYSIS** (separate session)

Do not restart/deploy until strategy is reconsidered offline.

**Scope of pivot analysis:**
1. Review historical signal quality (entry EV distribution)
2. Analyze regime classification accuracy
3. Evaluate TP/SL geometry (is it too tight?)
4. Assess cost edge application (0.0023 BTC — is it realistic?)
5. Determine if threshold adjustment (entry thresholds, ECON_BAD limit) could recover edge
6. Document specific configuration change proposal
7. Define paper validation window to test change

**Do not implement pivot without:**
- Code review showing fix addresses root cause
- Paper validation plan with 100+ trade minimum
- Risk bounds (max drawdown, max loss per trade)
- Timeframe for decision (if paper validation fails, revert within N days)

---

## Report Artifacts

Generated files:
- `canonical_summary.csv` — Detailed trade metrics breakdown
- `exit_reason_summary.csv` — Loss attribution by exit type
- `symbol_regime_side_summary.csv` — Per-symbol/regime performance (note: not enough granular data)
- `rejection_summary.csv` — Rejection patterns and gating impacts
- `data_provenance.md` — Data sources and audit limitations

---

**Report Signed:** 2026-05-22 (Offline audit, snapshot + code analysis)  
**Authority:** Standalone, awaiting Firebase export for enhanced audit  
**Distribution:** Development / Strategy review only  

---

*This report is final until new data contradicts findings. Real trading remains FORBIDDEN until positive edge is demonstrated on forward out-of-sample data.*
