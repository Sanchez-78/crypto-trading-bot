# Missing Data Required for Definitive Analysis

**Current Status:** Analysis conducted with snapshot-only data. This document enumerates data gaps preventing 100% certainty.

---

## Critical Data Gaps (Required for FINAL Pivot Decision)

### 1. Trade-Level Gross Move Data (CRITICAL)

**What:** For each of 100 canonical closed trades, export:
- entry_price
- exit_price  
- highest_price_reached (during hold)
- lowest_price_reached (during hold)
- tick_count (number of 1-sec intervals held)

**Why:** Enables calculation of:
- Gross move (before fees): (highest - entry) / entry if profitable side
- Maximum Favorable Excursion (MFE): best price vs entry
- Maximum Adverse Excursion (MAE): worst price vs entry
- Actual hold duration (vs configured timeout_s)

**Impact:** Answers "Were SCRATCH_EXIT trades killed at loss when they had favorable excursion?"

**Falsifies:** H3 (exits destroying winners) if MFE analysis shows:
- High % of SCRATCH trades had MFE > TP level (exits too early)
- Or low % had any positive MFE (exits correctly closed non-starters)

**Current Status:** Not available (would require Firestore export)

---

### 2. Firebase Trade Reconciliation (CRITICAL)

**What:** Direct export from Firestore `canonical_closed_trades` collection with full record integrity:
```
SELECT 
  trade_id, symbol, side, entry_ev, actual_move_pct,
  exit_reason, result, profit, entry_ts, exit_ts, regime
FROM canonical_closed_trades 
WHERE entry_ts > 321f10b_commit_time
LIMIT 100
```

**Why:** Verify snapshot data matches Firebase primary source.

**Impact:** Answers "Is dashboard/snapshot data correct or corrupted?"

**Falsifies:** H5 (data-scope mismatch) if:
- Firebase shows 100 trades matching snapshot breakdown, OR
- Firebase shows 7707 different trade population

**Current Status:** Not available (would require Hetzner server access)

---

### 3. Regime × Symbol × Side Breakdown (CRITICAL for slice analysis)

**What:** For each canonical trade, extract:
- regime (BULL_TREND, BEAR_TREND, RANGING, HIGH_VOL, etc.)
- side (BUY / SELL)
- Outcome (WIN / LOSS / FLAT)

**Why:** Enables analysis of H4 (edge in small slice).

**Impact:** Calculates sub-portfolio PF and WR by regime.

**Example findings that would shift decision:**
- BTC_BULL_BUY: 12 trades, PF=1.8, WR=67% → HIGH confidence in slice
- BTC_BEAR_SELL: 8 trades, PF=0.3, WR=25% → LOW confidence
- ALL_REGIMES negative → confirms H1 (no edge anywhere)

**Falsifies:** H4 (small slice edge) if:
- All regime slices < 1.0 PF, OR
- One slice > 1.2 PF with n > 30 samples

**Current Status:** Not available (snapshot lacks regime field)

---

### 4. MFE/MAE Distribution (HIGH VALUE)

**What:** For each trade:
- MFE % = (highest_during_hold - entry_price) / entry_price
- MAE % = (lowest_during_hold - entry_price) / entry_price
- Exit PnL %

**Why:** Enables exit policy audit.

**Impact:** Answers "Are exits killing winners or cutting losses correctly?"

**Example analysis:**
- If SCRATCH_EXIT trades avg MFE = +0.5%, MAE = -0.3%, exit_pnl = -0.2%:
  → Exits allowed winners to turn negative (exit too late or too loose)
- If SCRATCH_EXIT trades avg MFE = -0.05%, MAE = -0.2%, exit_pnl = -0.1%:
  → Exits correctly cut micro-losses before they worsened

**Falsifies:** H3 (exits destroying winners) if:
- 60%+ of LOSS trades had MFE > exit_pnl (killed winners)
- Vs current hypothesis: 60%+ had MFE < 0 (never had a winner)

**Current Status:** Not available (requires trade price history)

---

### 5. Entry EV Correlation Analysis (MEDIUM VALUE)

**What:** For each trade, record:
- entry_ev (canonical value used for decision)
- realized_move_pct (actual directional move achieved)
- holds actual profitability

**Why:** Determines if entry EV calibration is predictive.

**Impact:** Answers "Does higher EV lead to higher profitability?"

**Example finding:**
- EV 0.035–0.038: 20 trades, avg realized +0.2%, WR 45%
- EV 0.030–0.033: 30 trades, avg realized -0.1%, WR 20%
  → EV calibration IS predictive → H2/H3 more likely than H1

- If all EV quintiles show WR ≈ 11%:
  → EV calibration is NOT predictive → H1 confirmed

**Falsifies:** H1 (no directional edge) if:
- High EV trades significantly outperform low EV trades
- Even if portfolio net is negative, signal gradient would be evident

**Current Status:** Not available (requires trade-level EV and realized move)

---

### 6. Time-Split Analysis (MEDIUM VALUE)

**What:** Segment 100 canonical trades into time windows:
- First 25 trades (earliest)
- Trades 26–50
- Trades 51–75
- Last 25 trades (most recent)

For each window: calculate PF, WR, net PnL.

**Why:** Detects performance trend or model decay.

**Impact:** Answers "Is the strategy improving or deteriorating?"

**Example findings:**
- Early trades: PF 1.5, WR 60% (positive)
- Recent trades: PF 0.3, WR 5% (collapsed)
  → Model decay or regime shift → Justifies fresh calibration

- All windows PF 0.4–0.5, WR 10–12%:
  → Consistent negative results → Problem is structural, not temporal

**Falsifies:** H1 (no edge) if:
- Early trades are positive and recent are negative
- Suggests edge existed and decayed, not that edge never existed

**Current Status:** Not available (snapshot lacks timestamp ordering)

---

### 7. Post-Fix vs Pre-Fix Comparison (MEDIUM VALUE)

**What:** Separate canonical trades into:
- Trades closed BEFORE P1.1AP-J2/K/I fixes (pre-fix baseline)
- Trades closed AFTER P1.1AP-J2/K/I fixes (post-fix)

For each: calculate PF, WR, net PnL.

**Why:** Validates whether P1.1AP fixes improved edge.

**Impact:** Answers "Did recent patches help or hurt?"

**Example findings:**
- Pre-fix (n=30): PF 0.3, net -0.000080 BTC
- Post-fix (n=70): PF 0.6, net -0.000160 BTC
  → Fixes made things worse (P1.1AP rollback may be warranted)

- Pre-fix: PF 0.5, net -0.000050 BTC
- Post-fix: PF 0.5, net -0.000190 BTC
  → Fixes had no impact; problem is deeper

**Falsifies:** "Fixes are helping" if:
- Post-fix subset is positive or significantly less negative

**Current Status:** Not available (snapshot lacks commit-hash fields)

---

### 8. Cost Edge Calculation Audit (MEDIUM VALUE)

**What:** For sample of 10–20 recent trades:
- entry_ev (reported)
- cost_edge_required (0.0023 BTC baseline)
- actual_cost_edge_calculated
- was trade_executed or rejected?

**Why:** Validates cost edge filter is working correctly.

**Impact:** Answers "Is cost edge filter too strict or too loose?"

**Example findings:**
- Trade: entry_ev=0.032, cost_edge_required=0.0023, actual_cost_edge=0.0001
  → Filter too strict (rejecting legitimate low-cost trades)
- All trades: actual_cost_edge >= 0.0023:
  → Filter working as designed

**Falsifies:** H2 (fees destroy edge) if:
- Cost edge filter is broken and allowing negative-cost-edge trades

**Current Status:** Not available (requires Firebase trade_calc record)

---

### 9. Dashboard Expectancy Field Reconciliation (MEDIUM VALUE)

**What:** Dashboard code inspection:
- Locate `expectancy` field calculation
- Verify: is it `sum(realized_pnl) / count` or `sum(expected_move_pct) / count`?
- Cross-reference with Firebase metric save

**Why:** Explains +0.00000146 displayed expectancy vs -0.00023955 actual net.

**Impact:** Low operational impact (display bug, not data bug), but important for audit credibility.

**Expected finding:**
- Dashboard reports "expected move %", not "realized expectancy"
- E.g., avg entry_ev = 0.0348 → displayed as expectancy = +0.00000348
- Confusion between forward and backward metrics

**Falsifies:** "Dashboard metrics are corrupted" if:
- Expectancy calculation is undefined or clearly wrong

**Current Status:** Suspected (can be resolved by code inspection)

---

## Data Availability Timeline

| Data Source | Effort | Timeline | Blocker? |
|---|---|---|---|
| Trade-level gross moves | Firebase export | 30 min | YES (critical for MFE) |
| Firebase reconciliation | Server access + query | 20 min | YES (validates snapshot) |
| Regime/symbol/side breakdown | Spreadsheet analysis | 15 min | YES (falsifies H4) |
| MFE/MAE calculation | Custom script | 30 min | MEDIUM (falsifies H3) |
| EV correlation | Pandas analysis | 20 min | MEDIUM (falsifies H1) |
| Time-split analysis | Spreadsheet | 10 min | MEDIUM (trend analysis) |
| Post-fix comparison | Commit history + join | 30 min | MEDIUM (validation audit) |
| Cost edge audit | Firebase query | 15 min | LOW (validation) |
| Dashboard code inspection | Read metrics_engine.py | 10 min | LOW (backlog) |

---

## Recommended Data Collection Order

### Phase 1 (Mandatory for Final Verdict): 90 min
1. **Firebase reconciliation** (20 min) → validates snapshot is accurate
2. **Trade-level gross moves** (30 min) → enables MFE/MAE analysis
3. **Regime × symbol × side breakdown** (15 min) → tests H4 (small slice edge)
4. **MFE/MAE calculation** (30 min) → tests H3 (exits destroying winners)

### Phase 2 (Recommended for Robustness): 90 min
5. **EV correlation analysis** (20 min) → tests H1 signal quality
6. **Time-split analysis** (10 min) → detects trend/decay
7. **Post-fix vs pre-fix comparison** (30 min) → validates P1.1AP fixes
8. **Cost edge audit** (15 min) → validates cost structure

### Phase 3 (Backlog): 10 min
9. **Dashboard expectancy field inspection** (10 min) → resolves display inconsistency

---

## Current Analysis Confidence

**With snapshot data only:**
- H1 (no entry directional edge): **85% confidence** ← Can proceed with ABANDON decision
- H5 (data mismatch): **45% confidence** ← Need Firebase reconciliation
- H2 (weak gross edge + fees): **40% confidence** ← Need gross move data
- H4 (edge in slice): **20% confidence** ← Need regime breakdown

**Overall assessment:** Can proceed with ABANDON recommendation at 85% confidence on PRIMARY failure mode. Recommend Phase 1 data collection before final authorization of strategy pivot.

---

## Data Collection Authority

To collect Phase 1 data (Firebase read-only exports), requires:
- Hetzner server access credentials
- Firebase project read permission
- 90 minutes uninterrupted access

**Current status:** Not available from development environment. Requires separate session with production server access.

---

## Fallback: Proceed Without Full Data?

**If Phase 1 data cannot be obtained:**

Current snapshot analysis is sufficient to recommend:
- **H1 (no entry edge) is PRIMARY failure mode** at 85% confidence
- **ABANDON current signal architecture** (not a recoverable parameter-tuning issue)
- **Design new entry signal logic** before considering any new strategy iteration

The missing data would only shift recommendation from ABANDON to ONE SPECIFIC PIVOT if:
- (Very unlikely) MFE analysis shows exits destroying winners
- (Very unlikely) EV correlation shows signal is predictive but volume/cost destroyed edge
- (Very unlikely) Time-split shows early trades were positive and recent decayed

None of these are probable given 81% non-move rate.

---

**Conclusion:** Proceed with PIVOT DECISION based on current analysis. Flag missing data as secondary refinement effort.
