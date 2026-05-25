# Claude Code Prompt — Phase 2B: Firebase Schema Probe ONLY (Approved Ceiling: 10 Reads)

## Operator-approved scope

This task authorizes a **read-only Firebase schema/sample probe only**, capped at **10 total document reads**.

Do not retrieve the full 100-trade population in this task.
Do not perform Phase 2 diagnosis yet.
Do not modify runtime code, tests, state, Firebase documents, schemas, indexes, configuration, or service status.

```text
CURRENT STRATEGY: NO-GO / RETIRED FOR REAL TRADING
REAL TRADING: FORBIDDEN
RUNTIME PATCH FREEZE: ACTIVE
SAFE HEAD: 735ba35
FIREBASE WRITES: FORBIDDEN
MAX FIREBASE DOCUMENT READS IN THIS TASK: 10 TOTAL, HARD CAP
```

## Why this probe is required

Phase 2A is useful but did not establish an executable exact read plan. It still contains unresolved statements:

```text
collection = "canonical_closed_trades (or trades with filters)"
storage model = "likely one-document-per-trade, aggregate possible"
MFE/MAE persisted fields = pending Firebase verification
```

Source code showing fields are computed does not prove they are persisted in the actual Firebase documents needed for analysis.

Before requesting up to 100 canonical trade reads, prove:

```text
- exact collection/document/query path,
- one-doc-per-trade versus aggregate storage,
- actual stored field keys and units,
- whether canonical economic trades can be isolated from paper/shadow/legacy rows,
- whether MFE/MAE and cost fields are available in the stored records.
```

## Metric conclusions already accepted — do not re-litigate

```text
PF headline reconciliation:
0.00023435 / 0.00047390 = 0.4945136 ≈ 0.49.

Realized all-outcome expectancy:
-0.00023955 / 100 = -0.0000023955 BTC per canonical trade.

Dominant realized loss source:
SCRATCH_EXIT + STAGNATION_EXIT = 81/100 trades,
net -0.00021379 BTC ≈ 89.25% of total loss.

Entry-vs-exit cause:
UNRESOLVED pending raw MFE/MAE and possibly price-path data.
```

## Critical interpretation guardrail

Do not claim that MFE/MAE alone will “definitively” establish a successful alternate strategy.

It can establish whether realized losing exits had favorable excursion under the observed holding interval. A claim that another exit policy would have been profitable may require timestamped path/candle replay and the same fees/slippage assumptions.

Also use consistent units:
```text
MFE/MAE thresholds must be defined in percent or decimal-return units,
not as an unlabeled BTC amount.
```

## Step 0 — Local verification before any Firebase read

Run read-only local checks and save output:

```bash
cd /opt/CryptoMaster_srv
mkdir -p data/research/firebase_reconciliation_phase2b_schema_probe_2026-05-22

git rev-parse --short HEAD
git status --short
systemctl status cryptomaster --no-pager -l || true

grep -R "canonical_closed_trades\|collection(\|document(\|stream(\|where(\|trades\|paper_closed_trade\|max_seen\|min_seen\|mfe_pct\|mae_pct" -n \
  src scripts tests 2>/dev/null \
  > data/research/firebase_reconciliation_phase2b_schema_probe_2026-05-22/local_query_path_search.txt || true
```

Before performing any read, write a short local pre-read note listing candidate collections/queries inferred from code:

```text
data/research/firebase_reconciliation_phase2b_schema_probe_2026-05-22/PRE_READ_QUERY_CANDIDATES.md
```

It must specify:
```text
candidate path/query
code evidence file:line
why it might contain canonical trades or raw diagnostic fields
planned max reads allocated to that candidate
```

## Firebase read authorization and cap

After local query candidate inspection, you may perform only minimal document reads needed to establish schema.

Hard rules:

```text
- Maximum total documents read: 10.
- Read-only operations only.
- No writes, updates, deletes, backfills, migrations, indexes, resets or listeners.
- No retry loop that can exceed the hard cap.
- Maintain a read ledger incremented before/after every request.
- If a query would return more documents than remaining budget, set its limit to remaining budget.
- If collection/path cannot be resolved safely within 10 reads, stop and report unresolved.
```

Preferred allocation, adjust only downward:

```text
1–2 reads: establish exact collection/query existence and record shape.
Up to 8 additional reads: verify consistency of fields/scopes across sample documents.
Total <= 10.
```

Do not download secrets, service-account credentials, full environment files, or Firebase auth material into research outputs. Redact document IDs if they encode sensitive information; keep only a deterministic short hash where correlation is needed.

## Probe questions to answer

Using no more than 10 reads, determine:

### A. Storage path and model
```text
exact collection/document/query used
one trade per document, aggregate document, or unresolved
canonical-only vs. mixed rows
available discriminator fields: source, bucket, mode, environment, canonical flag, outcome, reason
```

### B. Stored raw fields
For each needed field, report:
```text
present in sample? yes/no/mixed
field name
unit/semantic interpretation based on code and observed value shape
```

Fields:
```text
trade_id or correlation key
symbol
side/action
entry_ts / exit_ts
entry price / exit price
exit_reason
bucket / training_bucket / source / mode
net_pnl / net_pnl_pct
gross_pnl / gross_move_pct
fee_cost / slippage_cost / fee_drag_pct
max_seen / min_seen
mfe_pct / mae_pct
entry_regime / exit_regime
TP / SL / hold limit
```

### C. Is a full Phase 2 read capable of answering entry-vs-exit?
Classify:

```text
READY:
stored canonical records contain MFE/MAE or max_seen/min_seen + side/entry/exit/cost fields.

PARTIALLY READY:
stored records contain trades but lack MFE/MAE; requires separate locally available path data
or additional price-history query plan.

NOT READY:
canonical record source cannot be isolated or essential fields are absent.
```

## Do not proceed beyond schema probe

Even if all fields are present, stop after 10-read schema verification.

Do **not**:
```text
- fetch the remaining canonical records,
- calculate an entry-vs-exit diagnosis from a nonrepresentative 10-row probe,
- implement a new strategy,
- make runtime/dashboard fixes.
```

## Required outputs

Create only under:

```text
data/research/firebase_reconciliation_phase2b_schema_probe_2026-05-22/
```

Files:

```text
runtime_and_git_freeze_check.md
local_query_path_search.txt
PRE_READ_QUERY_CANDIDATES.md
READ_LEDGER.md
FIREBASE_SCHEMA_PROBE_REPORT.md
FIELD_AVAILABILITY_MATRIX.csv
PHASE2_FULL_READ_APPROVAL_REQUEST_REVISED.md
```

`READ_LEDGER.md` must show:

| Operation # | Purpose | Query/path | Requested limit | Actual document reads | Cumulative reads |
|---:|---|---|---:|---:|---:|

The final cumulative value must be `<= 10`.

## Revised full-read request requirements

Only if probe returns `READY` or `PARTIALLY READY`, create the revised approval request. It must include:

```text
- exact verified collection/query path;
- exact filter used to isolate canonical trades or exact reason this is not possible;
- exact fields verified present/absent;
- verified storage model;
- max additional Firebase document reads needed after this 10-read probe;
- whether raw data can decide entry-vs-exit or whether candle/path replay is additionally required;
- output files to be created by future Phase 2;
- no writes/restarts/runtime edits.
```

Use a precise total ceiling:
```text
reads already consumed by Phase 2B: N <= 10
additional reads requested for Phase 2: M
combined approved-project ceiling if later authorized: N + M
```

## Completion response

Return only:

```text
PHASE 2B STATUS:
SAFE HEAD / RUNTIME FREEZE:
FIREBASE READS USED:
EXACT PATH VERIFIED:
STORAGE MODEL:
CANONICAL FILTER VERIFIED:
MFE/MAE OR MAX/MIN STORED?:
ENTRY-VS-EXIT DIAGNOSIS READINESS:
ADDITIONAL READS REQUESTED FOR FULL PHASE 2:
WRITES / RUNTIME CHANGES:
OUTPUT FILES:
```
