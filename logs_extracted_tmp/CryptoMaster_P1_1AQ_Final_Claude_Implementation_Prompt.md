# CryptoMaster P1.1AQ — Candidate → Accepted → Entry Flow Diagnostics

## Purpose

Implement **P1.1AQ** as a diagnostic-only patch.

The current production blocker is:

```text
COST_EDGE_BYPASS_CANDIDATE > 0
COST_EDGE_BYPASS_ACCEPTED = 0
PAPER_TRAIN_ENTRY_REAL = 0
```

Recent production snapshot after P1.1AP:

```text
Git HEAD: 8aaa934

PAPER_TRAIN_ENTRY:                0
PAPER_TRAIN_ENTRY_REAL:           0
PAPER_TRAIN_QUALITY_ENTRY:        0
PAPER_TRAIN_QUALITY_EXIT:         0
PAPER_EXIT:                       0
LM_STATE_AFTER_UPDATE:            0

COST_EDGE_BYPASS:                 23
COST_EDGE_BYPASS_CANDIDATE:       23
COST_EDGE_BYPASS_ACCEPTED:        0

NEGATIVE_EV_REJECTS:              0
UNKNOWN_BUCKET_SKIPS:             0
STARVATION_STATE_LOGS:            0
NEG_EV_PROBE_ACCEPTED:            0
NEG_EV_PROBE_BLOCKED:             0
```

Interpretation:

- P1.1AP cleanup is valid.
- False starvation warning is fixed.
- Core viewer output is clean.
- Negative-EV probe is not currently the active path.
- Bypass candidates exist, but none become accepted/entry samples.
- P1.1AN remains blocked because closed training trades are still below 10.

P1.1AQ must answer:

```text
Where exactly does a COST_EDGE_BYPASS_CANDIDATE disappear before PAPER_TRAIN_ENTRY?
```

---

## Hard Scope

This patch is **diagnostics-first**.

Do **not** implement economic tuning.

Do **not** change:

- live/real trading behavior
- EV formula
- score formula
- RDE thresholds
- TP/SL geometry
- fees
- P1.1AN calibration logic
- cost-edge bypass policy unless a metadata/logging bug is proven

Any behavior-affecting fix must be:

```python
mode == "paper_train"
bucket == "C_WEAK_EV_TRAIN"
```

and must be justified by diagnostics.

---

## Required Investigation Path

Trace the exact flow:

```text
[COST_EDGE_BYPASS_CANDIDATE]
  -> sampler / duplicate / cap / metadata gate
  -> [COST_EDGE_BYPASS_ACCEPTED]
  -> [PAPER_ENTRY_ATTEMPT]
  -> [PAPER_TRAIN_ENTRY]
  -> [PAPER_TRAIN_QUALITY_ENTRY]
```

Find the first point where the candidate is dropped.

Likely root causes to inspect:

1. **Training sampler caps**
   - max open per symbol
   - max open per bucket
   - total open cap
   - rate cap
   - lifetime cap

2. **Duplicate gate**
   - candidate marked as duplicate before real acceptance
   - duplicate cache persists after rejection
   - duplicate age falsely near 0 seconds

3. **Stale paper open positions**
   - `data/paper_open_positions.json` contains stale entries
   - runtime open count differs from persisted file
   - non-training/orphan positions consume caps
   - post-restart positions never close

4. **Metadata drop**
   - `bucket` becomes missing/UNKNOWN
   - `training_bucket` not preserved
   - `source` not preserved
   - `cost_edge_bypassed=True` lost before accepted/entry path

5. **Logging gap**
   - accepted candidates exist but `[COST_EDGE_BYPASS_ACCEPTED]` is not emitted
   - paper entries occur through another source and bypass accepted counter stays zero

---

## Add Diagnostic Logs

Add throttled diagnostics. Use 10-second throttling per stable key, e.g.:

```text
(symbol, stage, reason)
```

### 1. Bypass candidate flow start

Emit immediately after bypass candidate is identified:

```text
[COST_EDGE_BYPASS_FLOW] stage=candidate symbol=<symbol> bucket=<bucket> source=<source> reason=<reason> trades=<trades> cost_edge_ok=<bool> cost_edge_bypassed=<bool>
```

### 2. Bypass candidate drop

Emit when candidate is rejected after candidate stage but before accepted entry:

```text
[COST_EDGE_BYPASS_FLOW] stage=drop symbol=<symbol> bucket=<bucket> reason=<drop_reason> source=<source> open_symbol=<n> open_bucket=<n> open_total=<n> duplicate_age_s=<value_or_na> cost_edge_ok=<bool> cost_edge_bypassed=<bool>
```

Drop reasons must be normalized and finite:

```text
sampler_max_open_per_symbol
sampler_max_open_per_bucket
sampler_total_open_cap
sampler_rate_cap
sampler_lifetime_cap
duplicate_candidate
missing_bucket
missing_symbol
missing_side
invalid_source
position_state_stale
entry_exception
unknown
```

### 3. Bypass candidate accepted

Ensure this log exists and is emitted exactly once per accepted bypass sample:

```text
[COST_EDGE_BYPASS_ACCEPTED] mode=paper_train symbol=<symbol> bucket=C_WEAK_EV_TRAIN reason=bootstrap_training_sample source=<source> open_symbol=<n> open_bucket=<n> open_total=<n>
```

### 4. Paper entry attempt

Add or verify:

```text
[PAPER_ENTRY_ATTEMPT] symbol=<symbol> bucket=<bucket> source=<source> cost_edge_ok=<bool> cost_edge_bypassed=<bool> bypass_reason=<reason>
```

### 5. Paper entry blocked

Add or verify:

```text
[PAPER_ENTRY_BLOCKED] reason=<reason> symbol=<symbol> bucket=<bucket> source=<source> open_symbol=<n> open_bucket=<n> open_total=<n>
```

---

## Update Audit Script

Update:

```text
scripts/p11ag_quality_audit.sh
```

Add a new section:

```text
Candidate-to-Entry Flow:
-------
COST_EDGE_BYPASS_CANDIDATE:
COST_EDGE_BYPASS_ACCEPTED:
COST_EDGE_BYPASS_FLOW_CANDIDATE:
COST_EDGE_BYPASS_FLOW_DROP:
PAPER_ENTRY_ATTEMPT:
PAPER_ENTRY_BLOCKED:
PAPER_TRAIN_ENTRY_REAL:
```

Add drop reason breakdown:

```text
Bypass Drop Reasons:
-------
sampler_max_open_per_symbol:
sampler_max_open_per_bucket:
sampler_total_open_cap:
sampler_rate_cap:
sampler_lifetime_cap:
duplicate_candidate:
missing_bucket:
missing_symbol:
missing_side:
invalid_source:
position_state_stale:
entry_exception:
unknown:
```

Add diagnostic interpretation:

```bash
if candidates > 0 and accepted == 0 and paper_train_entry_real == 0 and flow_drop > 0:
  print "⚠️ Bypass candidates are being dropped before paper entry"
  print top drop reason
elif candidates > 0 and accepted == 0 and paper_train_entry_real == 0 and flow_drop == 0:
  print "⚠️ Bypass candidates vanish without a drop log — instrumentation gap remains"
elif candidates > 0 and accepted > 0 and paper_train_entry_real > 0:
  print "✓ Bypass candidate-to-entry flow is active"
```

Keep all counters scalar-safe using existing helpers:

```bash
to_int()
count_pattern()
```

Do not reintroduce multiline integer bugs.

---

## Optional Read-Only State Script

If helpful, add:

```text
scripts/p11aq_paper_state_check.sh
```

Read-only only. No mutation.

Output:

```text
Git HEAD:
Service PID:
paper_open_positions.json exists:
open position count:
count by symbol:
count by bucket/training_bucket:
max age if timestamps exist:
stale positions older than hold_limit_s + 60:
```

This script must never delete, repair, or mutate positions.

---

## Minimal Fix Rules

Implement only if diagnostics prove the cause.

### Case A — stale open positions consume caps

Allowed fix:

- paper_train-only stale state warning
- rehydration-safe timeout close if existing architecture supports it
- no deletion of live/real positions
- no broad reset

### Case B — duplicate gate marks too early

Allowed fix:

- mark duplicate only after accepted entry attempt / entry open path
- preserve duplicate protection
- regression tests required

### Case C — metadata lost

Allowed fix:

- preserve:
  - `bucket=C_WEAK_EV_TRAIN`
  - `training_bucket=C_WEAK_EV_TRAIN`
  - `source`
  - `cost_edge_bypassed`
  - `bypass_reason`
- regression tests required

### Case D — accepted log missing only

Allowed fix:

- logging-only
- no behavior change

### Case E — caps working correctly

Allowed action:

- no cap loosening
- audit should report exact cap reason
- wait for exits

---

## Required Tests

Add tests to:

```text
tests/test_paper_mode.py
```

Minimum tests:

1. Bypass candidate emits `[COST_EDGE_BYPASS_FLOW] stage=candidate`.
2. Sampler cap block emits `[COST_EDGE_BYPASS_FLOW] stage=drop reason=sampler_*`.
3. Duplicate block emits `reason=duplicate_candidate`.
4. Accepted bypass emits exactly one `[COST_EDGE_BYPASS_ACCEPTED]`.
5. Accepted bypass preserves `bucket=C_WEAK_EV_TRAIN`.
6. Accepted bypass preserves `training_bucket=C_WEAK_EV_TRAIN`.
7. Accepted bypass preserves `cost_edge_bypassed=True`.
8. Live mode never routes bypass candidate into paper entry.
9. Real mode never routes bypass candidate into paper entry.
10. Audit script handles:
    - zero candidates
    - candidates > 0 / accepted = 0
    - flow drop reason counters
    - scalar-safe counters

Run:

```bash
python -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh
```

If state script added:

```bash
bash -n scripts/p11aq_paper_state_check.sh
```

---

## Production Validation

Deploy:

```bash
cd /opt/cryptomaster
git fetch origin
git pull --ff-only

git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 10

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"
```

Run audit:

```bash
bash scripts/p11ag_quality_audit.sh --since "45 min ago"
bash scripts/p11ak_core_flow_viewer_cs.sh --since "45 min ago"
```

Direct focused log check:

```bash
sudo journalctl -u cryptomaster --since "45 min ago" --no-pager   | grep "cryptomaster\[$PID\]"   | grep -E "COST_EDGE_BYPASS|COST_EDGE_BYPASS_FLOW|PAPER_ENTRY_ATTEMPT|PAPER_ENTRY_BLOCKED|PAPER_TRAIN_ENTRY|PAPER_TIMEOUT_SCAN|PAPER_EXIT|LM_STATE_AFTER_UPDATE"   | tail -200
```

If added:

```bash
bash scripts/p11aq_paper_state_check.sh
```

---

## Pass Criteria

### PASS A — flow active

```text
COST_EDGE_BYPASS_CANDIDATE > 0
COST_EDGE_BYPASS_ACCEPTED > 0
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
```

### PASS B — block reason proven

```text
COST_EDGE_BYPASS_CANDIDATE > 0
COST_EDGE_BYPASS_ACCEPTED = 0
PAPER_TRAIN_ENTRY_REAL = 0
COST_EDGE_BYPASS_FLOW_DROP > 0
top drop reason is explicit and actionable
```

### PASS C — clean idle

```text
COST_EDGE_BYPASS_CANDIDATE = 0
PAPER_TRAIN_ENTRY_REAL = 0
no false starvation warning
no mismatch
```

---

## P1.1AN Remains Blocked

Do not resume P1.1AN until production shows:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
one attribution > 50%
```

Known recent sample before P1.1AP:

```text
closed_training_trades = 4
FEE_DOMINATED_MOVE = 2
COST_EDGE_BYPASS_LOSS = 2
Decision: TUNE_ALLOWED = NO
```

P1.1AQ is only to diagnose/restore sample flow.
