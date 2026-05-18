# CryptoMaster P1.1AP — Diagnostics Cleanup Implementation Prompt

## Status

P1.1AO is complete and deployed at:

```text
HEAD: a7afaa9
```

Current production state:

```text
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

P1.1AO cold-start recovery is working. Normal `C_WEAK_EV_TRAIN` samples are flowing again.

P1.1AN remains blocked:

```text
closed_training_trades: 4 / 10 required
attribution: 50/50 tie
FEE_DOMINATED_MOVE: 2
COST_EDGE_BYPASS_LOSS: 2
TUNE_ALLOWED: NO
```

## Goal

Implement **P1.1AP diagnostics cleanup only**.

This is a shell/log parsing cleanup patch. Do not change trading behavior.

## Hard Scope Rules

Do not modify:

- RDE logic
- signal generation
- EV calculation
- score thresholds
- paper training sampler behavior
- negative-EV probe behavior
- cost-edge bypass behavior
- TP/SL geometry
- live/real execution
- learning update semantics
- Python trading code unless absolutely necessary for tests/imports

Prefer editing only:

```text
scripts/p11ag_quality_audit.sh
scripts/p11ak_core_flow_viewer_cs.sh
```

If both Czech and English viewer scripts exist, inspect both and keep behavior consistent:

```text
scripts/p11ak_core_flow_viewer.sh
scripts/p11ak_core_flow_viewer_cs.sh
```

## Issues To Fix

---

## Issue 1 — False Starvation Warning

### Current problem

Audit prints:

```text
⚠️ Starvation detected but no probes accepted — check caps/conditions
```

even when normal training entries exist.

Observed counters:

```text
STARVATION_STATE_LOGS: 1
NEGATIVE_EV_REJECTS: 0
UNKNOWN_BUCKET_SKIPS: 0
NEG_EV_PROBE_ACCEPTED: 0
PAPER_TRAIN_ENTRY_REAL: 4
```

This is not starvation. Probe is not required because normal training flow is active.

### Required fix

In `scripts/p11ag_quality_audit.sh`, change warning condition.

Only warn when all are true:

```text
STARVATION_STATE_LOGS > 0
NEG_EV_PROBE_ACCEPTED = 0
PAPER_TRAIN_ENTRY_REAL = 0
AND (NEGATIVE_EV_REJECTS > 0 OR UNKNOWN_BUCKET_SKIPS > 0)
```

When normal training entries exist, print:

```text
✓ Normal training entries present; probe not required
```

When no starvation signals exist, print nothing or a neutral OK line.

### Acceptance

For current production state, audit must not print the starvation warning.

---

## Issue 2 — Core Viewer Blank Exit Rows

### Current problem

Core viewer prints blank exit rows like:

```text
✓  outcome=LOSS pnl= reason=
```

This likely happens because the parser matches `[PAPER_TRAIN_QUALITY_EXIT]` or `[PAPER_TRAIN_ECON_ATTRIB]` lines as if they were `[PAPER_EXIT]` lines, or because it prints rows even when symbol/pnl/reason fields are missing.

### Required fix

In `scripts/p11ak_core_flow_viewer_cs.sh`:

- Parse only actual `[PAPER_EXIT]` lines for the `EXITS` section.
- Exclude:
  - `[PAPER_TRAIN_QUALITY_EXIT]`
  - `[PAPER_TRAIN_ECON_ATTRIB]`
  - other quality/economic diagnostic lines
- Do not print a success/checkmark row unless required fields are present:
  - `symbol`
  - `outcome`
  - `net_pnl_pct`
  - `reason`
- If malformed exit-like lines are encountered, count them separately but do not show fake checkmark rows.

Example acceptable output:

```text
← EXITS:
  ✓ ETHUSDT outcome=LOSS pnl=-0.0776 reason=TIMEOUT
  ✓ BTCUSDT outcome=LOSS pnl=-0.1369 reason=TIMEOUT
  ✓ ADAUSDT outcome=LOSS pnl=-0.2653 reason=TIMEOUT
  ✓ BTCUSDT outcome=LOSS pnl=-0.1504 reason=TIMEOUT
```

No blank rows.

---

## Issue 3 — Missing LM Update Display

### Current problem

Audit shows:

```text
LM_STATE_AFTER_UPDATE: 4
```

but the core viewer `LEARNING UPDATES` section is empty.

### Required fix

In `scripts/p11ak_core_flow_viewer_cs.sh`, display `[LM_STATE_AFTER_UPDATE]` lines.

Recommended format:

```text
📚 LEARNING UPDATES:
  ✓ ETHUSDT BEAR_TREND before_total=0 after_total=1 outcome=LOSS
  ✓ BTCUSDT BULL_TREND before_total=1 after_total=2 outcome=LOSS
```

Required fields if available:

- `symbol`
- `regime`
- `before_total`
- `after_total`
- `outcome`

If `regime` is missing, still print a useful row without failing.

Do not require `[LEARNING_UPDATE] ok=True` because current visible update signal is `[LM_STATE_AFTER_UPDATE]`.

---

## Issue 4 — Non-Training Paper Exit Count

### Current problem

Audit shows:

```text
PAPER_EXIT: 5
PAPER_EXIT_TRAINING_BUCKET: 4
```

This creates confusion because one exit is not part of training quality correlation.

### Required fix

In `scripts/p11ag_quality_audit.sh`, add derived counter:

```text
PAPER_EXIT_NON_TRAINING = PAPER_EXIT - PAPER_EXIT_TRAINING_BUCKET
```

Clamp to zero if negative.

Display in Log Counts:

```text
PAPER_EXIT_NON_TRAINING:          1
```

Add informational diagnostic only when count > 0:

```text
ℹ️ Found 1 non-training/orphan paper exit(s); excluded from training quality correlation
```

This must not be a failure when:

```text
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
LM_UPDATE_MISMATCH = 0
```

---

## Tests Required

Add shell-level tests if a shell test framework already exists.

If no shell test framework exists, add minimal fixture-based tests under the existing test layout without introducing heavy dependencies.

Required regression cases:

1. Starvation state exists + normal training entries exist  
   Expected: no starvation warning; prints `Normal training entries present; probe not required`.

2. Starvation state exists + no entries + negative EV rejects + no probe accepted  
   Expected: starvation warning appears.

3. Core viewer receives mixed logs:
   - `[PAPER_EXIT]`
   - `[PAPER_TRAIN_QUALITY_EXIT]`
   - `[PAPER_TRAIN_ECON_ATTRIB]`  
   Expected: only `[PAPER_EXIT]` rows appear in exits; no blank rows.

4. Core viewer receives `[LM_STATE_AFTER_UPDATE]`  
   Expected: learning updates section is populated.

5. Audit with:
   ```text
   PAPER_EXIT=5
   PAPER_EXIT_TRAINING_BUCKET=4
   ```
   Expected:
   ```text
   PAPER_EXIT_NON_TRAINING=1
   ```

## Validation Commands

Run from repo root:

```bash
bash -n scripts/p11ag_quality_audit.sh
bash -n scripts/p11ak_core_flow_viewer_cs.sh
```

If English viewer exists and was touched:

```bash
bash -n scripts/p11ak_core_flow_viewer.sh
```

Run existing tests:

```bash
python -m pytest tests/test_paper_mode.py -q
```

Run shell tests if present, for example:

```bash
bash tests/*.sh
```

Do not skip existing regression tests.

## Production Validation After Deploy

```bash
cd /opt/cryptomaster
git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 10

bash scripts/p11ag_quality_audit.sh --since "45 min ago"
bash scripts/p11ak_core_flow_viewer_cs.sh --since "45 min ago"
```

Expected audit behavior for current non-starved state:

```text
✓ Quality entry logs match entry count
✓ Training exit logs present
✓ Learning update logs present
✓ Economic summary logged
✓ Normal training entries present; probe not required
```

Expected core viewer behavior:

```text
No blank exit rows.
LM_STATE_AFTER_UPDATE rows visible under learning updates.
```

## Commit Message

Use:

```text
P1.1AP diagnostics cleanup
```

## Final Report Format

Return:

```text
P1.1AP Complete
Commit: <hash>

Changed files:
- ...

Validation:
- bash -n scripts/p11ag_quality_audit.sh: PASS
- bash -n scripts/p11ak_core_flow_viewer_cs.sh: PASS
- python -m pytest tests/test_paper_mode.py -q: PASS

Behavior:
- False starvation warning fixed
- Core viewer blank exit rows fixed
- LM_STATE_AFTER_UPDATE displayed
- PAPER_EXIT_NON_TRAINING added
- No Python trading behavior changed
```
