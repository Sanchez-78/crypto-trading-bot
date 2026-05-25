# Claude Code Prompt — PHASE 1A Completion Gate: Correct Remaining Claims Before Firebase Approval

## Decision

Proceed with **Phase 1A local documentation/source-inspection work only**.

Do **not** execute Firebase reads yet.
Do **not** modify runtime code, tests, configuration, service state, Git history, or strategy behavior.
Do **not** restart `cryptomaster.service`.

Safe status remains:

```text
CURRENT STRATEGY: RETIRED / NO-GO FOR REAL TRADING
REAL TRADING: FORBIDDEN
RUNTIME PATCH FREEZE: ACTIVE
SAFE HEAD: 735ba35
VERIFIED TEST BASELINE: 854 passed, 0 failures, 0 warnings
```

## Phase 1A corrections already accepted

Retain these corrected conclusions:

```text
PF:
0.00023435 / 0.00047390 = 0.4945136 ≈ dashboard PF 0.49.
PF headline reconciliation passes locally; no Firebase read is required for PF.

Realized all-outcome expectancy:
-0.00023955 / 100 = -0.0000023955 BTC per canonical trade.

Dashboard expectancy:
+0.00000146 has the opposite sign from realized all-outcome expectancy.
Its absolute magnitude is ≈0.6095× the realized value, not "200× wrong".
Inspect local producer code before proposing DB reads for this field.

WR terminology:
Use "decisive-only WR = 73.3%" and "positive-exit share" only after resolving
the dashboard win-count versus positive-exit-count mismatch below.
```

## New corrections required before Phase 1A can be called complete

### 1. Do not call SCRATCH/STAGNATION “zero-move outcomes”

The current Phase 1A text states:

```text
81 trades (81% of canonical set) have zero-move outcomes (SCRATCH + STAGNATION)
```

This is not proven from exit names and net aggregates alone.

Correct statement:

```text
SCRATCH_EXIT + STAGNATION_EXIT comprise 81/100 canonical exits and contribute
-0.00021379 BTC, approximately 89.25% of total net loss.

Whether these trades had zero favorable movement, or whether they first moved
favorably and were later closed poorly, is NOT proven without MFE/MAE or price paths.
```

Classification:

```text
Dominant realized loss source: PROVEN.
No directional move within those trades: NOT PROVEN.
Entry-vs-exit causal diagnosis: NOT PROVEN.
```

### 2. Resolve the positive-exit count versus dashboard `OK 11` mismatch locally

The exit summary shown in the snapshot reports:

```text
PARTIAL_TP_25 = 8
MICRO_TP      = 4
```

If all 12 are positive canonical exits, this appears inconsistent with:

```text
Obchody 100 (OK 11 X 4 ~ 85)
WR_canonical = 11/(11+4) = 73.3%
```

Do not state `all-outcome positive-exit share = 11%` as settled until this is reconciled.

Investigate locally:

```bash
cd /opt/CryptoMaster_srv

grep -R "PARTIAL_TP_25\|MICRO_TP\|WR_canonical\|OK .* X\|wins\|losses\|canonical_closed_trades" -n \
  src scripts tests VERIFICATION_V10_13W data/research 2>/dev/null \
  > data/research/firebase_reconciliation_phase1_2026-05-22/phase1a_win_count_formula_search.txt || true
```

Determine:
- whether one `PARTIAL_TP_25` record is partial profit followed by non-win final classification;
- whether positive exit types are counted differently from canonical `wins`;
- whether exit-type report and header are drawn from different windows/scopes.

Until resolved, write:

```text
Dashboard decisive wins = 11 and losses = 4, yielding decisive-only WR 73.3%.
Exit-type table contains 12 positive-labeled exit events (8 PARTIAL_TP_25 + 4 MICRO_TP).
The relationship between positive exit events and canonical win classification requires
local formula/source reconciliation; do not equate them yet.
```

### 3. Do not say the remaining 19 trades are all “11% of loss” without sign clarification

Because the 19 non-SCRATCH/non-STAGNATION trades include positive and negative exits,
report their **net contribution**, not “losses”:

```text
All other exit categories combined:
net contribution = total net - scratch/stagnation net
                 = -0.00023955 - (-0.00021379)
                 = -0.00002576 BTC

They contribute net negative 10.75% of total net loss after offsetting positive
PARTIAL_TP/MICRO_TP gains against timeout/replaced losses.
```

### 4. Economic-health formula is not verified merely from the dashboard label

The Phase 1A summary states:

```text
Economic health = 0.0000 (BAD) is correctly calculated from min(PF, WR, negative_expectancy)
```

Only retain this statement if code inspection provides exact file:line evidence and
formula. Otherwise write:

```text
Displayed health=0.0000 [BAD] is observed and consistent with negative net PnL/PF<1,
but its exact formula must be documented from the local metric producer before marking
calculation reconciliation as PASS.
```

### 5. Do not keep PF in the Firebase critical-read plan

PF is already locally reconciled. Remove:

```text
Read 1.3: Profit factor source reconciliation (aggregation query)
```

from critical reads unless code inspection proves the displayed gross fields come from
a different scope than displayed PF. If there is only a semantic source-scope question,
list it as optional provenance, not required to uphold NO-GO.

### 6. Firebase read-count plan must be document-accurate

The current plan claims:

```text
10–20 reads for MFE/MAE data for all 100 trades
```

That is valid only if one located aggregate document embeds many trade rows.

Before asking approval, locate the exact storage contract locally:

```bash
grep -R "collection(\|document(\|closed_trades\|canonical_closed\|mfe\|mae\|max_seen\|min_seen\|fee_cost\|slippage_cost" -n \
  src scripts tests 2>/dev/null \
  > data/research/firebase_reconciliation_phase1_2026-05-22/phase1a_firebase_contract_search.txt || true
```

The corrected budget must specify:

```text
- exact collection/document/query path inferred from source;
- whether each returned document contains one trade or an aggregate list;
- fields expected (`mfe_pct`, `mae_pct`, gross/net pnl, fees, side, regime, reason);
- exact upper bound of document reads.

If trade records are one document per trade, validating 100 canonical trades with
MFE/MAE needs up to 100 document reads, plus only narrowly justified metadata reads.
Do not describe this as 10–20 reads.
```

The budget can still be small relative to quota, but it must be honest.

## Required local work now

Create/update only:

```text
data/research/firebase_reconciliation_phase1_2026-05-22/PHASE1A_CORRECTION_REPORT.md
data/research/firebase_reconciliation_phase1_2026-05-22/metric_scope_table_corrected.csv
data/research/firebase_reconciliation_phase1_2026-05-22/phase1a_metric_formula_search.txt
data/research/firebase_reconciliation_phase1_2026-05-22/phase1a_win_count_formula_search.txt
data/research/firebase_reconciliation_phase1_2026-05-22/phase1a_firebase_contract_search.txt
data/research/firebase_reconciliation_phase1_2026-05-22/firebase_read_budget_plan_corrected.md
```

Do not merely state these will be created. Produce them and report their paths.

## Required report conclusion

Phase 1A final report must begin:

```text
STRATEGY STATUS: NO-GO / RETIRED FOR REAL TRADING
REAL TRADING: FORBIDDEN
RUNTIME PATCH FREEZE: ACTIVE
FIREBASE READS PERFORMED: NO
PF HEADLINE RECONCILIATION: PASS (0.4945 ≈ 0.49)
ENTRY-VS-EXIT CAUSE: UNRESOLVED PENDING RAW MFE/MAE/PRICE-PATH DATA
```

## Firebase approval gate

After completing the local outputs, return a proposed Firebase read plan only.
Do not perform reads.

Approval may be considered only if it states one of:

```text
A. One-trade-per-document storage:
   Maximum reads = up to 100 trade documents + N precisely listed metadata documents.

B. Aggregate-document storage:
   Maximum reads = exact number of aggregate documents discovered in source/schema,
   each containing specifically documented fields.
```

## Report back only

Return:

```text
PHASE 1A COMPLETE?:
RUNTIME/FIREBASE OPERATIONS PERFORMED:
PF RECONCILIATION:
EXPECTANCY RECONCILIATION:
WIN/EVENT COUNT RECONCILIATION:
HEALTH FORMULA SOURCE:
PROVEN LOSS ATTRIBUTION:
ENTRY-VS-EXIT CAUSE:
CORRECTED FIREBASE MAX READS:
APPROVAL REQUESTED?:
OUTPUT FILES CREATED:
```
