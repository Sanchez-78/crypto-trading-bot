# Claude Code Prompt — Phase 2A: Exact Raw-Data Access Plan for Entry-vs-Exit Diagnosis (NO Reads Yet)

## Operating decision

The current CryptoMaster strategy is retired from consideration for real trading.

```text
CURRENT STRATEGY: NO-GO / RETIRED FOR REAL TRADING
REAL TRADING: FORBIDDEN
RUNTIME PATCH FREEZE: ACTIVE
SAFE HEAD: 735ba35
VALIDATED TEST BASELINE: 854 passed, 0 failures, 0 warnings
```

This task is not a patch and not a strategy implementation. Its only purpose is to prepare an exact, low-risk read-only data extraction plan for the unresolved entry-vs-exit question.

## Why this is the next step

Already proven locally:

```text
canonical trades = 100
net PnL = -0.00023955 BTC
PF = 0.4945 ≈ dashboard PF 0.49
realized all-outcome expectancy = -0.0000023955 BTC per canonical trade
SCRATCH_EXIT + STAGNATION_EXIT = 81/100 trades
SCRATCH_EXIT + STAGNATION_EXIT PnL = -0.00021379 BTC ≈ 89.25% of total loss
```

Still unresolved:

```text
Did entry signals fail directionally, producing no usable favorable movement?
OR
Did entries sometimes have favorable movement that scratch/stagnation exit logic failed to monetize?
```

This cannot be answered from aggregate exit totals. It requires raw per-trade fields such as MFE/MAE, gross/net PnL, fees/slippage, entry/exit timestamps and possibly price paths.

## Hard boundaries

Do not:

```text
- modify src/, tests/, configuration, state files, or dashboards
- write/commit/push code
- restart or reload cryptomaster.service
- execute any Firebase reads or writes in Phase 2A
- enable real trading
- propose a runtime patch
- change thresholds, TP/SL, routing, learning or sampling
```

Outputs may be written only under:

```text
data/research/firebase_reconciliation_phase2a_2026-05-22/
```

## Inputs

Review existing analysis first:

```text
data/research/offline_go_no_go_2026-05-22/
data/research/offline_strategy_pivot_2026-05-22/
data/research/firebase_reconciliation_phase1_2026-05-22/
```

Use the corrected Phase 1A conclusions; do not reintroduce prior PF or expectancy errors.

## Phase 2A-1 — Confirm safe runtime/repo state, read-only

```bash
cd /opt/CryptoMaster_srv
mkdir -p data/research/firebase_reconciliation_phase2a_2026-05-22

git rev-parse --short HEAD
git log --oneline -10
git status --short
systemctl status cryptomaster --no-pager -l || true

grep -R "E_ECON_BAD_NEAR_MISS_SHADOW\|PAPER_ECON_BAD_NEAR_MISS_SHADOW_ENTRY" -n src/services tests || true
```

Record the outcome in:

```text
data/research/firebase_reconciliation_phase2a_2026-05-22/runtime_freeze_verification.md
```

## Phase 2A-2 — Exhaust local data before any database read

Search for locally available raw trade information:

```bash
find data -maxdepth 5 -type f -printf '%p\n' | sort \
  > data/research/firebase_reconciliation_phase2a_2026-05-22/local_file_inventory.txt

grep -R "mfe_pct\|mae_pct\|max_seen\|min_seen\|gross_move_pct\|fee_drag_pct\|fee_cost\|slippage_cost\|PAPER_TRAIN_ECON_ATTRIB\|PAPER_TRAIN_QUALITY_EXIT" -n \
  data scripts src tests 2>/dev/null \
  > data/research/firebase_reconciliation_phase2a_2026-05-22/local_raw_field_search.txt || true
```

Determine whether existing logs or exports already contain sufficient MFE/MAE/gross/fee information for any clean subset. If sufficient raw rows exist locally, calculate exploratory entry-vs-exit metrics locally and state that Firebase reads may be unnecessary or reduced.

Do not mix:
```text
D_NEG_EV_CONTROL shadow rows
B_RECOVERY_READY diagnostics
C_WEAK canonical learning rows
legacy/canonical dashboard rows
```

## Phase 2A-3 — Locate Firebase schema and exact read interface from code only

Read-only source inspection:

```bash
grep -R "firebase\|firestore\|collection(\|document(\|get_document\|get_collection\|stream(\|trades\|trade_history\|canonical_closed\|model_state\|metrics" -n \
  src scripts tests 2>/dev/null \
  > data/research/firebase_reconciliation_phase2a_2026-05-22/firebase_schema_code_search.txt || true

grep -R "mfe_pct\|mae_pct\|max_seen\|min_seen\|gross_move_pct\|fee_drag_pct\|fee_cost\|slippage_cost\|net_pnl\|entry_regime\|exit_regime\|training_bucket" -n \
  src scripts tests 2>/dev/null \
  > data/research/firebase_reconciliation_phase2a_2026-05-22/raw_field_contract_search.txt || true
```

Open relevant functions and map:

```text
- collection/document path for canonical trade records, if present
- collection/document path for paper closed trade diagnostics, if present
- whether data is one document per trade or embedded aggregate arrays
- field names for trade_id, bucket, symbol, side, regime, entry/exit, gross/net PnL, fee/slippage, MFE/MAE
- code path that separates canonical records from D_NEG/B diagnostic rows
- whether any existing read-only export script can be safely used
```

## Phase 2A-4 — Define the minimum admissible raw sample

The audit must prioritize data that can answer causality, not generate more reports.

Required sample, if available:

```text
Population A — Canonical economic trades underlying PF/net PnL:
  ideally all 100 canonical trades;
  required fields: trade_id, symbol, side, regime, entry/exit timestamps/prices,
                   exit_reason, net_pnl, gross_pnl, fee/slippage,
                   MFE/MAE if recorded.

Population B — Clean post-fix C_WEAK paper trades, separate analysis only:
  required fields as available, never merge into canonical.

Exclude from economic population:
  D_NEG_EV_CONTROL shadow rows.
Keep separately labelled:
  B_RECOVERY_READY diagnostic rows.
```

If the canonical 100 do not contain MFE/MAE, report that Firebase cannot resolve entry-vs-exit causality without price-path reconstruction, and specify the minimal candle/time-window export required instead.

## Phase 2A-5 — Produce exact read-only execution proposal, but do not run it

Create:

```text
data/research/firebase_reconciliation_phase2a_2026-05-22/FIREBASE_PHASE2_READ_APPROVAL_REQUEST.md
```

It must contain an executable, reviewable plan:

| Read operation | Collection/path | Query/filter/limit | Expected documents max | Required fields | Question resolved |
|---|---|---|---:|---|---|

Rules:

```text
- No range estimate without a source-backed explanation.
- If one document per trade and 100 trades are required, state maximum >=100 trade reads.
- If an aggregate document contains all trades, cite the code/schema evidence and state exact document count.
- Add metadata/config reads only when essential and list each one.
- Keep total requested read ceiling explicit.
- Do not include writes, resets, migrations or backfills.
```

Include proposed output destinations:

```text
data/research/firebase_reconciliation_phase2_2026-05-22/raw_canonical_trades.json
data/research/firebase_reconciliation_phase2_2026-05-22/raw_paper_diagnostics.json
data/research/firebase_reconciliation_phase2_2026-05-22/ENTRY_VS_EXIT_DIAGNOSIS_REPORT.md
```

Do not create those Phase 2 outputs yet unless local data alone is sufficient.

## Required Phase 2A outputs

Create:

```text
data/research/firebase_reconciliation_phase2a_2026-05-22/runtime_freeze_verification.md
data/research/firebase_reconciliation_phase2a_2026-05-22/local_file_inventory.txt
data/research/firebase_reconciliation_phase2a_2026-05-22/local_raw_field_search.txt
data/research/firebase_reconciliation_phase2a_2026-05-22/firebase_schema_code_search.txt
data/research/firebase_reconciliation_phase2a_2026-05-22/raw_field_contract_search.txt
data/research/firebase_reconciliation_phase2a_2026-05-22/SCHEMA_AND_RAW_FIELD_MAP.md
data/research/firebase_reconciliation_phase2a_2026-05-22/FIREBASE_PHASE2_READ_APPROVAL_REQUEST.md
```

## Completion requirement

At the end of this task, stop before any DB operation and report:

```text
PHASE 2A STATUS:
RUNTIME/SOURCE/DB CHANGES:
LOCAL RAW DATA SUFFICIENT?:
FIREBASE PATHS FOUND:
REQUIRED RAW FIELDS AVAILABLE?:
EXACT REQUESTED READ CEILING:
WHAT THE READS WOULD DECIDE:
OPERATOR APPROVAL REQUIRED:
OUTPUT FILES:
```

Do not proceed to Firebase reads until the operator explicitly approves the stated read plan and ceiling.
