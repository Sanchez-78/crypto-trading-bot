# Claude Code Prompt — OFFLINE Strategy Pivot Analysis After NO-GO

## Decision context

The runtime patch loop is frozen. The completed GO/NO-GO audit returned:

```text
VERDICT: NO-GO
REAL TRADING: FORBIDDEN
RUNTIME PATCH FREEZE: ACTIVE
```

Safe code state:
```text
HEAD: 735ba35 Revert P1.1AP-L shadow sampler experiment
Server-safe suite: 854 passed, 0 failed, 0 warnings
```

Use the existing audit outputs as the primary dataset:

```text
data/research/offline_go_no_go_2026-05-22/GO_NO_GO_REPORT.md
data/research/offline_go_no_go_2026-05-22/canonical_summary.csv
data/research/offline_go_no_go_2026-05-22/exit_reason_summary.csv
data/research/offline_go_no_go_2026-05-22/symbol_regime_side_summary.csv
data/research/offline_go_no_go_2026-05-22/rejection_summary.csv
data/research/offline_go_no_go_2026-05-22/data_provenance.md
```

## Mandatory metric corrections before analysis

The summary contained two wording/calculation problems. Correct them in the pivot report:

```text
Net PnL total = -0.00023955 BTC across 100 canonical trades.

All-outcome realized expectancy =
-0.00023955 / 100 =
-0.0000023955 BTC per canonical trade,
not -0.00023955 BTC/trade.

WR_canonical 73.3% = 11 / (11 + 4), decisive-only.
It excludes 85 neutral/other outcomes; do not call all 85 individually losing.
Known loss-dominating subset:
SCRATCH_EXIT 47 + STAGNATION_EXIT 34 = 81 trades,
combined PnL = -0.00021379 BTC,
approximately 89.25% of total net loss.
```

Do not trust dashboard labels such as positive expectancy or `TRENINK (zisk > 0)` until reconciled to canonical trade data.

## Purpose

Determine whether there is a defensible **strategy pivot hypothesis** worth validating in a new, fully offline/backtest or isolated paper-experiment plan.

This session must not implement code or change runtime. It must rank causes and recommend either:

```text
A. ABANDON CURRENT SIGNAL ARCHITECTURE
B. ONE OFFLINE-VALIDATABLE STRATEGY PIVOT
```

Do not recommend real trading.

## Prohibited actions

Do not:
```text
- edit src/ or tests/
- commit/push
- restart service
- enable real trading
- change EV thresholds, cost-edge, TP/SL, routing, learning or shadow buckets
- design another diagnostic runtime sampler
- rely on headline WR without all-outcome economics
```

Write outputs only beneath:

```text
data/research/offline_strategy_pivot_2026-05-22/
```

## Analysis questions

Answer, with numbers and provenance:

### 1. Is the signal direction predictive at all?
Using clean canonical and any separable post-fix paper data:
```text
- PnL by symbol × regime × side
- gross move before fees vs net after fees
- MFE/MAE where available
- fraction where direction was correct but costs/exits caused net loss
- fraction where direction was wrong immediately
```

### 2. Are exits destroying an otherwise usable edge?
Focus on:
```text
SCRATCH_EXIT
STAGNATION_EXIT
TIMEOUT_FLAT
TIMEOUT_LOSS
PARTIAL_TP_25
MICRO_TP
```

For each exit:
```text
count
gross move if available
net PnL
avg net PnL
fee/slippage drag
MFE and MAE distribution if available
how many would have reached an alternate TP/SL only as a simulation, not proposal
```

Key question:
```text
Are SCRATCH/STAGNATION exits avoiding larger losses, or prematurely killing winners?
```

Do not infer this from net losses alone; require MFE/MAE or subsequent-price replay.

### 3. Is apparent edge confined to an unusably small slice?
Evaluate:
```text
XRP positive result
ADA_HIGH_VOL / BTC_BULL / SOL_BEAR etc. displayed high WR/EV slices
minimum samples
post-fee PnL
confidence limitations
```

Reject any "promising" slice with tiny sample size or no post-fee validation.

### 4. Are metric definitions internally valid?
Reconcile:
```text
canonical trades=100
LM trades=200
completed_trades=7707
WR_canonical=73.3%
dashboard expectancy=+0.00000146
reported total net=-0.00023955
PF=0.49
status="TRENINK (zisk > 0)"
learning mode="LIVE"
```

Classify each mismatch:
```text
definition/documentation problem
dashboard display bug for backlog
data-source mismatch
potential economic calculation bug requiring later isolated investigation
```

Do not patch during this work.

### 5. What is the smallest falsifiable pivot hypothesis?
Rank hypotheses based on evidence, not intuition:

```text
H1: Entries lack directional edge; strategy signals should be redesigned.
H2: Entries contain weak gross edge but fees/cost threshold eliminate it.
H3: Exit policy (scratch/stagnation) destroys gross-positive trades.
H4: Specific symbol/regime/side slice carries the only net edge.
H5: Reporting/data-scope mismatch prevents a reliable conclusion.
```

For each:
```text
supporting evidence
contradicting evidence
data still missing
falsification test
confidence LOW/MEDIUM/HIGH
```

## Required decision rules

Recommend **ABANDON CURRENT SIGNAL ARCHITECTURE** if:
```text
- direction is not gross-positive before costs; or
- no slice has meaningful post-fee positive PnL with credible sample size; or
- metric/data-source mismatches make results unverifiable.
```

Recommend **ONE OFFLINE-VALIDATABLE STRATEGY PIVOT** only if:
```text
- a precisely named failure mechanism is supported by reconciled data;
- its proposed change is testable offline;
- it is not simply lowering thresholds to admit known weak candidates;
- validation includes out-of-sample/time split and all fees/slippage.
```

## Required outputs

Create:

```text
data/research/offline_strategy_pivot_2026-05-22/PIVOT_DECISION_REPORT.md
data/research/offline_strategy_pivot_2026-05-22/metric_reconciliation.md
data/research/offline_strategy_pivot_2026-05-22/exit_failure_analysis.csv
data/research/offline_strategy_pivot_2026-05-22/slice_viability_ranking.csv
data/research/offline_strategy_pivot_2026-05-22/hypothesis_ranking.md
data/research/offline_strategy_pivot_2026-05-22/missing_data_required.md
```

Begin `PIVOT_DECISION_REPORT.md` with:

```text
CURRENT STRATEGY: ABANDON or RETAIN FOR ONE OFFLINE EXPERIMENT ONLY
REAL TRADING: FORBIDDEN
RUNTIME PATCH FREEZE: ACTIVE
EVIDENCE QUALITY: HIGH / MEDIUM / LOW
```

Report must include:
```text
- corrected all-outcome expectancy
- decisive-only WR explicitly labelled non-economic headline metric
- top loss source and percentage contribution
- whether entries or exits are the dominant failure
- one next action only
```

## Report back in chat

Return only:

```text
CURRENT STRATEGY DECISION:
REAL TRADING:
CORRECTED EXPECTANCY:
DOMINANT FAILURE:
BEST SUPPORTED HYPOTHESIS:
ONE NEXT ACTION:
OUTPUT FILES:
```
