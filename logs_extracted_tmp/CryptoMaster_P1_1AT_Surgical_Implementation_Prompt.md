# CryptoMaster P1.1AT — Paper Sampler Rate-Cap Reservation Fix

## Purpose

Implement one surgical fix only.

P1.1AS production audit confirmed that the paper training sampler rate-cap is consuming/reserving slots before a real paper training entry exists.

This blocks future samples with `sampler_rate_cap`, even though:

```text
PAPER_TRAIN_ENTRY_REAL = 0
open_total = 0
closed_training = 0
recent_entries = 3
rate_limit = 3
```

The goal of P1.1AT is to make rate-cap accounting reflect successful entries only.

---

## Hard Freeze

Do not expand diagnostics.

Do not tune economics.

Do not change strategy.

Do not change TP/SL.

Do not change live/real behavior.

Do not add dashboards.

Do not modify attribution logic.

Allowed change only:

```text
Move rate-cap timestamp commit from pre-entry gate to post-successful paper entry creation.
```

---

## Files To Inspect First

Start with these files and locate the exact entry flow:

```text
src/services/paper_training_sampler.py
src/services/trade_executor.py
src/services/paper_trade_executor.py
tests/test_paper_mode.py
scripts/p11ag_quality_audit.sh
scripts/p11as_sampler_state_check.sh
```

Only edit files required for the surgical fix and tests.

---

## Current Broken Pattern

In or near `_training_quality_gate()`:

```python
_entry_times_minute.append(now)
_entry_times_hour.append(now)
return allow_result
```

This is wrong because it happens before downstream entry creation succeeds.

If downstream entry creation fails, the rate-cap slot remains consumed forever until the time window expires, even though no `PAPER_TRAIN_ENTRY` exists.

---

## Required Correct Pattern

Rate-cap timestamp append must happen only after the actual paper training entry is successfully created.

Target behavior:

```python
result = open_or_create_paper_training_entry(...)

if result_is_successful_entry(result):
    _entry_times_minute.append(now)
    _entry_times_hour.append(now)
```

The exact function may be named differently. Find the real place where `[PAPER_TRAIN_ENTRY]` is emitted or where the open paper position is persisted successfully. Commit rate-cap timestamps there, after success.

---

## Implementation Requirements

### 1. Remove premature rate-cap commit

In `_training_quality_gate()`:

- Keep rate-cap checks.
- Keep return of allow/block status.
- Do not append to `_entry_times_minute` or `_entry_times_hour` there.
- Preserve existing `flow_id` propagation from P1.1AQ/P1.1AR/P1.1AS.
- If the gate currently returns `now`, `flow_id`, `open_symbol`, `open_bucket`, etc., preserve them.

Expected concept:

```python
# gate only checks
if rate_cap_exceeded:
    return blocked_result

return allowed_result_with_pending_rate_cap_metadata
```

### 2. Commit only after successful entry

In the actual downstream function that creates/persists the paper training entry:

- After entry creation succeeds.
- After the trade id / position is known.
- After the path that emits `[PAPER_TRAIN_ENTRY]` or equivalent confirmed-open log.
- Commit both minute and hour timestamps.

Expected concept:

```python
if opened_successfully and training_bucket == "C_WEAK_EV_TRAIN":
    commit_training_sampler_rate_slot(now=gate_result.now, flow_id=gate_result.flow_id)
```

Use the existing `now` from the gate if available, or the entry creation time if that is the existing convention. Be consistent with current rate-cap logic.

### 3. Rollback / no-commit on failure

If entry creation fails downstream:

- Do not commit rate-cap timestamp.
- Do not consume a rate slot.
- Do not fake success.
- Do not create a placeholder entry.

If the current code appends before a later operation that can still fail, move the append after the last operation required for a valid `PAPER_TRAIN_ENTRY`.

### 4. Preserve paper-only scope

This fix must apply only to paper training sampler accounting.

Do not change:

```text
live mode
real mode
EV calculation
RDE decisions
score thresholds
TP/SL geometry
cost-edge bypass logic
negative-EV probe logic
attribution logic
learning update semantics
```

### 5. Preserve existing diagnostics

Keep these logs working if already present:

```text
[COST_EDGE_BYPASS_FLOW]
[COST_EDGE_BYPASS_ACCEPTED]
[PAPER_ENTRY_ATTEMPT]
[PAPER_SAMPLER_RATE_CAP_STATE]
[PAPER_TRAIN_ENTRY]
[PAPER_TRAIN_QUALITY_ENTRY]
[PAPER_TRAIN_QUALITY_EXIT]
[LM_STATE_AFTER_UPDATE]
```

Do not add new broad diagnostic systems.

A small debug log is allowed only if absolutely necessary, but prefer not to add new production log types.

---

## Tests Required

Add focused regression tests only.

### Test 1 — Gate does not consume rate slot

Arrange a candidate that passes `_training_quality_gate()`.

Assert:

```text
allow == True
len(_entry_times_minute) unchanged
len(_entry_times_hour) unchanged
```

### Test 2 — Successful entry consumes exactly one slot

Simulate or call the successful paper training entry creation path.

Assert:

```text
PAPER_TRAIN_ENTRY path succeeds
_entry_times_minute increments by 1
_entry_times_hour increments by 1
```

### Test 3 — Failed entry consumes zero slots

Simulate downstream entry creation failure after the gate allowed.

Assert:

```text
no PAPER_TRAIN_ENTRY
_entry_times_minute unchanged
_entry_times_hour unchanged
```

### Test 4 — Rate-cap tracks real entries

Create N successful entries up to limit.

Assert:

```text
recent_entries == successful_entries
phantom failed attempts do not count
next candidate blocks only after real successes hit the limit
```

### Test 5 — flow_id preserved

Ensure the same `flow_id` survives through:

```text
gate allow
bypass accepted
paper entry attempt
successful entry path
```

### Test 6 — live/real unaffected

Assert that live/real modes do not route or commit paper sampler rate slots from this path.

---

## Validation Commands

Run locally before commit:

```bash
python -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh
bash -n scripts/p11as_sampler_state_check.sh
```

If there are project-wide tests available and runtime is acceptable:

```bash
python -m pytest -q
```

---

## Commit Message

Use:

```text
P1.1AT: commit paper sampler rate slots only after successful entry
```

---

## Production Validation

After deploy:

```bash
cd /opt/cryptomaster
git rev-parse --short HEAD
systemctl restart cryptomaster
sleep 90
bash scripts/p11ag_quality_audit.sh --since "45 min ago"
bash scripts/p11as_sampler_state_check.sh --since "45 min ago"
```

PASS condition:

```text
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
PAPER_SAMPLER_RATE_CAP_STATE recent_entries reflects real successful entries
open_total / closed_training no longer contradict recent_entries
```

FAIL condition:

```text
PAPER_TRAIN_ENTRY_REAL = 0
recent_entries = 3
rate_limit = 3
open_total = 0
closed_training = 0
```

If fail persists, stop. Inspect the rate-cap accounting function directly. Do not create another broad diagnostics patch.

---

## P1.1AN Still Locked

Do not implement P1.1AN until production has:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
one attribution case > 50%
```

Until then:

```text
TUNE_ALLOWED = NO
```

---

## Final Instruction

Implement P1.1AT only.

Keep the patch small.

No extra diagnostics.

No tuning.

No live/real changes.

Fix the reservation accounting bug and stop.
