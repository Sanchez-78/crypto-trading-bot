# CryptoMaster — Critical Decision Document

## PATCH FREEZE + SURGICAL FIX GATE

**Status:** Final pre-P1.1AN checkpoint  
**Current phase:** P1.1AS production validation → possible P1.1AT surgical fix only  
**Rule:** Stop diagnostic expansion. Fix only the proven reservation bug.

---

## 1. Problem Proven by P1.1AS Audit

P1.1AS audit proves that the sampler rate-cap is counting/reserving something that never becomes a real paper-training entry.

```text
sampler_rate_cap drops:        8
PAPER_SAMPLER_RATE_CAP_STATE:  8
recent_entries:                3
rate_limit:                    3
```

But at the same time:

```text
PAPER_TRAIN_ENTRY_REAL:        0
open_total:                    0
closed_training:               0
```

This is the decisive contradiction.

The rate-cap is active and internally consistent, but it is being fed before a final entry exists.

---

## 2. Root Cause

Likely location:

```text
_training_quality_gate() lines ~588-589
```

Problematic behavior:

```python
_entry_times_minute.append(now)
_entry_times_hour.append(now)
```

These timestamps are appended after sampler gates pass, but before downstream entry creation completes.

If `PAPER_TRAIN_ENTRY` is not created, the rate-cap slot is still consumed and never released.

Result:

```text
candidate → accepted/attempted → no entry
rate slot consumed
sampler_rate_cap blocks future candidates
no new training trades
P1.1AN remains impossible
```

---

## 3. Decision: Patch Freeze

No more broad diagnostics. No more patch expansion before sample flow is restored.

| Forbidden | Reason |
|---|---|
| ❌ P1.1AT diagnostics expansion | Enough signal. Stop diagnosing. |
| ❌ Economic tuning / P1.1AN | `closed_training_trades = 0`, so tuning is invalid. |
| ❌ Attribution features | Not the root cause. |
| ❌ New dashboards | Signal is sufficient. |
| ❌ Strategy changes | Not supported by sample data. |
| ❌ TP/SL geometry changes | P1.1AN gate is still blocked. |
| ❌ Live/real behavior changes | This is paper-train recovery only. |

Only allowed next patch:

```text
P1.1AT — Paper Sampler Rate-Cap Reservation Fix
```

---

## 4. P1.1AT Minimal Scope

### Goal

Commit rate-cap timestamps only after a real paper-training entry exists.

### Required fix

Move rate-cap timestamp append:

```python
_entry_times_minute.append(now)
_entry_times_hour.append(now)
```

From:

```text
_training_quality_gate()
```

To a point after successful entry creation, such as:

```text
maybe_open_training_sample()
```

or:

```text
open_paper_position()
```

Only commit after:

```text
[PAPER_TRAIN_ENTRY]
```

or after the open-position object has been successfully created and persisted in memory/state.

### Required rollback

If downstream entry creation fails after acceptance or attempt:

```text
do not consume a rate-cap slot
```

If a timestamp was already appended, remove it.

### Preserve

Keep all existing P1.1AQ/P1.1AR/P1.1AS correlation:

```text
flow_id
COST_EDGE_BYPASS_FLOW
COST_EDGE_BYPASS_ACCEPTED
PAPER_ENTRY_ATTEMPT
PAPER_SAMPLER_RATE_CAP_STATE
```

Do not add broad new diagnostics.

---

## 5. Acceptance Criteria

After P1.1AT deploy, run:

```bash
bash scripts/p11ag_quality_audit.sh --since "45 min ago"
bash scripts/p11as_sampler_state_check.sh --since "45 min ago"
```

### PASS

```text
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
PAPER_SAMPLER_RATE_CAP_STATE recent_entries == actual committed entries in window
```

or at least:

```text
recent_entries <= actual successful paper-training entries/reservations that reached final entry
```

### FAIL

```text
PAPER_TRAIN_ENTRY_REAL = 0
recent_entries = 3
rate_limit = 3
open_total = 0
closed_training = 0
```

If FAIL persists, stop and inspect the exact rate-cap accounting function. Do not add another diagnostics patch.

---

## 6. P1.1AN Gate Remains Blocked

P1.1AN economic tuning is not allowed until:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
one attribution case is dominant
```

Current state does not satisfy the first requirement because sample flow is blocked.

```text
TUNE_ALLOWED: NO
reason: no valid closed training sample flow
```

---

## 7. Next Operational Steps

1. Confirm production audit shows the reservation bug.
2. Implement only P1.1AT.
3. Run tests and audit scripts.
4. Deploy.
5. Let bot collect stable paper-training samples.
6. Wait for at least 10 closed training trades.
7. Only then resume P1.1AN economic calibration.

---

## 8. Claude/Codex Prompt — P1.1AT Only

```text
You are working in CryptoMaster.

Hard rule:
Do not add broad diagnostics. Do not tune strategy. Do not change EV, TP/SL, attribution, dashboards, live, or real execution.

Production P1.1AS audit proves a paper-training sampler reservation bug:
- sampler_rate_cap drops exist
- PAPER_SAMPLER_RATE_CAP_STATE logs exist
- recent_entries=3 and rate_limit=3
- PAPER_TRAIN_ENTRY_REAL=0
- open_total=0
- closed_training=0

Root cause:
_training_quality_gate() appends _entry_times_minute/_entry_times_hour before final PAPER_TRAIN_ENTRY creation. If downstream entry creation fails, the rate slot is consumed but no entry exists.

Task:
Implement P1.1AT — Paper Sampler Rate-Cap Reservation Fix.

Required changes:
1. Move _entry_times_minute.append(now) and _entry_times_hour.append(now) out of _training_quality_gate().
2. Commit rate-cap timestamps only after successful PAPER_TRAIN_ENTRY/open-position creation.
3. If downstream creation fails after acceptance/attempt, do not consume a rate slot.
4. Preserve existing flow_id propagation.
5. Keep all behavior paper_train/training-sampler scoped.
6. Live/real execution must remain unchanged.
7. Add regression tests:
   - candidate drop does not increment rate-cap timestamps
   - accepted but aborted attempt does not increment rate-cap timestamps
   - successful PAPER_TRAIN_ENTRY increments rate-cap exactly once
   - flow_id is preserved
   - live/real modes unchanged
8. Run:
   python -m pytest tests/test_paper_mode.py -q
   bash -n scripts/p11ag_quality_audit.sh
   bash -n scripts/p11as_sampler_state_check.sh

Output:
- changed files
- test results
- exact statement confirming rate-cap timestamps commit only after successful PAPER_TRAIN_ENTRY
```

---

## Final Rule

After P1.1AT, stop patching and let production collect samples.

No P1.1AN until at least 10 closed paper-training trades exist.
