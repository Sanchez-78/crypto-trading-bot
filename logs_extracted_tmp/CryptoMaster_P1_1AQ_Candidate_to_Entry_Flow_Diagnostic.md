# CryptoMaster P1.1AQ — Candidate-to-Entry Flow Diagnostic

## Status Before This Patch

Production is running:

```text
HEAD: 8aaa934
Patch: P1.1AP
Scope of P1.1AP: shell/diagnostics only
Trading behavior changed by P1.1AP: NO
```

P1.1AP validation result:

```text
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

Core viewer output is clean:

```text
No blank exit rows
No false starvation warning
No errors/mismatches
```

## Interpretation

P1.1AP itself is validated as a diagnostics cleanup.

The current blocker is not negative-EV starvation and not viewer parsing.

The real blocker is:

```text
COST_EDGE_BYPASS_CANDIDATE > 0
COST_EDGE_BYPASS_ACCEPTED = 0
PAPER_TRAIN_ENTRY_REAL = 0
```

Meaning:

- candidates reach the cost-edge bypass candidate stage,
- none are accepted downstream,
- no new paper training samples open,
- P1.1AN cannot progress because closed training trades remain below 10.

## Objective

Implement P1.1AQ as a minimal diagnostic/flow-recovery patch.

Goal:

```text
Explain and fix why bypass candidates do not become accepted paper training entries.
```

Do not tune trading economics yet.

Do not change live/real trading behavior.

Do not change TP/SL, fees, EV formula, RDE thresholds, or P1.1AN economic calibration.

---

## Hard Safety Constraints

1. Live/real behavior must remain unchanged.
2. Any behavioral change must be gated to:

```python
mode == "paper_train"
bucket == "C_WEAK_EV_TRAIN"
cold_start / bootstrap context only
```

3. Prefer diagnostics first.
4. Do not implement P1.1AN calibration in this patch.
5. Do not remove EV-only enforcement for live/real.
6. Preserve all P1.1AD–P1.1AP diagnostics and tests.

---

## Required Investigation

Trace this exact path:

```text
COST_EDGE_BYPASS_CANDIDATE
  -> downstream sampler/caps/duplicate/entry gate
  -> COST_EDGE_BYPASS_ACCEPTED
  -> PAPER_TRAIN_ENTRY
  -> PAPER_TRAIN_QUALITY_ENTRY
```

Find the first drop point after `COST_EDGE_BYPASS_CANDIDATE`.

Check likely blockers:

1. Training sampler caps:
   - max open per symbol
   - max open per bucket
   - total open cap
   - lifetime cap
   - cooldown/rate limit

2. Candidate duplicate gate:
   - same symbol/side/bucket marked too early
   - duplicate check happens before actual accepted entry
   - stale duplicate marks after rejected candidates

3. Open position state:
   - `data/paper_open_positions.json` contains stale/orphan positions
   - runtime open count differs from file state
   - positions are not closing after restart
   - non-training positions consume sampler caps

4. Routing mismatch:
   - candidate has bucket `C_WEAK_EV_TRAIN`
   - accepted path expects another bucket key
   - `training_bucket` missing or overwritten
   - source not allowed after bypass

5. Audit/logging mismatch:
   - accepted entries happen but `COST_EDGE_BYPASS_ACCEPTED` log is not emitted
   - entry happens through a non-bypass source and is counted differently

6. Probe/cold-start logic:
   - negative-EV probe is not involved here because:
     - `NEGATIVE_EV_REJECTS = 0`
     - `UNKNOWN_BUCKET_SKIPS = 0`
     - `NEG_EV_PROBE_ACCEPTED = 0`
   - do not focus on probe unless logs prove negative-EV rejects resumed.

---

## Add Required Diagnostic Logs

Add lightweight, throttled diagnostics around each candidate after cost-edge bypass candidate detection.

### 1. After bypass candidate is identified

Add:

```text
[COST_EDGE_BYPASS_FLOW] stage=candidate symbol=<s> bucket=<b> source=<src> reason=<r> trades=<n>
```

### 2. When candidate is rejected after bypass candidate stage

Add one normalized drop log:

```text
[COST_EDGE_BYPASS_FLOW] stage=drop symbol=<s> bucket=<b> reason=<reason> open_symbol=<n> open_bucket=<n> open_total=<n> duplicate_age_s=<x> source=<src>
```

Drop reasons should be explicit and finite, for example:

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
entry_exception
position_state_stale
unknown
```

### 3. When accepted

Ensure this exists and is emitted exactly once:

```text
[COST_EDGE_BYPASS_ACCEPTED] mode=paper_train symbol=<s> bucket=C_WEAK_EV_TRAIN reason=bootstrap_training_sample source=<src> open_symbol=<n> open_bucket=<n> open_total=<n>
```

### 4. At paper entry attempt

Add or verify:

```text
[PAPER_ENTRY_ATTEMPT] symbol=<s> bucket=<b> source=<src> cost_edge_bypassed=<true/false>
```

### 5. At paper entry blocked

Add or verify:

```text
[PAPER_ENTRY_BLOCKED] reason=<reason> symbol=<s> bucket=<b> source=<src> open_symbol=<n> open_bucket=<n> open_total=<n>
```

Throttle repetitive logs by `(symbol, stage, reason)` every 10 seconds.

---

## Add Audit Script Counters

Update `scripts/p11ag_quality_audit.sh` with a new section:

```text
Candidate-to-Entry Flow:
-------
COST_EDGE_BYPASS_CANDIDATE:
COST_EDGE_BYPASS_ACCEPTED:
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
entry_exception:
position_state_stale:
unknown:
```

Add diagnostic decision:

```text
if COST_EDGE_BYPASS_CANDIDATE > 0 and COST_EDGE_BYPASS_ACCEPTED == 0 and PAPER_TRAIN_ENTRY_REAL == 0:
    print "⚠️ Bypass candidates are not reaching paper entries"
    print top drop reason if available
```

Keep all counters scalar-safe using existing `to_int()` / `count_pattern()` helpers.

---

## Optional Read-Only State Check Script

Add a read-only helper if useful:

```text
scripts/p11aq_paper_state_check.sh
```

It should print:

```text
- current git HEAD
- service PID
- paper_open_positions.json exists: yes/no
- number of open positions in file
- count by symbol
- count by training_bucket
- max age if timestamps exist
- whether any stale position age > hold_limit_s + 60
```

It must not mutate files.

---

## Minimal Fix Rules

Only implement a fix if root cause is confirmed.

Possible fixes:

### Case 1 — stale open positions consume caps

If file/runtime state has stale paper positions older than hold limit and no matching runtime close path:

- add diagnostic warning first,
- then add paper_train-only cleanup or rehydration-safe timeout close,
- do not delete live positions,
- do not affect real/live mode.

### Case 2 — duplicate gate marks candidates before acceptance

If duplicate marks happen before entry is accepted:

- move mark to after actual accepted entry attempt,
- preserve duplicate protection,
- add tests.

### Case 3 — accepted log missing but entries exist

If entries exist but accepted log missing:

- logging-only fix,
- no behavior change.

### Case 4 — sampler caps too strict but correct

If caps are working as designed and there are open positions:

- do not loosen caps yet,
- improve audit message to say `blocked_by_caps_wait_for_exits`,
- wait for exits.

### Case 5 — candidate source/bucket mismatch

If source/bucket metadata is dropped:

- preserve `bucket=C_WEAK_EV_TRAIN`
- preserve `training_bucket=C_WEAK_EV_TRAIN`
- preserve `cost_edge_bypassed=True`
- add tests for metadata propagation.

---

## Required Tests

Add tests to `tests/test_paper_mode.py`.

Minimum tests:

1. `COST_EDGE_BYPASS_CANDIDATE` followed by sampler cap block emits `[COST_EDGE_BYPASS_FLOW] stage=drop reason=sampler_*`.
2. Duplicate candidate drop emits `reason=duplicate_candidate`.
3. Accepted candidate emits exactly one `[COST_EDGE_BYPASS_ACCEPTED]`.
4. Accepted candidate produces `PAPER_TRAIN_ENTRY` with `training_bucket=C_WEAK_EV_TRAIN`.
5. Live mode never emits accepted/probe/bypass-flow paper training entry.
6. Real mode never emits accepted/probe/bypass-flow paper training entry.
7. Audit script handles zero candidates.
8. Audit script handles candidates > 0 and accepted = 0.
9. Audit script drop reason counters are scalar-safe.
10. Existing P1.1AD–P1.1AP tests still pass.

---

## Production Validation Commands

After implementation and deploy:

```bash
cd /opt/cryptomaster
git fetch origin
git pull --ff-only

git rev-parse --short HEAD
sudo systemctl restart cryptomaster
sleep 10

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "45 min ago"
bash scripts/p11ak_core_flow_viewer_cs.sh --since "45 min ago"
```

If no entries yet, inspect direct logs:

```bash
sudo journalctl -u cryptomaster --since "45 min ago" --no-pager   | grep "cryptomaster\[$PID\]"   | grep -E "COST_EDGE_BYPASS|COST_EDGE_BYPASS_FLOW|PAPER_ENTRY_ATTEMPT|PAPER_ENTRY_BLOCKED|PAPER_TRAIN_ENTRY|PAPER_TIMEOUT_SCAN|PAPER_EXIT|LM_STATE_AFTER_UPDATE"   | tail -200
```

If state check script was added:

```bash
bash scripts/p11aq_paper_state_check.sh
```

---

## Pass Criteria

P1.1AQ passes if one of these is true:

### PASS A — Normal flow restored

```text
COST_EDGE_BYPASS_CANDIDATE > 0
COST_EDGE_BYPASS_ACCEPTED > 0
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
```

### PASS B — Correct block reason proven

```text
COST_EDGE_BYPASS_CANDIDATE > 0
COST_EDGE_BYPASS_ACCEPTED = 0
PAPER_TRAIN_ENTRY_REAL = 0
COST_EDGE_BYPASS_FLOW_DROP > 0
top drop reason is explicit and actionable
```

### PASS C — No candidates in clean idle period

```text
COST_EDGE_BYPASS_CANDIDATE = 0
PAPER_TRAIN_ENTRY_REAL = 0
No false starvation warning
No mismatches
```

---

## P1.1AN Gate Remains Blocked

Do not resume P1.1AN until:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
one attribution > 50%
```

Current known post-P1.1AO/pre-P1.1AP sample:

```text
closed_training_trades: 4
ATTR_FEE_DOMINATED_MOVE: 2
ATTR_COST_EDGE_BYPASS_LOSS: 2
Decision: TUNE_ALLOWED = NO
```

P1.1AQ is only to restore/diagnose sample flow so P1.1AN can later proceed with enough data.
