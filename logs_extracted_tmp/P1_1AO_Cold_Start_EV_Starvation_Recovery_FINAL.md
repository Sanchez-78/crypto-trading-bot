# CryptoMaster P1.1AO — Cold-Start EV Starvation Recovery

> **Purpose:** restore paper-training sample flow when the bot is stuck in cold-start EV starvation.
>
> **Important:** This is **not** P1.1AN tuning. Do **not** calibrate strategy, TP/SL, attribution logic, or live trading behavior in this patch.
>
> **Target stack:** Python 3.11+  
> **Repo:** `/opt/cryptomaster` on production, Windows dev root likely `C:\Projects\CryptoMaster_srv`  
> **Mode affected:** `paper_train` only  
> **Live/real behavior:** must remain unchanged and must keep hard EV-only enforcement.

---

## 0. Current Production State

P1.1AM economic attribution diagnostics are deployed and working, but P1.1AN is paused because the bot cannot collect enough closed paper-training trades.

Observed blocker from production logs:

```text
on_price(ETHUSDT): Generated valid signal BUY
[ECONOMIC_GATE] Insufficient trade data
[V10.13w DECISION] ... REJECT (NEGATIVE_EV ...)
[V10.13t] ... Rejected negative/zero EV — hard enforcement of EV-only principle
[PAPER_EXPLORE_SKIP] reason=no_bucket_matched bucket=UNKNOWN original_decision=REJECT_NEGATIVE_EV reject_reason=negative_ev
```

Also observed:

```text
idle=234928s
global_trades=0<100
Insufficient trade data
bootstrap active
score negative / EV negative
```

Result:

```text
valid signals exist
→ RDE rejects NEGATIVE_EV
→ paper exploration bucket remains UNKNOWN
→ no PAPER_TRAIN_ENTRY
→ no PAPER_EXIT
→ no LM_STATE_AFTER_UPDATE
→ cannot reach P1.1AN threshold of >=10 closed training trades
```

This is **cold-start EV starvation**.

---

## 1. Patch Goal

Implement **P1.1AO** as a minimal, safe, paper-only recovery patch that lets the bot collect a small number of diagnostic samples from negative-EV rejected signals **only under strict cold-start starvation conditions**.

The new sample path must be isolated into a new probe bucket:

```text
C_NEG_EV_PROBE
```

This bucket is for diagnostic paper training only. It must never affect live or real execution.

---

## 2. Non-Negotiable Safety Rules

1. **Do not change live/real trading behavior.**
2. **Do not allow live/real `REJECT_NEGATIVE_EV` to open any position.**
3. **Do not relax live EV-only enforcement.**
4. **Do not tune TP/SL, strategy, attribution, signal scoring, or P1.1AN calibration.**
5. **Do not remove existing P1.1AD–P1.1AM diagnostics.**
6. **All new routing must be gated by `mode == "paper_train"` or an equivalent existing runtime mode check.**
7. **All probe samples must be clearly tagged with `bucket=C_NEG_EV_PROBE`.**
8. **Probe sampling must have hard caps and must auto-stop after enough cold-start samples exist.**
9. **All changes must include regression tests.**
10. **If code architecture differs, adapt to existing names, but preserve the behavior exactly.**

---

## 3. Root Cause Hypothesis

Current paper exploration likely maps only accepted / weak-positive / routed decisions into training buckets such as:

```text
C_WEAK_EV_TRAIN
```

But negative EV rejects are logged as:

```text
bucket=UNKNOWN
reason=no_bucket_matched
original_decision=REJECT_NEGATIVE_EV
reject_reason=negative_ev
```

So even in `paper_train`, the system has no controlled path to gather cold-start evidence from rejected signals.

This creates a deadlock:

```text
No closed samples → model EV stays negative/unknown
EV stays negative → all signals rejected
All rejected signals → no paper samples
No paper samples → no learning
```

---

## 4. Required Implementation

### 4.1 Add starvation diagnostics

Add a periodic/throttled log:

```text
[PAPER_TRAIN_STARVATION_STATE]
mode=paper_train
idle_s=<float>
global_trades=<int>
lm_total=<int>
open_paper=<int>
negative_ev_rejects_10m=<int>
paper_entries_10m=<int>
last_paper_entry_age_s=<float|na>
economic_data_ready=<bool>
reason=<cold_start_starvation|normal|not_paper_train|...>
```

Emit it only when useful:
- every 60 seconds while in starvation,
- or when state changes,
- throttle to prevent spam.

Also add mismatch diagnostic:

```text
[PAPER_TRAIN_STATE_MISMATCH]
global_trades=<int>
lm_total=<int>
rde_n=<int|na>
reason=lm_has_samples_but_rde_global_zero
```

Trigger when LM has samples but the decision layer still reports `global_trades=0` or equivalent. This catches stale counters / separate state stores.

---

### 4.2 Add `C_NEG_EV_PROBE` bucket

Create a new paper-only bucket:

```python
C_NEG_EV_PROBE = "C_NEG_EV_PROBE"
```

Use existing constants style if available.

Route a negative EV reject to this bucket only if all conditions are true:

```python
mode == "paper_train"
decision in {"REJECT_NEGATIVE_EV", "SKIP_SCORE_HARD"} OR reject_reason == "negative_ev"
economic data is insufficient OR global_trades < 100
idle_s >= 1800  # 30 minutes
no normal paper entries recently
closed_probe_trades < 20
```

The probe route must be logged:

```text
[PAPER_NEG_EV_PROBE_ACCEPTED]
symbol=<symbol>
side=<side>
bucket=C_NEG_EV_PROBE
original_decision=REJECT_NEGATIVE_EV
reject_reason=negative_ev
ev=<float>
score=<float>
global_trades=<int>
lm_total=<int>
idle_s=<float>
reason=cold_start_starvation
```

If probe is blocked, log a throttled reason:

```text
[PAPER_NEG_EV_PROBE_BLOCKED]
symbol=<symbol>
reason=<not_paper_train|not_cold_start|cap_symbol|cap_total|cap_rate|cap_lifetime|recent_entry|missing_signal|...>
```

---

### 4.3 Hard probe caps

The new bucket must be aggressively capped.

Required caps:

```text
max open per symbol: 1
max total open probe positions: 2
max new probe entries per 10 minutes: 2
max closed probe trades lifetime/cold-start window: 20
```

Use existing training sampler cap infrastructure where possible. If there is already per-symbol / per-bucket cap logic, extend it rather than duplicating.

Probe trades must close through the normal paper timeout/exit path and must feed the learning monitor as paper trades, clearly marked with:

```text
bucket=C_NEG_EV_PROBE
training_bucket=C_NEG_EV_PROBE
source=NEGATIVE_EV_PROBE
```

---

### 4.4 Do not pollute live/real or standard training buckets

`C_NEG_EV_PROBE` must be isolated in reporting and learning stats.

Allowed:
- include in LM as diagnostic cold-start samples,
- include in paper quality diagnostics,
- include in audit output,
- include in economic attribution.

Not allowed:
- using probe samples to permit live trading,
- treating probe samples as normal positive-EV proof,
- mixing probe outcomes into `C_WEAK_EV_TRAIN` summaries without bucket label,
- changing live sizing / execution rules.

If existing LM logic aggregates all paper trades together, add bucket labels to diagnostics so probe contribution is visible.

---

### 4.5 Log throttling

Current logs are extremely noisy:

```text
[HBLOCK] SKIP_SCORE_HARD ...
[PAPER_EXPLORE_SKIP] reason=no_bucket_matched ...
```

Add or reuse a throttle helper so identical spam is suppressed.

Throttle keys:

```text
HBLOCK: (symbol, decision/reason, threshold_zone)
PAPER_EXPLORE_SKIP: (symbol, original_decision, reject_reason)
PAPER_NEG_EV_PROBE_BLOCKED: (symbol, reason)
```

Throttle interval:

```text
10 seconds
```

Keep summaries/counters so debugging remains possible.

Do not suppress:
- `PAPER_TRAIN_ENTRY`
- `PAPER_EXIT`
- `LM_STATE_AFTER_UPDATE`
- `PAPER_TRAIN_ECON_ATTRIB`
- `PAPER_NEG_EV_PROBE_ACCEPTED`

---

### 4.6 Audit script extension

Update:

```text
scripts/p11ag_quality_audit.sh
```

Add counters:

```text
NEGATIVE_EV_REJECTS
PAPER_EXPLORE_SKIP_UNKNOWN_BUCKET
PAPER_TRAIN_STARVATION_STATE
PAPER_TRAIN_STATE_MISMATCH
PAPER_NEG_EV_PROBE_ACCEPTED
PAPER_NEG_EV_PROBE_BLOCKED
PAPER_NEG_EV_PROBE_EXIT
PAPER_NEG_EV_PROBE_LM_UPDATE
```

If using pattern counts, preserve P1.1AL scalar safety:
- all counters must be single-line integers,
- use existing `to_int()` / `count_pattern()` helpers,
- no multiline `0\n0` bug regression.

Add a diagnostic section:

```text
Cold-Start Starvation:
-------
NEGATIVE_EV_REJECTS:              <n>
UNKNOWN_BUCKET_SKIPS:             <n>
STARVATION_STATE_LOGS:            <n>
NEG_EV_PROBE_ACCEPTED:            <n>
NEG_EV_PROBE_BLOCKED:             <n>
NEG_EV_PROBE_EXITS:               <n>
NEG_EV_PROBE_LM_UPDATES:          <n>

Diagnostics:
✓ Probe inactive when not starving
✓ Probe accepted under cold-start starvation
⚠️ Negative EV rejects still unknown-bucketed
⚠️ Probe entries exist but no exits yet
✓ Probe exits reached LM
```

---

## 5. Acceptance Criteria

After deployment and 30–60 minutes in `paper_train`, audit should show one of these acceptable states.

### State A — probe not needed

```text
PAPER_TRAIN_ENTRY > 0
PAPER_EXPLORE_SKIP_UNKNOWN_BUCKET low/stable
PAPER_NEG_EV_PROBE_ACCEPTED = 0
```

Meaning normal training resumed.

### State B — probe active and working

```text
PAPER_TRAIN_STARVATION_STATE >= 1
PAPER_NEG_EV_PROBE_ACCEPTED >= 1
PAPER_TRAIN_ENTRY includes bucket=C_NEG_EV_PROBE
PAPER_EXIT includes training_bucket=C_NEG_EV_PROBE
LM_STATE_AFTER_UPDATE increments
QUALITY_EXIT_MISSING_BY_TRADE_ID = 0
LM_UPDATE_MISMATCH = 0
```

### State C — hard stop / investigation needed

```text
NEGATIVE_EV_REJECTS high
PAPER_EXPLORE_SKIP_UNKNOWN_BUCKET high
PAPER_NEG_EV_PROBE_ACCEPTED = 0
```

If State C happens, logs must clearly explain why probes were blocked.

---

## 6. Suggested Files to Inspect

Search first; do not assume exact names.

Likely files:

```text
src/services/realtime_decision_engine.py
src/services/trade_executor.py
src/services/paper_trade_executor.py
src/services/learning_monitor.py
src/services/training_sampler.py
src/services/*sampler*.py
src/services/*bucket*.py
scripts/p11ag_quality_audit.sh
tests/test_paper_mode.py
```

Find existing symbols/logs:

```text
PAPER_EXPLORE_SKIP
PAPER_TRAIN_ENTRY
C_WEAK_EV_TRAIN
REJECT_NEGATIVE_EV
SKIP_SCORE_HARD
training_sampler
check_and_close_timeout_positions
LM_STATE_AFTER_UPDATE
```

---

## 7. Implementation Plan

### Step 1 — Trace current reject routing

Find where this log is emitted:

```text
[PAPER_EXPLORE_SKIP] reason=no_bucket_matched bucket=UNKNOWN
```

Identify:
- input decision object,
- reject reason field,
- mode check,
- bucket selection function,
- why negative EV maps to UNKNOWN.

Do not patch blindly.

---

### Step 2 — Add bucket classification

Add a function or extend existing bucket resolver:

```python
def classify_paper_training_bucket(decision, signal, context) -> str | None:
    ...
```

Required behavior:

```python
if is_paper_train and is_cold_start_starvation and is_negative_ev_reject:
    return "C_NEG_EV_PROBE"
```

If architecture already has a bucket classifier, extend it minimally.

---

### Step 3 — Add caps

Add cap checks before opening probe trades:

```python
max_open_per_symbol = 1
max_open_total = 2
max_new_per_10m = 2
max_closed_probe_total = 20
```

Prefer existing sampler state and counters. Add testable helpers if needed.

---

### Step 4 — Wire to paper entry

When probe accepted, open via existing paper-train entry path.

Ensure logs include:

```text
source=NEGATIVE_EV_PROBE
bucket=C_NEG_EV_PROBE
training_bucket=C_NEG_EV_PROBE
original_decision=REJECT_NEGATIVE_EV
reject_reason=negative_ev
```

Do not bypass existing paper position safety checks.

---

### Step 5 — Add diagnostics and throttling

Add:
- `[PAPER_TRAIN_STARVATION_STATE]`
- `[PAPER_TRAIN_STATE_MISMATCH]`
- `[PAPER_NEG_EV_PROBE_ACCEPTED]`
- `[PAPER_NEG_EV_PROBE_BLOCKED]`
- throttled `HBLOCK` / `PAPER_EXPLORE_SKIP`.

Keep logs structured and grep-friendly.

---

### Step 6 — Extend audit script

Update `scripts/p11ag_quality_audit.sh`.

Run shell tests if present. If no shell tests exist, add minimal shell tests around:
- scalar counts,
- new counters,
- no multiline integer comparison bug.

---

## 8. Required Tests

Add at least 10 regression tests. Names can differ, but coverage must match.

### Test group: activation

1. `test_neg_ev_probe_activates_in_paper_train_cold_start`
   - Given `mode=paper_train`, `global_trades=0`, `idle_s>1800`, negative EV reject
   - Expect bucket `C_NEG_EV_PROBE`

2. `test_neg_ev_probe_does_not_activate_when_not_starving`
   - Given recent paper entry or idle below threshold
   - Expect no probe bucket

3. `test_neg_ev_probe_does_not_activate_after_lifetime_cap`
   - Given closed probe trades >=20
   - Expect blocked

### Test group: caps

4. `test_neg_ev_probe_cap_one_open_per_symbol`
5. `test_neg_ev_probe_cap_two_total_open`
6. `test_neg_ev_probe_rate_limit_two_per_10m`

### Test group: live/real isolation

7. `test_negative_ev_never_routes_to_probe_in_live_mode`
8. `test_negative_ev_never_routes_to_probe_in_real_mode`

These two are critical.

### Test group: diagnostics

9. `test_starvation_state_log_emitted_when_unknown_bucket_repeats`
10. `test_state_mismatch_log_when_lm_total_positive_but_global_trades_zero`
11. `test_probe_logs_include_source_bucket_and_original_decision`
12. `test_hblock_and_explore_skip_are_throttled`

If test count needs to stay lower, combine diagnostics tests but preserve behavior coverage.

---

## 9. Validation Commands

After implementation:

```bash
python -m pytest tests/test_paper_mode.py -q
python -m pytest -q
```

If shell tests exist:

```bash
bash tests/test_p11ag_quality_audit.sh
```

Production validation:

```bash
cd /opt/cryptomaster

git rev-parse --short HEAD
git merge-base --is-ancestor <P1.1AO_COMMIT> HEAD && echo "OK P1.1AO" || echo "BAD P1.1AO missing"

sudo systemctl restart cryptomaster
sleep 15

PID=$(systemctl show -p MainPID --value cryptomaster)
echo "PID=$PID"

bash scripts/p11ag_quality_audit.sh --since "30 min ago"
```

Manual grep:

```bash
sudo journalctl -u cryptomaster --since "30 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "PAPER_TRAIN_STARVATION_STATE|PAPER_TRAIN_STATE_MISMATCH|PAPER_NEG_EV_PROBE_ACCEPTED|PAPER_NEG_EV_PROBE_BLOCKED|PAPER_TRAIN_ENTRY|PAPER_EXIT|LM_STATE_AFTER_UPDATE|PAPER_EXPLORE_SKIP" \
| tail -200
```

Probe-specific check:

```bash
sudo journalctl -u cryptomaster --since "60 min ago" --no-pager \
| grep "cryptomaster\[$PID\]" \
| grep -E "C_NEG_EV_PROBE|NEGATIVE_EV_PROBE|PAPER_NEG_EV_PROBE" \
| tail -200
```

---

## 10. Expected Production Result

Before P1.1AO:

```text
valid signal
REJECT_NEGATIVE_EV
PAPER_EXPLORE_SKIP bucket=UNKNOWN
no paper entry
```

After P1.1AO under starvation:

```text
valid signal
REJECT_NEGATIVE_EV
[PAPER_TRAIN_STARVATION_STATE] reason=cold_start_starvation
[PAPER_NEG_EV_PROBE_ACCEPTED] bucket=C_NEG_EV_PROBE
[PAPER_TRAIN_ENTRY] bucket=C_NEG_EV_PROBE source=NEGATIVE_EV_PROBE
...
[PAPER_EXIT] training_bucket=C_NEG_EV_PROBE
[LM_STATE_AFTER_UPDATE] source=paper_closed_trade
```

This should allow the bot to collect enough closed training samples to resume the P1.1AN audit gate.

---

## 11. Final Response Format

When done, respond with:

```text
P1.1AO Complete

Commit: <hash>

Changed Files:
- ...

Implemented:
1. ...
2. ...
3. ...

Tests:
- <n> passing
- live/real negative-EV isolation verified

Production Validation:
<commands>

Expected:
- PAPER_NEG_EV_PROBE_ACCEPTED appears only in paper_train starvation
- C_NEG_EV_PROBE entries close normally
- LM_STATE_AFTER_UPDATE increments
- no live/real behavior changed
```

---

## 12. Hard Stop Conditions

Stop and report instead of patching if:
- runtime mode cannot be determined safely,
- negative-EV route shares code with live execution and cannot be isolated,
- paper entry path cannot label bucket/source,
- existing tests reveal live/real behavior would change,
- audit script cannot be made scalar-safe.

Do not implement speculative broad rewrites.
