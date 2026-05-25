# Claude Code Prompt — Phase 1 Read-Only Data Reconciliation Before Strategy Redesign

## Decision already made

Operational decision is final for the current system:

```text
CURRENT STRATEGY STATUS: RETIRED / NO-GO FOR REAL TRADING
REAL TRADING: FORBIDDEN
RUNTIME PATCH FREEZE: ACTIVE
SAFE CODE HEAD: 735ba35
SERVER-SAFE TEST BASELINE: 854 passed, 0 failed, 0 warnings
```

Do **not** implement strategy changes, runtime patches, parameter tuning, dashboard fixes, routing changes, learning changes, or service restarts in this task.

## Why this Phase 1 exists

Offline GO/NO-GO and pivot analyses concluded that the current strategy is not economically viable on the available summary data:

```text
canonical closed trades = 100
net PnL total = -0.00023955 BTC
profit factor = 0.49x
learning health = BAD
SCRATCH_EXIT + STAGNATION_EXIT = 81/100 trades
their combined net PnL = -0.00021379 BTC (~89.25% of total net loss)
```

However, before authorizing a *new* strategy design, reconcile the data sources and metric semantics so the redesign is based on clean evidence.

Important correction:
```text
Confirmed all-outcome realized expectancy in absolute units:
-0.00023955 BTC / 100 = -0.0000023955 BTC per canonical trade.

Do NOT express this as a percentage per trade unless the exact denominator/equity/notional basis is proven from source data.
```

Also do not overclaim:
```text
"Current architecture is retired because it failed current economic evidence" is supported.
"No parameter or redesigned strategy can ever recover edge" is not proven.
```

## Inputs to use first

Existing offline audit artifacts:

```text
data/research/offline_go_no_go_2026-05-22/GO_NO_GO_REPORT.md
data/research/offline_go_no_go_2026-05-22/canonical_summary.csv
data/research/offline_go_no_go_2026-05-22/exit_reason_summary.csv
data/research/offline_go_no_go_2026-05-22/symbol_regime_side_summary.csv
data/research/offline_go_no_go_2026-05-22/rejection_summary.csv
data/research/offline_go_no_go_2026-05-22/data_provenance.md

data/research/offline_strategy_pivot_2026-05-22/PIVOT_DECISION_REPORT.md
data/research/offline_strategy_pivot_2026-05-22/metric_reconciliation.md
data/research/offline_strategy_pivot_2026-05-22/exit_failure_analysis.csv
data/research/offline_strategy_pivot_2026-05-22/slice_viability_ranking.csv
data/research/offline_strategy_pivot_2026-05-22/hypothesis_ranking.md
data/research/offline_strategy_pivot_2026-05-22/missing_data_required.md
```

Local runtime/state/export files may be read only. Do not mutate or overwrite them.

## Strict no-write boundaries

Do not:

```text
- modify src/, tests/, configuration or runtime state
- commit or push code
- restart/reload cryptomaster.service
- write to Firebase
- run any reset/migration/backfill script
- change Android snapshot or metrics contracts
- enable live/real trading
- implement a new signal paradigm
```

Outputs may be created only under:

```text
data/research/firebase_reconciliation_phase1_2026-05-22/
```

## Firebase quota/safety rule

Firebase must be treated as read-budget constrained.

Before making any Firebase reads:

1. Exhaust local artifacts, existing exports, JSON/state files, and journal-derived evidence.
2. Locate existing read-only export scripts and estimate the exact required Firebase collections/documents.
3. Produce a read-budget plan:
   ```text
   required collections
   exact query/filter per collection
   estimated read count
   expected information gained
   whether local data already makes that read unnecessary
   ```
4. If live Firebase reads are still required, **stop and report the read-budget plan for operator approval**. Do not perform live Firebase reads in this task unless the operator explicitly authorizes them later.

This task is therefore a local reconciliation audit plus a minimal Firebase read plan, not an uncontrolled database export.

## Phase 1A — Verify repository/runtime freeze status

Run read-only checks:

```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git log --oneline -10
git status --short
systemctl status cryptomaster --no-pager -l || true

grep -R "E_ECON_BAD_NEAR_MISS_SHADOW\|PAPER_ECON_BAD_NEAR_MISS_SHADOW_ENTRY" -n src/services tests || true
```

Record:
```text
HEAD
service PID/start time/status
any runtime/local dirty files
confirmation E-shadow is absent from active source
```

Do not restart the service.

## Phase 1B — Catalogue local evidence and metric producers

Find available local data and the code that defines displayed metrics:

```bash
mkdir -p data/research/firebase_reconciliation_phase1_2026-05-22

find data -maxdepth 4 -type f -printf '%p\n' | sort \
  > data/research/firebase_reconciliation_phase1_2026-05-22/local_data_inventory.txt

find scripts -maxdepth 4 -type f -printf '%p\n' | sort \
  > data/research/firebase_reconciliation_phase1_2026-05-22/script_inventory.txt

grep -R "completed_trades\|Total trades in LM\|WR_canonical\|Expectancy\|Profit Factor\|canonical_closed_trades\|lm_economic_health\|STAGNATION_EXIT\|SCRATCH_EXIT" -n \
  src scripts tests VERIFICATION_V10_13W 2>/dev/null \
  > data/research/firebase_reconciliation_phase1_2026-05-22/metric_producer_locations.txt || true
```

Read and map metric formulas and source paths for:

```text
canonical trades = 100
LM trades = 200
completed_trades = 7707
WR_canonical = 73.3%
dashboard expectancy = +0.00000146
net closed PnL = -0.00023955
PF = 0.49
mode labels: TRENINK versus learning snapshot mode=LIVE
```

## Phase 1C — Reconcile locally available metrics

Using only local exported audit files, state files, and logs, create a reconciliation table:

| Metric | Displayed value | Calculation/source function | Underlying dataset scope | Independently recomputed value | Match? | Interpretation |
|---|---:|---|---|---:|---|---|
| canonical count | 100 | | | | | |
| LM count | 200 | | | | | |
| completed_trades | 7707 | | | | | |
| net PnL | -0.00023955 BTC | | | | | |
| PF | 0.49 | | | | | |
| decisive-only WR | 73.3% | | | | | |
| all-outcome win share | | | | | | |
| absolute expectancy/trade | -0.0000023955 BTC | | | | | |
| dashboard expectancy | +0.00000146 | | | | | |
| status text | TRENINK (zisk > 0) | | | | | |
| snapshot mode | LIVE | | | | | |

### Required reconciliations

Prove from local data if possible:

```text
1. sum(exit_reason net PnL) == total net PnL
2. sum(symbol net PnL) == total net PnL
3. gross_win / abs(gross_loss) == PF
4. exact denominator and definition of WR_canonical
5. exact formula/unit/denominator of dashboard Expectancy
6. exact semantic meaning of completed_trades, canonical trades, and LM count
7. whether mode="LIVE" is trade execution mode, learning state label, or display bug
```

Do not fix any mismatch. Classify it.

## Phase 1D — Identify missing raw data needed to decide entry-vs-exit failure

The pivot conclusion currently says entries lack directional edge with ~85% confidence. Validate what can and cannot be claimed.

For every conclusion, label:
```text
PROVEN FROM NET AGGREGATES
SUPPORTED BUT NOT PROVEN
NOT TESTABLE WITHOUT RAW DATA
```

Especially distinguish:

```text
A. "Current system loses money after costs" — expected PROVEN.
B. "Scratch/stagnation dominate net losses" — expected PROVEN.
C. "Entries have no directional edge" — requires gross pre-fee path/MFE/MAE or replay; not proven from exit net alone unless present.
D. "Exit logic destroys possible winners" — also requires price-path evidence.
```

Determine the minimum raw fields needed:

```text
trade_id
symbol, regime, side
entry_ts/exit_ts
entry/exit price
reason / bucket / canonical eligibility
gross pnl
fee_cost/slippage_cost/net pnl
MFE/MAE
TP/SL/hold geometry
signal EV/score/features
post-entry price path or sampled candles for counterfactual exit replay
```

## Phase 1E — Minimal Firebase read plan, no execution

Search locally for Firebase collection/query contracts:

```bash
grep -R "collection(\|document(\|firebase\|firestore\|trades\|model_state\|metrics\|signals" -n \
  src scripts tests 2>/dev/null \
  > data/research/firebase_reconciliation_phase1_2026-05-22/firebase_schema_locations.txt || true
```

Create a **proposed read-only export plan** that states:

```text
Collection/document paths required
Query filters/time windows required
Fields needed
Estimated Firebase reads
Why each read is needed
What conclusion it can validate
Can it be avoided using local data? yes/no
```

Prefer the smallest export that validates:

```text
- the 100 canonical trades behind PF/net PnL
- the metric definitions/count scopes
- raw trade data sufficient for entry-vs-exit diagnosis
```

Do not execute Firebase reads without later explicit approval.

## Outputs

Create:

```text
data/research/firebase_reconciliation_phase1_2026-05-22/PHASE1_RECONCILIATION_REPORT.md
data/research/firebase_reconciliation_phase1_2026-05-22/metric_scope_table.csv
data/research/firebase_reconciliation_phase1_2026-05-22/local_data_inventory.txt
data/research/firebase_reconciliation_phase1_2026-05-22/metric_producer_locations.txt
data/research/firebase_reconciliation_phase1_2026-05-22/raw_data_gap_analysis.md
data/research/firebase_reconciliation_phase1_2026-05-22/firebase_read_budget_plan.md
data/research/firebase_reconciliation_phase1_2026-05-22/firebase_schema_locations.txt
```

Start the report with:

```text
CURRENT STRATEGY: RETIRED / NO-GO FOR REAL TRADING
RUNTIME PATCH FREEZE: ACTIVE
FIREBASE LIVE READS PERFORMED: NO
NEXT DECISION GATE: approve or reject minimal Firebase read plan
```

## Acceptance criteria

This task succeeds only if it:
```text
- changes no runtime source/test/configuration
- performs no Firebase writes
- performs no live Firebase reads without explicit operator approval
- reconciles every metric possible from local data
- clearly separates proven loss from unproven entry-vs-exit cause
- prepares a small quantified Firebase read plan only for unresolved facts
```

## Report back in chat

Return:

```text
PHASE 1 STATUS:
RUNTIME/DB CHANGES:
PROVEN LOCALLY:
NOT YET PROVEN:
DASHBOARD/METRIC MISMATCHES:
MINIMAL FIREBASE READ PLAN:
OPERATOR DECISION REQUIRED:
OUTPUT FILES:
```
