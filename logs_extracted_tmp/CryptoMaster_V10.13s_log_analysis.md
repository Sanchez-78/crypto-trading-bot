# CryptoMaster V10.13s — Log Analysis (Apr 25, 11:15)

## Executive summary

This log is a meaningful improvement over the previous state because the **canonical runtime state for decision logic is now consistent**.

Confirmed by:

- `Runtime: 108`
- `Dashboard: 108`
- `For Logic: 108 [live]`
- `Consistent: True`

That means the earlier stale/global-state mismatch issue is no longer the primary driver of behavior in the live logic path.

However, the core economic problem is **not solved**. The system still shows:

- high canonical win rate
- negative total closed PnL
- poor profit factor
- overwhelming dominance of `SCRATCH_EXIT`

So the main problem has shifted from **state inconsistency** to **exit economics / harvest failure**.

---

## What is clearly improved

### 1. Canonical state for logic is fixed

This is the biggest architectural win in the new log.

Previously there were conflicting truths such as `0 / 100 / 500 / 7467`.  
Now the logic path reports:

- `Runtime: 108`
- `Dashboard: 108`
- `For Logic: 108 [live]`
- `Consistent: True`

Interpretation:

- the bot is no longer making live decisions from stale global totals
- runtime logic now appears to use a coherent source of truth
- maturity / logic gating is likely operating on the correct live state

---

### 2. Pre-live audit is less restrictive

Previous snapshot:
- `Passed to execution: 14`
- `Blocked: 6`

Current snapshot:
- `Passed to execution: 18`
- `Blocked: 2`

Interpretation:

- the audit layer is cleaner
- the system is no longer over-blocking as aggressively
- fewer candidates are being stopped before execution

---

### 3. Risk budget is now clearly clamped

Current audit:

- `Avg risk_budget = 0.300`
- `Max risk_budget = 0.300`
- `Min risk_budget = 0.300`

This is a deliberate hard cap and explains the smaller sizes:

- `Avg final size ≈ 0.00315`

Compared to prior logs, position sizes are materially smaller.  
This improves safety, but also makes fee/scratch drag even harder to overcome.

---

## What is still wrong

## 1. Trading economics remain structurally bad

Current headline metrics:

- `WR_canonical = 73.6%`
- `Profit Factor = 0.65x`
- `Closed PnL = -0.00087396`

This is the critical contradiction:

- win rate looks strong
- but profit factor is poor
- total result is negative

That means the strategy still has a **payoff-shape problem**, not just a hit-rate problem.

---

## 2. SCRATCH_EXIT remains the dominant failure mode

Current breakdown:

- `SCRATCH_EXIT = 409`
- `82% of trades`
- `net = -0.00132613`

This is the central economic failure of the system.

Positive components do exist:

- `PARTIAL_TP_25 net +0.00056144`
- `MICRO_TP net +0.00001989`
- `wall_exit net +0.00002412`

But they are overwhelmed by the scratch layer.

### Most important new evidence

The new exit audit adds extremely valuable evidence:

- `partial25_near_miss = 327`
- `micro_near_miss = 101`

This strongly suggests:

- many trades come close to profitable harvest thresholds
- the bot often exits too early or too conservatively
- the harvest/exit logic is missing realizable positive excursion

This is no longer just “too many scratches.”  
It is specifically **too many scratches despite repeated near-miss opportunities**.

---

## 3. Learning quality is still weak despite `GOOD`

Current learning state:

- `Health = 0.309 [GOOD]`
- `edge_too_weak: mean edge < 0.001`
- `low_convergence: only 0/9 pairs converged`
- `low_breadth: only 4 pairs with n≥10`
- `Trend uceni: ZHORŠUJE SE`
- `Last 24: 66.7% vs average 73.6% (-7.0%)`

Interpretation:

The textual label `GOOD` is too optimistic.

The actual state is closer to:

- fragile
- shallow edge
- weak convergence
- narrow usable breadth
- short-term deterioration

So the monitoring semantics should probably be tightened.

---

## 4. Rejection layer is now more informative

Block reasons:

- `NEGATIVE_EV_REJECTION = 70`
- `LOSS_CLUSTER = 4`
- `SKIP_SCORE_SOFT = 3`
- `OFI_TOXIC_SOFT_BOOTSTRAP = 7`
- `OFI_TOXIC_SOFT = 7`

Interpretation:

- EV-only enforcement is active and significant
- the system is rejecting many low-edge candidates
- OFI/toxicity gating is now visibly participating
- block reasons are more diagnostic than before

This is a good sign architecturally.

---

## Remaining ambiguity / reporting mismatch

## 1. UI/reporting still mixes two realities

The canonical state says:

- `Runtime: 108`
- `Dashboard: 108`

But the large dashboard block still shows:

- `Obchody: 500`

That is probably explainable if:

- `500` = historical reconciled dataset
- `108` = canonical runtime state for live logic

But the log does **not explain that clearly enough**, so it still looks like a bug.

### Recommendation

Explicitly print:

- `Historical closed trades`
- `Runtime canonical trades`
- `Logic source`

That would eliminate ambiguity.

---

## 2. Execution engine numbers look session-local

Examples:

- `WR: 62.50%`
- `Edge: 0.50000`

These do not appear to match the broader historical reporting.

So the UI should clearly separate:

- historical performance
- current runtime session performance
- live open-book status

Without that, operators can misread the state.

---

## Diagnosis

## Primary conclusion

The major stale-state / source-of-truth bug is no longer the main blocker.

The main blocker is now:

> **exit economics**, especially the dominance of scratch exits and the failure to capture repeated near-miss harvest opportunities.

---

## Current priority order

## Priority 1 — Scratch exit forensics

Add a dedicated forensic layer for every scratch exit with at least:

- symbol
- regime
- hold time
- MFE before exit
- MAE before exit
- fee-adjusted result
- whether it was near:
  - `partial25`
  - `micro_tp`
- whether the exit was triggered by:
  - stall
  - timeout-like flatten
  - scratch policy
  - replacement pressure
  - risk compression

Goal:

- identify which scratch subgroup is economically harmful
- separate healthy defensive scratches from premature harvest failures

---

## Priority 2 — Harvest logic tuning

The harvest rate is still too low:

- `Harvest rate: 4.9% (5/103)`

Given:
- `partial25_near_miss = 327`
- `micro_near_miss = 101`

the system is likely too conservative in one or more of these:

- partial trigger threshold
- micro take-profit trigger
- persistence / hysteresis before scratch
- stall handling after positive excursion
- fee-aware profit capture

### Strong hypothesis

A large share of losing economics comes from:
- trades that briefly move into “almost profitable”
- but are scratched before realizing that excursion

---

## Priority 3 — Health/status semantics

Current label:
- `Health = 0.309 [GOOD]`

But concurrent warnings:
- weak edge
- zero convergence
- low breadth
- worsening recent trend

Suggested relabeling logic:

- `GOOD` only when edge, breadth, and convergence all meet minimum thresholds
- `CAUTION` when edge is weak or convergence is very low
- `FRAGILE` when multiple warnings stack simultaneously

---

## Priority 4 — Reporting semantic cleanup

Add explicit sections:

- `Historical reconciled totals`
- `Runtime canonical totals`
- `Live logic source`

This avoids false debugging loops caused by mixed counters.

---

## Best single-sentence conclusion

**The runtime/canonical state bug now appears fixed for live decision logic, but the strategy still loses economically because scratch exits dominate and the bot repeatedly fails to convert near-miss profit opportunities into realized harvests.**

---

## Recommended next patch

## `V10.13s.2 — Scratch Harvest Forensics + Exit Tuning`

### Objectives

1. instrument every scratch exit with MFE/MAE/hold-time/near-miss context  
2. classify scratch exits into economically useful vs premature  
3. lower missed-harvest rate  
4. improve partial/micro capture without increasing catastrophic loss behavior  
5. keep EV-only logic intact

### Expected impact

- lower `SCRATCH_EXIT` dominance
- better realized edge
- better profit factor
- reduced gap between win rate and net profitability

---

## Practical verdict

### Fixed enough to move on from as primary issue
- stale global state affecting logic
- inconsistent canonical runtime totals for decision-making
- over-restrictive audit behavior

### Still the main problem
- scratch-heavy exit profile
- weak realized edge
- low convergence / low breadth
- misleading monitoring semantics

---

## Final verdict

The bot is **architecturally healthier** than before, but **not economically healthy yet**.

You are no longer mainly debugging a broken state machine.  
You are now debugging a **poorly monetized edge**.
