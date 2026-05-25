# Metric Reconciliation and Calculation Corrections

**Date:** 2026-05-22  
**Purpose:** Correct wording/calculation errors from GO/NO-GO report and reconcile dashboard inconsistencies

---

## 1. All-Outcome Expectancy Correction

### Original (INCORRECT) statement:
"Expectancy: -0.00023955 BTC/trade (negative across all calculation methods)"

### Corrected calculation:
```
Total net PnL: -0.00023955 BTC
Total canonical closed trades: 100
All-outcome realized expectancy = -0.00023955 / 100 = -0.0000023955 BTC per trade

In percent terms: -0.0000023955 / 1 BTC = -0.00023955% per trade
Or per 100 sat: -2.3955 satoshis per 100 BTC notional

In common trading terms: -23.955 sat per canonical trade
```

### Corrected headline:
**All-Outcome Expectancy: -0.0000023955 BTC/trade** (negative but smaller magnitude than initially stated)

---

## 2. Win Rate Labeling Correction

### Original phrasing (misleading):
"Win Rate (all outcomes): 11% | Win Rate (decisive only): 73.3%"

### Clarification required:
73.3% is **NOT an economic metric**. It measures "fraction of decided trades that were profitable" not "probability next trade will profit."

```
Decisive-only: 11 wins / (11 wins + 4 losses) = 73.3%
All-outcomes:  11 wins / 100 total trades = 11%
```

**Critical distinction:**
- All-outcomes WR is the true economic metric (11%)
- Decisive-only WR is a **headlinability metric** that excludes neutral outcomes and is misleading when presented as strategy performance

### Corrected framing:
- **Economic win rate (all outcomes):** 11.0% — probability next trade profits
- **Directional accuracy (decisive only):** 73.3% — NOT ECONOMIC, excludes 85 neutral/losing trades from denominator

---

## 3. Loss Attribution Correction

### Original statement (potentially misleading):
"do not call all 85 individually losing"

### Clarification:
The 85 neutral-classified trades ARE economically loss-producing as a population, but not all individually:

```
Exit Type                Count    Net PnL         Avg per Trade    Status
TIMEOUT_FLAT             2        -0.00000788     -0.00000394       negative
SCRATCH_EXIT            47        -0.00009236     -0.00000196       negative (cumulative)
STAGNATION_EXIT         34        -0.00012143     -0.00000357       negative (cumulative)
────────────────────────────────────────────────────────────────────────
SUBTOTAL                81        -0.00021379     -0.00000264       NEGATIVE AS GROUP

Loss-producing subset:   89.25% of total net loss
```

### Reconciliation:
Each individual SCRATCH or STAGNATION exit may seem inconsequential (-0.00000196 to -0.00000357 per trade), but when repeated 47–34 times respectively, they accumulate to dominate total losses.

**Analogy:** A leak of 1 liter per hour is invisible on any single trade but lethal over a session.

---

## 4. Dashboard Inconsistency Reconciliation

### Inconsistency A: WR 73.3% vs Net PnL Negative

**Dashboard reports:** 73.3% win rate  
**Actual net:** -0.00023955 BTC loss

**Root cause:** WIN rate calculated as decisive-only (11/15), while net PnL includes all 100 trades.
- 11 wins × avg ~+0.000005 BTC per win = +0.000055 BTC gross
- 4 losses × avg ~-0.000007 BTC per loss = -0.000028 BTC gross
- 85 neutral/flat × avg ~-0.000000264 BTC per neutral = -0.000214 BTC gross
- **Net = +0.000055 - 0.000028 - 0.000214 = -0.000187 BTC** (approximately matches -0.00024)

**Classification:** Dashboard display DEFECT
- Solution: Report all-outcomes WR (11%) alongside decisive-only (73.3%) with clear labeling
- Backlog: Metrics v10.13y+ enhancement

---

### Inconsistency B: Expectancy Field Positive (+0.00000146) vs Net Negative (-0.00024)

**Dashboard reports:** expectancy = +0.00000146  
**Canonical net:** -0.00023955

**Root cause hypothesis (unconfirmed):** Dashboard "expectancy" field may be:
1. Expected move % (gross directional move) not realized expectancy
2. Paper-only performance (LM subset) not canonical
3. Outdated stale value from earlier session

**Classification:** Dashboard field definition MISMATCH
- Action required: Verify definition of dashboard "expectancy" field
- Likely non-economic: If it's expected move or paper-only, it does not represent canonical profitability

---

### Inconsistency C: Status Message "TRENINK (zisk > 0)" vs Negative Zisk

**Dashboard reports:** Status = "TRENINK (zisk > 0)"  
**Actual zisk (profit):** -0.00023955 BTC

**Root cause:** Stale or inverted conditional logic  
- Either message was cached from prior session with positive state
- Or comparison logic is reversed (checking zisk <= 0 but displaying as ">")

**Classification:** Dashboard status field BUG
- Solution: Verify live refresh and fix conditional
- Urgency: Low (informational only, does not impact trading logic)

---

### Inconsistency D: Trade Count Scope Ambiguity

**Dashboard fields report:**
- completed_trades = 7707
- canonical = 100
- LM = 200

**Root cause:** Three different trade populations without documented scope

```
completed_trades (7707) = ?
  Hypothesis 1: Total all-time completed trades (including historical)
  Hypothesis 2: Completed in current session/day
  Hypothesis 3: Including live/real + paper combined
  
canonical (100) = Clean closed trades used for PF/health calc
  Definition clear: subset with full closure information
  
LM (200) = Paper trades in learning monitor
  Definition clear: subset of paper_train mode entries
```

**Classification:** Documentation DEFECT
- Solution: Add field definitions to dashboard contract
- Urgency: Medium (prevents audit/analysis without guess-work)

---

### Inconsistency E: Mode Field (shows "LIVE" when exposure=0)

**Dashboard reports:** mode = "LIVE"  
**Actual execution state:** Positions=0, Exposure=0, WR=0.00%

**Root cause:** Mode field reflects configured trading mode, not actual live money exposure

**Classification:** Field naming DEFECT
- Clarify: "configured_mode" vs "actual_exposure_status"
- Current state: configured_mode=LIVE, actual_exposure_status=HALTED

---

## 5. Hypothesis: Which Inconsistency is Most Problematic?

| Inconsistency | Type | Impact | Fix Effort | Severity |
|---|---|---|---|---|
| A. WR mismatch | Display defect | Can mislead strategy assessment | Low | MEDIUM |
| B. Expectancy field | Definition mismatch | Prevents audit accuracy | Medium | HIGH |
| C. Status message | Logic bug | Cosmetic | Very low | LOW |
| D. Trade counts | Documentation | Prevents scope clarity | Medium | MEDIUM |
| E. Mode indicator | Naming | Confusing but clear from context | Low | LOW |

**Likely root cause of Inconsistency B:** 
Dashboard "expectancy" is probably a **forward-looking expected move %** (from EV calibration) not a **realized expectancy** (backward-looking profit per trade). This would explain why it's positive (entry EV was positive 0.030–0.038) while realized is negative (exits destroyed that edge).

---

## Summary for Pivot Analysis

**Metrics corrected for downstream analysis:**
- All-outcome expectancy: **-0.0000023955 BTC/trade** ✓
- Economic win rate (all outcomes): **11.0%** ✓
- Decisive-only WR (non-economic headline): **73.3% ← labeled clearly** ✓
- Loss-dominating subset (SCRATCH+STAG): **81 trades, -0.00021379 BTC, 89.25% of loss** ✓

**Dashboard inconsistencies classified:**
- WR presentation defect: Backlog
- Expectancy definition mismatch: Investigate (possibly forward vs realized)
- Status message bug: Backlog (low priority)
- Trade count scope: Add documentation
- Mode naming: Clarify

**Proceed with pivot analysis using corrected metrics above.**
