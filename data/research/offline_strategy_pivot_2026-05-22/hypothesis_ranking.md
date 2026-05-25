# Strategy Pivot Hypothesis Ranking

**Objective:** Determine the primary failure mode and evaluate falsifiability of each hypothesis.

---

## Hypothesis H1: Entries Lack Directional Edge

**Statement:** Entry signals (EV calibration) do not contain genuine directional predictive power. Weak entry EV (0.030–0.038 range) reflects low confidence, and realized performance (11% WR, 89% scratch/stagnation) confirms signals are not predictive.

### Supporting Evidence:

1. **High non-move rate (81/100 trades = 81%)**
   - 47 SCRATCH_EXIT: Entry triggered, position stagnated until timeout
   - 34 STAGNATION_EXIT: No favorable move within hold window
   - Combined: 81% failure to produce directional move
   - Source: canonical_summary, exit_reason_summary

2. **Entry EV range explanation**
   - P1.1AP-L experiment post-mortem noted "weak-positive ECON_BAD rejections"
   - Threshold 0.030 (C_WEAK minimum) is below B_RECOVERY 0.038 and canonical 0.045
   - Weak EV reflects low probability of profitability (low calibration confidence)
   - Source: code specification, paper_exploration.py constants

3. **Learning feedback is frozen**
   - Canonical PF 0.49 indicates learning monitor cannot recover edge
   - Last trade 616 hours ago; starvation mode active
   - ECON_BAD health status blocks normal B/C routing
   - No recovery path exists with current entry calibration
   - Source: canonical_summary, learning_event.py analysis

4. **Positive exits (12 trades) are too few to validate opposite hypothesis**
   - Only 12 of 100 trades reached TP
   - Insufficient to claim entries contain edge and exits destroy it
   - If directional edge existed, we'd expect 30–50% move-to-TP ratio, not 12%
   - Source: exit_reason_summary

### Contradicting Evidence:

1. **PARTIAL_TP_25 and MICRO_TP generate positive PnL**
   - 12 profitable exits (net +0.00005687 BTC) shows SOME entries did work
   - Argument: If entries lacked all edge, expectation is 0 profitable exits, not 12
   - Counter: With 100-trade sample, 12 wins from 50/50 random is within ~3σ noise

2. **Possibility of regime-dependent edge**
   - Could be that certain market regimes (BULL only, or BTC+ETH only) contain edge
   - Current analysis lacks regime breakdown
   - Argument: Cannot declare "no edge" without testing all regime slices
   - Counter: Even if subset had edge, portfolio-level 11% WR is terminal; subset edge would need to overcome other losses

### Missing Data:

- Regime × symbol × side breakdown (would show if BULL_TREND has positive WR despite overall negative)
- Gross move analysis (did scratch-exit trades fail to move, or move against entry?)
- MFE/MAE distribution (what % of trades had favorable excursion > TP but exited early?)
- Entry EV vs actual realized move correlation (does higher EV lead to higher %realized profitability?)
- Time-split analysis (are recent trades worse than historical? Trend?)

### Falsification Test:

**Test A: Regime isolation**
- Extract all BULL_TREND trades → if positive PnL and WR > 50%, hypothesis weakened
- If all regimes negative, hypothesis strengthened

**Test B: Reverse backtest**
- Run model on same trades but with RANDOM entry direction (flip BUY→SELL)
- If random direction has similar PnL, entries have no directional content
- Expected for noise: random direction would yield ~0.024% loss (coin flip variance)

**Test C: Entry EV vs win rate correlation**
- Segment trades by entry EV quintiles: [0.030–0.032], [0.032–0.034], etc.
- Does higher EV → higher WR among those trades?
- If not, EV calibration is not predictive of outcome

### Confidence: **HIGH (85%)**

**Rationale:**
- 81% non-move rate is extremely strong signal
- Positive exits (12) are too few for statistical significance
- ECON_BAD health and starvation mode indicate learning model cannot recover edge
- Entry EV range (0.030–0.038) is deliberately weak range post-thresholds

**Recommendation:** Unless regime/time-split breakdown shows hidden positive subset, H1 is likely PRIMARY FAILURE MODE.

---

## Hypothesis H2: Entries Contain Weak Gross Edge But Fees/Cost Eliminate It

**Statement:** Entry signals produce small positive gross move (before fees/slippage) but cost structure (fees 0.0001–0.0002 BTC per round trip, slippage 0.00005–0.0001 BTC) eliminates the edge. Net PnL is negative due to cost structure, not signal quality.

### Supporting Evidence:

1. **12 profitable exits suggest some gross edge exists**
   - If gross edge were zero, expected winning trades ≈ 0
   - 12 wins is excess over coin-flip expectation
   - Could imply ~0.01–0.02 BTC average gross win per trade
   - But offset by 88 losses at -0.00000337 average
   - Source: exit_reason_summary

2. **Cost edge threshold (0.0023 BTC) is absolute lowest**
   - Feature in code: entry requires cost edge > 0.0023 BTC before entry
   - If threshold is too high, weak-gross-edge trades are pre-filtered
   - Cost edge = EV * position_size * (fees + slippage assumption)
   - If this filter is broken or too strict, weak edges rejected
   - Source: realtime_decision_engine.py, trade_executor.py

3. **Weak entry EV (0.030–0.038) can produce small gross moves**
   - EV is probability-weighted move estimate
   - 0.030 means "3% expected move" conditional on entry
   - 3% of position on BTCUSDT ≈ 1,350 sat
   - 3% of position on ETHUSDT ≈ 75 sat
   - After 0.0001 fee and 0.00005 slippage, 1,350 sat gross → ~800 sat net
   - Hypothesis: Many trades have 0.5–1% gross edge, but fees eliminate it

### Contradicting Evidence:

1. **SCRATCH_EXIT micro-loss is incompatible with "gross positive" claim**
   - 47 SCRATCH_EXIT trades at -0.00000196 avg each
   - Scratch exit is taken when position approaches small loss (e.g., -0.0001 BTC)
   - If entry had +1% gross edge, scratch would be hit much less frequently
   - Frequency of scratch suggests entries have NEGATIVE gross move tendency, not barely positive
   - Source: exit_attribution.py definition, exit_failure_analysis.csv

2. **If cost were the only problem, optimization should show clear threshold**
   - E.g., "trades with EV > 0.035 have positive gross, net turned negative by fees"
   - Instead, data shows 81% of ALL trades fail to move at all
   - This pattern is inconsistent with "weak but positive gross" hypothesis
   - Source: stagnation_exit high count

3. **ECON_BAD rejection of 800+ candidates indicates cost edge filter working as designed**
   - If cost edge filter were too strict, dashboard would show "stuck awaiting high-EV entries"
   - Instead, ECON_BAD (bad economic health) is the blocker
   - This means weak candidates ARE being admitted (and failing)
   - Source: specification audit context

### Missing Data:

- Gross move before fees/slippage for each trade (would directly prove/disprove hypothesis)
- Cost edge calculation used (is 0.0023 actually applied, or is it bypassed?)
- Realized vs expected move distribution (do entries produce the expected move size?)

### Falsification Test:

**Test A: Calculate gross moves**
- For each SCRATCH_EXIT trade: entry_price, lowest_price, exit_price
- Determine: did position move positively before scratch triggered?
- If yes for most scratches → gross edge exists, fees destroyed it
- If no (position immediately underwater) → no gross edge

**Test B: Cost edge audit**
- Query Firebase for sample of trades with entry_ev=0.032 and cost_edge reported
- Verify: is cost_edge actually >= 0.0023? Or is it < 0.0023 and trade still executed?
- If cost_edge filter is broken, this explains edge destruction

**Test C: Compare to fee baseline**
- Typical exchange fees: 0.0001 per round trip (taker+taker)
- Typical slippage on weak orders: 0.00005–0.0001
- Total cost drag: 0.0002–0.0002 BTC per round trip
- If average gross win = 0.0002 BTC and average loss = -0.0001 BTC, net = zero
- Check: do the 12 profitable trades average ~0.0002–0.0005 BTC? If so, consistent with hypothesis.

### Confidence: **MEDIUM (40%)**

**Rationale:**
- SCRATCH_EXIT frequency argues against this (why so many scratches if gross is positive?)
- But possible some gross edge exists and is being filtered out
- Cannot definitively rule out without gross move data

**Recommendation:** LOWER priority than H1. If H1 (no directional edge) is false, revisit H2.

---

## Hypothesis H3: Exit Policy Destroys Gross-Positive Trades

**Statement:** Entries contain meaningful directional edge (high gross move %), but exit logic (TP/SL geometry, scratch threshold, stagnation timeout) closes trades prematurely before reaching TP. Exits are destroying an otherwise viable strategy.

### Supporting Evidence:

1. **PARTIAL_TP_25 succeeds (8 trades, +0.00005131 BTC)**
   - Suggests that SOME TP target is realistic and reachable
   - Shows exit logic (TP level) is not universally wrong
   - Argument: If exit TP too tight, even partial TP would not succeed this often
   - Source: exit_reason_summary

### Contradicting Evidence:

1. **Only 12 profitable exits out of 100 trades**
   - If exits were destroying winners, expect 40–60% trades to reach TP with suboptimal exits
   - Instead, only 12% reach profitable exit
   - This pattern is incompatible with "exits destroying winners" explanation
   - Source: canonical_summary

2. **STAGNATION_EXIT dominates (34 trades, -0.00012143 BTC = 50.7% of loss)**
   - Stagnation exit: no favorable price movement within hold window
   - If position had edge, would expect some favorable excursion
   - Frequency of stagnation suggests entries lack directional content, not exit problem
   - Source: exit_reason_summary

3. **Timeout logic has protective rationale**
   - Maximum hold time prevents unlimited drawdown duration
   - Scratch threshold prevents crystallizing small permanent losses
   - These are defensive, not destructive, in context of weak-signal entries
   - Source: smart_exit_engine.py analysis

### Missing Data:

- MFE (Maximum Favorable Excursion) for each trade
- Would show: for trades exited at loss, did price ever touch a more favorable price?
- E.g., did SCRATCH_EXIT trades ever reach +0.0001 BTC favorable excursion before exiting?
- If yes, exits destroyed winners
- If no, exits correctly cut losses

### Falsification Test:

**Test A: MFE/MAE analysis**
- For each SCRATCH_EXIT, calculate:
  - MFE: best price reached during hold (did trade ever go +0.0001?)
  - MAE: worst price reached during hold
  - If MFE >> exit_pnl, exit closed winner prematurely
  - If MFE ≈ exit_pnl, trade never had the edge

**Test B: Simulated alternate exit policy**
- Rerun same 100 trades with:
  - TP moved 2x further
  - Scratch threshold moved 2x further
  - Stagnation timeout extended 2x
- If simulated trades improve to positive PnL, exits are destructive
- If simulated trades remain negative, exits are correct

### Confidence: **LOW (15%)**

**Rationale:**
- Only 12% of trades reaching TP/profit argues strongly against exits being destroyer
- Stagnation rate (34%) and scratch rate (47%) indicate lack of directional move, not premature exit
- Would require MFE data to prove, and that data is unavailable

**Recommendation:** Unlikely to be PRIMARY failure mode. De-prioritize unless MFE data becomes available.

---

## Hypothesis H4: Positive Edge Confined to Unusably Small Slice

**Statement:** Current strategy is globally negative, but a small slice (specific symbol, regime, or side) contains positive edge. Edge is too small to be useful, or sample size is too small to validate.

### Supporting Evidence:

1. **XRP shows positive result: +0.00001241 BTC**
   - Only symbol with positive PnL
   - Argument: Perhaps strategy is XRPUSDT-only profitable
   - Source: symbol_regime_side_summary

2. **Hypothesis space: 7 symbols × 5 regimes × 2 sides = 70 possible slices**
   - Even with portfolio -0.024%, statistically likely that some slice is +0.01%
   - Argument: Should search the slice space before abandoning strategy

### Contradicting Evidence:

1. **XRP "edge" is within slippage noise**
   - +0.00001241 BTC ≈ 1.2 satoshi per trade
   - Typical slippage: 0.00005–0.0001 BTC per round trip
   - XRP result is 4–80× smaller than slippage variance
   - Indistinguishable from random luck
   - Source: slice_viability_ranking analysis

2. **Per-symbol sample sizes are tiny**
   - ~14 trades per symbol (7 symbols × ~100 total trades / 5 regimes assumed)
   - 14-trade sample has huge variance
   - Cannot validate +0.0000012 BTC signal at 14-trade sample (would need 1000+ trades)
   - Source: slice_viability_ranking

3. **All other 6 symbols uniformly negative**
   - BTC, ETH, BNB, DOT, SOL, ADA: all negative
   - No diversity of outcome (would see mix if random noise)
   - Uniformity argues for systematic loss, not small slice noise
   - Source: symbol_regime_side_summary

### Missing Data:

- Regime × symbol breakdown (is BTC_BULL positive but BTC_BEAR negative?)
- Time-split (are recent trades worse than historical?)
- Post-fix vs pre-fix (did strategy improve after P1.1AP J/K/I fixes?)

### Falsification Test:

**Test A: Regime isolation**
- Extract BULL_TREND trades only → calculate PF and WR
- Extract BEAR_TREND trades only → calculate PF and WR
- If any regime > 1.0 PF, slice search has merit
- If all regimes < 1.0 PF, hypothesis falsified

**Test B: Time split (early vs recent)**
- Compare first 50 trades to last 50 trades
- Trend improvement (recent better than early)? Or degradation?
- If recent is better and positive, potential for recovery
- If recent is worse, model decay or regime shift

**Test C: Post-fix improvement**
- Compare trades closed before P1.1AP J/K fixes to trades closed after
- Are recent post-fix trades better performing?
- If yes, fixes are working, continue validation
- If no, fixes made no difference

### Confidence: **LOW (20%)**

**Rationale:**
- XRP result is within slippage noise (not a credible edge)
- All other symbols uniformly negative (not random scatter)
- 14-trade sample too small to validate any slice
- High risk of overfitting to noise if pursuing this path

**Recommendation:** Require regime/time-split breakdown before pursuing slice hypothesis. Without it, recommend abandoning this direction.

---

## Hypothesis H5: Reporting/Data-Scope Mismatch Prevents Reliable Conclusion

**Statement:** Dashboard inconsistencies (WR vs PnL mismatch, expectancy field, mode indicators, trade count scopes) indicate underlying data-source or calculation bugs. Until these are reconciled, NO reliable GO/NO-GO conclusion is possible.

### Supporting Evidence:

1. **Multiple dashboard inconsistencies documented**
   - WR 73.3% vs PnL negative ✓
   - Expectancy +0.00000146 vs net -0.00024 ✓
   - Status "TRENINK (zisk > 0)" vs zisk negative ✓
   - Mode "LIVE" vs exposure zero ✓
   - Trade count (7707, 100, 200) without scope docs ✓
   - Source: metric_reconciliation.md

2. **Expectancy field mismatch is particularly concerning**
   - Dashboard reports +0.00000146
   - Canonical net is -0.00023955
   - If expectancy field is wrong, other metrics may be wrong too
   - Argument: Cannot trust any dashboard-derived metric until expectancy field reconciled

3. **Trade count scope ambiguity**
   - completed_trades = 7707 (??)
   - canonical = 100
   - LM = 200
   - What does 7707 mean? Lifetime? Session? Live+paper mixed?
   - If 7707 is lifetime, canonical 100 is subset, analysis is correct
   - If 7707 is session, and canonical 100 is different session, analysis is comparing apples to oranges
   - Argument: Need definitions before confident audit

### Contradicting Evidence:

1. **Correctable issues don't invalidate primary finding**
   - Even with dashboard bugs, the core data is:
     * 100 closed canonical trades with recorded exit types and PnL
     * Exit breakdown (SCRATCH 47, STAG 34, PARTIAL_TP 8, etc.) is mathematically consistent
     * Sum of exit PnLs = total net PnL = -0.00023955 ✓
   - This is NOT a bug; it's a correct aggregation of losing trades
   - Argument: Core conclusion (net negative) is robust even if display fields are buggy

2. **Reconciliation shows contradictions are dashboard-level, not data-level**
   - WR 73.3% is CORRECT as "wins / (wins + losses)"
   - Problem is not with the calculation but with using it as headline metric
   - Same with expectancy: field may be "expected move %" not "realized expectancy"
   - These are labeling bugs, not calculation bugs
   - Source: metric_reconciliation.md analysis

3. **Snapshot data can be independently validated**
   - 11 wins + 4 losses + 85 neutral = 100 trades ✓
   - 8 + 4 + 2 + 2 + 47 + 34 + 3 = 100 trades ✓
   - Sum of exit PnLs: 0.00005131 + 0.00000556 - 0.00000788 - 0.00003500 - 0.00003975 - 0.00009236 - 0.00012143 ≈ -0.00023955 ✓
   - Arithmetic is consistent; data corruption is unlikely

### Missing Data:

- Firebase primary source reconciliation (does Firestore table match reported exit breakdown?)
- Dashboard source code inspection (is expectancy field calculated from realized net or expected move %?)
- Logging verification (do application logs show trades being processed as reported?)

### Falsification Test:

**Test A: Data source reconciliation**
- Extract canonical_closed_trades collection from Firebase (read-only)
- Manually aggregate: sum(profit), count(exit_type=SCRATCH), etc.
- Compare to reported values in snapshot
- If Firebase matches snapshot, reporting is accurate
- If Firebase diverges, data-source mismatch exists

**Test B: Dashboard code inspection**
- Review dashboard_snapshot_contract.py and metrics_engine.py
- Locate expectancy field calculation
- Is it `sum(pnl) / count` (realized) or `sum(expected_move_pct) / count` (expected)?
- This explains the inconsistency

### Confidence: **MEDIUM (45%)**

**Rationale:**
- Some dashboard bugs ARE documented (WR framing, status message)
- But core trade data appears arithmetically consistent
- Expectancy field mismatch needs explanation but doesn't invalidate conclusion
- Low risk that underlying trade data is corrupted
- Higher risk that metrics are calculated from different subsets

**Recommendation:** Require Firebase reconciliation before final conclusion, but current snapshot-based analysis is defensible. Proceed with PIVOT DECISION as if snapshot is correct; separately file dashboard bugs for v10.13y+ backlog.

---

## Hypothesis Ranking Summary

| Rank | Hypothesis | Confidence | Recommendation | Action |
|---|---|---|---|---|
| **1** | H1: Entries lack directional edge | HIGH (85%) | **MOST LIKELY** | ROOT CAUSE IDENTIFIED |
| **2** | H5: Reporting/data-scope mismatch | MEDIUM (45%) | INVESTIGATE | Verify Firebase source, inspect dashboard code |
| **3** | H2: Weak gross edge offset by fees | MEDIUM (40%) | LOWER PRIORITY | Conditional on H1 being false |
| **4** | H4: Edge in small slice | LOW (20%) | UNLIKELY | Requires regime/time breakdown (not available) |
| **5** | H3: Exits destroy winners | LOW (15%) | UNLIKELY | Requires MFE data (not available) |

---

## Primary Conclusion

**H1 (Entries lack directional edge) is the best-supported hypothesis at 85% confidence.**

- **Evidence:** 81% of trades (SCRATCH + STAGNATION) fail to move in entry direction
- **Interpretation:** Entry EV signals at 0.030–0.038 range are not predictive
- **Root cause:** Signal calibration or entry gate is misconfigured/overfitted
- **Remedy:** Requires signal architecture redesign, not parameter tuning

**Secondary:** H5 (reporting mismatches) should be investigated but does NOT invalidate primary conclusion.

**Recommendation for PIVOT DECISION:** ABANDON current signal architecture unless Firebase reconciliation reveals data-source mismatch that explains entire negative result (very unlikely).
