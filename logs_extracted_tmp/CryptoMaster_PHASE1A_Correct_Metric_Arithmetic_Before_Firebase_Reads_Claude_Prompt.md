# Claude Code Prompt — PHASE 1A Correction: Fix Local Reconciliation Arithmetic Before Any Firebase Reads

## Decision

Do **not** perform Firebase reads yet.

Phase 1 correctly confirmed the operational conclusion:

```text
CURRENT STRATEGY: RETIRED / NO-GO FOR REAL TRADING
REAL TRADING: FORBIDDEN
RUNTIME PATCH FREEZE: ACTIVE
SAFE HEAD: 735ba35
```

However, its summary contains arithmetic/conclusion errors that must be corrected locally before approving any database access.

This task is **read-only documentation correction and source inspection only**:
- no runtime changes,
- no `src/` or `tests/` edits,
- no service restart,
- no Firebase reads or writes,
- no commits unless the operator later asks to commit research outputs only.

Write only under:

```text
data/research/firebase_reconciliation_phase1_2026-05-22/
```

## Trusted snapshot values

From the canonical dashboard snapshot:

```text
canonical trades = 100
gross_win = 0.00023435 BTC
gross_loss = 0.00047390 BTC
net_pnl = -0.00023955 BTC
reported PF = 0.49x
dashboard expectancy = +0.00000146
decisive outcomes = wins 11, losses 4, neutral/other 85
SCRATCH_EXIT = 47, net -0.00009236 BTC
STAGNATION_EXIT = 34, net -0.00012143 BTC
```

## Mandatory corrections

### Correction 1 — PF is already reconciled locally

Phase 1 reported:

```text
Calculated PF = 0.192 versus dashboard PF = 0.49, unexplained discrepancy.
```

That statement is wrong based on the displayed gross values.

Compute and document:

```python
0.00023435 / 0.00047390 = 0.4945136105 ≈ 0.49
```

Correct conclusion:

```text
PF reconciliation: PASS.
Dashboard PF=0.49 is arithmetically consistent with gross_win/gross_loss shown in the snapshot.
No Firebase read is required to resolve the PF headline value.
```

Find why the prior audit produced `0.192` and correct the report/calculation script if the error is inside research-only output generation. Do **not** alter runtime metric code.

### Correction 2 — Expectancy mismatch is not "200x wrong"

Confirmed realized all-outcome expectancy:

```python
-0.00023955 / 100 = -0.0000023955 BTC per canonical trade
```

Dashboard shows:

```text
+0.00000146
```

Correct characterization:

```text
- The signs conflict: dashboard is positive while realized all-outcome expectancy is negative.
- The absolute dashboard magnitude is about 0.6095× the absolute realized expectancy, not 200×.
- Difference = +0.0000038555 BTC/trade relative to realized all-outcome expectancy.
- The dashboard field may use another formula/unit/scope; inspect source locally before requesting Firebase reads.
```

### Correction 3 — WR terminology

Do not call `11/100 = 11%` an "all-outcome win rate" without qualification. Use:

```text
all-outcome positive-exit share = 11.0%
decisive-only WR = 11/(11+4) = 73.3%
```

The 85 other outcomes must not all be labelled losing; proven statement is:

```text
SCRATCH_EXIT + STAGNATION_EXIT:
81/100 trades
-0.00021379 BTC
89.2465% of total net loss magnitude
```

### Correction 4 — Directional-edge conclusion remains provisional

Allowed conclusion:

```text
Current strategy is economically NO-GO after costs.
SCRATCH/STAGNATION dominate realized losses.
Lack of directional entry edge is strongly suspected, not proven.
```

Forbidden overclaim until raw path/MFE/MAE or replay is reconciled:

```text
Entry architecture definitively lacks directional edge.
No parameter or exit redesign could ever recover edge.
```

## Local source inspection before any DB approval

Search metric formula code and local generated artifacts:

```bash
cd /opt/CryptoMaster_srv

grep -R "Expectancy\|expectancy\|Profit Factor\|profit_factor\|gross_win\|gross_loss\|WR_canonical\|completed_trades\|Total trades in LM" -n \
  src scripts tests VERIFICATION_V10_13W data/research 2>/dev/null \
  > data/research/firebase_reconciliation_phase1_2026-05-22/phase1a_metric_formula_search.txt || true

grep -R "0.192\|0.49\|0.00000146\|0.0000023955\|0.00023955" -n \
  data/research/firebase_reconciliation_phase1_2026-05-22 \
  data/research/offline_go_no_go_2026-05-22 \
  data/research/offline_strategy_pivot_2026-05-22 2>/dev/null || true
```

Read the source functions that produce:
```text
dashboard expectancy
PF
WR_canonical
completed_trades
canonical trades
LM count
status text TRENINK (zisk > 0)
```

Record file:line and exact formulas where determinable.

## Revised Firebase need decision

After local corrections, produce a reduced unresolved-facts list.

Likely no Firebase required for:
```text
- total net loss from displayed snapshot
- headline PF arithmetic reconciliation
- decisive-only WR definition
- all-outcome realized expectancy arithmetic
- scratch/stagnation loss share
- whether dashboard status text contradicts negative net PnL
```

Firebase/raw-export may still be necessary only for:
```text
- exact trade-level canonical dataset provenance if local export lacks it
- per-trade gross PnL, costs, fees/slippage
- MFE/MAE and price paths
- entry-vs-exit diagnosis
- authoritative count-scope reconciliation if local state/source is insufficient
```

### Read-plan requirements if still needed

Do not write vague estimates like `10-20 reads` for validating `100 trades` unless an aggregate document containing all required rows is identified.

For every proposed read state:

```text
collection/document path
exact query/filter/order/limit
whether one document aggregates multiple trades
exact expected maximum document reads
fields required
question resolved by this read
local evidence proving it is not already available
```

## Required output files

Update/create:

```text
data/research/firebase_reconciliation_phase1_2026-05-22/PHASE1A_CORRECTION_REPORT.md
data/research/firebase_reconciliation_phase1_2026-05-22/metric_scope_table_corrected.csv
data/research/firebase_reconciliation_phase1_2026-05-22/phase1a_metric_formula_search.txt
data/research/firebase_reconciliation_phase1_2026-05-22/firebase_read_budget_plan_corrected.md
```

Start the report with:

```text
STRATEGY STATUS: NO-GO / RETIRED FOR REAL TRADING
REAL TRADING: FORBIDDEN
RUNTIME PATCH FREEZE: ACTIVE
FIREBASE READS PERFORMED: NO
PHASE 1 CORRECTION REQUIRED: YES — prior PF and expectancy mismatch statements contained arithmetic errors
```

## Report back

Return only:

```text
PHASE 1A STATUS:
CORRECTED PF RECONCILIATION:
CORRECTED EXPECTANCY COMPARISON:
WR TERMINOLOGY CORRECTION:
WHAT IS PROVEN:
WHAT STILL REQUIRES RAW DATA:
FIREBASE READS STILL REQUESTED?:
EXACT MAX READS IF REQUESTED:
OUTPUT FILES:
```
