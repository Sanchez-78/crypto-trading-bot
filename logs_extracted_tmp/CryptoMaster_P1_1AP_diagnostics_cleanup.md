# CryptoMaster — P1.1AO Post-Audit Verdict + P1.1AP Diagnostics Cleanup Prompt

## Current audit verdict

P1.1AO is deployed and working.

```text
HEAD: a7afaa9
PID: 1053800
PAPER_TRAIN_ENTRY_REAL: 4
PAPER_TRAIN_QUALITY_ENTRY: 4
PAPER_TRAIN_QUALITY_EXIT_TRAINING_BUCKET: 4
PAPER_EXIT_TRAINING_BUCKET: 4
QUALITY_EXIT_MISSING_BY_TRADE_ID: 0
PAPER_TRAIN_QUALITY_MISMATCH: 0
LM_STATE_AFTER_UPDATE: 4
LM_UPDATE_MISMATCH: 0
Latest Total trades in LM: 5
```

## Interpretation

### PASS: P1.1AO normal training flow restored

Normal `C_WEAK_EV_TRAIN` flow is producing entries and exits again.

```text
PAPER_TRAIN_ENTRY_REAL = 4
PAPER_TRAIN_QUALITY_ENTRY = 4
PAPER_TRAIN_QUALITY_EXIT_TRAINING_BUCKET = 4
LM_STATE_AFTER_UPDATE = 4
```

This means:

- entry logging is healthy
- quality entry/exit diagnostics are healthy
- training exits are correlated by trade ID
- LM updates are visible
- no quality or LM mismatch is present

### OK: negative-EV probe did not activate

```text
NEGATIVE_EV_REJECTS: 0
UNKNOWN_BUCKET_SKIPS: 0
NEG_EV_PROBE_ACCEPTED: 0
NEG_EV_PROBE_BLOCKED: 0
NEG_EV_PROBE_EXITS: 0
```

This is acceptable because normal training entries resumed. The probe is only a fallback for starvation, not the primary training path.

### False-positive warning

The audit prints:

```text
⚠️ Starvation detected but no probes accepted — check caps/conditions
```

But the counters show:

```text
STARVATION_STATE_LOGS: 1
NEGATIVE_EV_REJECTS: 0
UNKNOWN_BUCKET_SKIPS: 0
PAPER_TRAIN_ENTRY_REAL: 4
```

So this warning is currently misleading. It should only fire when there are negative-EV rejects / unknown bucket skips and no normal training entries.

### Core viewer issue

The core flow viewer prints blank exit rows:

```text
✓  outcome=LOSS pnl= reason=
```

This is a parser/display issue, likely from matching multiple log types or not guarding missing fields. It is not evidence of trading logic failure because the audit trade-ID correlation is clean.

### Non-training/orphan exit

Audit shows:

```text
PAPER_EXIT: 5
PAPER_EXIT_TRAINING_BUCKET: 4
```

There is one extra paper exit outside the training-bucket correlation. Since:

```text
QUALITY_EXIT_MISSING_BY_TRADE_ID: 0
LM_UPDATE_MISMATCH: 0
```

this is not a blocker. It should be reported separately as `NON_TRAINING_PAPER_EXIT=1` so it does not confuse future audits.

## P1.1AN calibration gate

Do not start P1.1AN yet.

```text
closed_training_trades: 4
required: >=10
```

Attribution is also inconclusive:

```text
FEE_DOMINATED_MOVE: 2 / 50%
COST_EDGE_BYPASS_LOSS: 2 / 50%
```

Decision:

```text
TUNE_ALLOWED: NO
Reason: INSUFFICIENT_SAMPLE_FOR_CALIBRATION + 50/50 attribution tie
```

Need at least 10 closed training trades and one clear dominant attribution above 50%.

---

# Claude Prompt — P1.1AP Diagnostics Cleanup Only

Use this prompt only for a small diagnostics patch. Do not tune strategy.

```markdown
# CryptoMaster P1.1AP — Diagnostics Cleanup After P1.1AO

You are working in an existing Python 3.11+ crypto trading bot.

## Context

P1.1AO is deployed at commit `a7afaa9`.

Latest production audit:

```text
PAPER_TRAIN_ENTRY_REAL: 4
PAPER_TRAIN_QUALITY_ENTRY: 4
PAPER_TRAIN_QUALITY_EXIT_TRAINING_BUCKET: 4
PAPER_EXIT_TRAINING_BUCKET: 4
QUALITY_EXIT_MISSING_BY_TRADE_ID: 0
PAPER_TRAIN_QUALITY_MISMATCH: 0
LM_STATE_AFTER_UPDATE: 4
LM_UPDATE_MISMATCH: 0

NEGATIVE_EV_REJECTS: 0
UNKNOWN_BUCKET_SKIPS: 0
STARVATION_STATE_LOGS: 1
NEG_EV_PROBE_ACCEPTED: 0

PAPER_EXIT: 5
PAPER_EXIT_TRAINING_BUCKET: 4

Attribution:
FEE_DOMINATED_MOVE: 2
COST_EDGE_BYPASS_LOSS: 2
```

## Goal

Implement diagnostics-only cleanup.

Do not change trading behavior, strategy, gates, scoring, EV, TP/SL, cost-edge, sampler acceptance, live execution, or learning logic.

## Problems to fix

### 1. False starvation warning

The audit currently prints:

```text
⚠️ Starvation detected but no probes accepted — check caps/conditions
```

even when:

```text
PAPER_TRAIN_ENTRY_REAL > 0
NEGATIVE_EV_REJECTS = 0
UNKNOWN_BUCKET_SKIPS = 0
```

This is a false positive. `STARVATION_STATE_LOGS > 0` alone is not sufficient for warning.

Fix warning condition so it only fires when all are true:

```text
STARVATION_STATE_LOGS > 0
NEG_EV_PROBE_ACCEPTED = 0
PAPER_TRAIN_ENTRY_REAL = 0
AND (NEGATIVE_EV_REJECTS > 0 OR UNKNOWN_BUCKET_SKIPS > 0)
```

If normal training entries exist, print an informational line instead:

```text
✓ Normal training entries present; probe not required
```

### 2. Core flow viewer blank exits

`scripts/p11ak_core_flow_viewer.sh` prints blank rows like:

```text
✓  outcome=LOSS pnl= reason=
```

Fix parser/display logic:

- Only parse actual `[PAPER_EXIT]` lines for the `EXITS` section.
- Do not treat `[PAPER_TRAIN_QUALITY_EXIT]` or `[PAPER_TRAIN_ECON_ATTRIB]` as normal paper exits.
- If symbol/reason/pnl is missing, do not print a fake checkmark row.
- Optionally print a diagnostic section for malformed lines with count only.

Expected clean output:

```text
← EXITS:
  ✓ ETHUSDT outcome=LOSS pnl=-0.0776 reason=TIMEOUT
  ✓ BTCUSDT outcome=LOSS pnl=-0.1369 reason=TIMEOUT
  ✓ ADAUSDT outcome=LOSS pnl=-0.2653 reason=TIMEOUT
  ✓ BTCUSDT outcome=LOSS pnl=-0.1504 reason=TIMEOUT
```

No blank rows.

### 3. Show LM updates in core viewer

Audit shows:

```text
LM_STATE_AFTER_UPDATE: 4
```

but the core viewer section `LEARNING UPDATES` appears empty.

Fix the viewer to display `[LM_STATE_AFTER_UPDATE]` lines as learning updates.

Expected:

```text
📚 LEARNING UPDATES:
  ✓ ETHUSDT before_total=0 after_total=1 outcome=LOSS
  ✓ BTCUSDT before_total=1 after_total=2 outcome=LOSS
```

Use available fields. Do not fail if one optional field is missing.

### 4. Add non-training paper exit count

Audit currently shows:

```text
PAPER_EXIT: 5
PAPER_EXIT_TRAINING_BUCKET: 4
```

Add a derived counter:

```text
PAPER_EXIT_NON_TRAINING: 1
```

This should be informational only and must not create a failure when:

```text
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
LM_UPDATE_MISMATCH = 0
```

Add diagnostic text:

```text
ℹ️ Found 1 non-training/orphan paper exit(s); excluded from training quality correlation
```

## Files likely involved

- `scripts/p11ag_quality_audit.sh`
- `scripts/p11ak_core_flow_viewer.sh`
- shell tests if present, or add new shell regression tests

Do not modify Python trading code unless absolutely necessary. This patch should be shell/diagnostics only.

## Tests required

Add shell tests or script-level regression fixtures for:

1. Starvation state exists but normal training entries exist → no warning, show probe not required.
2. Starvation state exists + negative EV rejects + no entries + no probe accepted → warning appears.
3. Core viewer does not print blank exit rows when quality/attrib logs are present.
4. Core viewer displays `LM_STATE_AFTER_UPDATE`.
5. Audit reports `PAPER_EXIT_NON_TRAINING`.

Run:

```bash
bash -n scripts/p11ag_quality_audit.sh
bash -n scripts/p11ak_core_flow_viewer.sh
python -m pytest tests/test_paper_mode.py -q
```

If shell tests exist, run them too.

## Acceptance criteria

Production audit should show:

```text
PAPER_TRAIN_ENTRY_REAL >= 1
PAPER_TRAIN_QUALITY_ENTRY >= PAPER_TRAIN_ENTRY_REAL
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
LM_UPDATE_MISMATCH = 0
```

And for the current non-starved case:

```text
✓ Normal training entries present; probe not required
```

No false starvation warning.

Core flow viewer must not show blank exit rows.
```

---

## Next production command

Run after more training closes:

```bash
cd /opt/cryptomaster
bash scripts/p11ag_quality_audit.sh --since "90 min ago"
bash scripts/p11ak_core_flow_viewer.sh --since "90 min ago"
```

Do P1.1AN only when:

```text
PAPER_TRAIN_ECON_ATTRIB >= 10
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
LM_UPDATE_MISMATCH = 0
dominant attribution > 50%
```
