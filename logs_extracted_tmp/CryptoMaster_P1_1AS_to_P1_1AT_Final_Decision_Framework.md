# CryptoMaster — P1.1AS → P1.1AT Final Decision Framework

## Status

```text
P1.1AS: COMPLETE / deployed / audit-confirmed
HEAD: d7d7850
P1.1AT: ONLY allowed next patch
P1.1AN: BLOCKED until >=10 closed training trades
Patch expansion: FROZEN
```

---

## 1. Confirmed Production Finding

P1.1AS audit confirmed the reservation bug.

Observed contradiction:

```text
sampler_rate_cap drops:        present
PAPER_SAMPLER_RATE_CAP_STATE:  present
recent_entries:                3
rate_limit:                    3

PAPER_TRAIN_ENTRY_REAL:        0
open_total:                    0
closed_training:               0
```

This proves that the rate-cap is counting/reserving entries before real paper entries exist.

---

## 2. Proven Flow Block

```text
candidate flow
  -> accepted
  -> attempt
  -> _entry_times_minute.append(now)   # too early
  -> _entry_times_hour.append(now)     # rate slot consumed
  -> downstream entry creation fails
  -> rate slot never released
  -> future candidates blocked by sampler_rate_cap
  -> no PAPER_TRAIN_ENTRY_REAL
  -> no closed_training_trades
  -> P1.1AN impossible
```

---

## 3. Root Cause

Current behavior:

```python
def _training_quality_gate(...):
    ...
    # all gates pass
    _entry_times_minute.append(now)
    _entry_times_hour.append(now)
    return _allow(...)
```

The timestamp reservation happens before final paper entry creation.

This makes the sampler think entries were created even when no `PAPER_TRAIN_ENTRY` exists.

---

## 4. Patch Freeze Rule

No new patch branches are allowed before the flow block is fixed.

| Forbidden | Reason |
|---|---|
| P1.1AT diagnostics expansion | Signal is sufficient. |
| P1.1AN economic tuning | Need >=10 closed trades first. |
| Attribution features | Blocked by zero/insufficient sample flow. |
| Dashboards | Current visibility is enough. |
| Strategy changes | No valid sample basis. |
| TP/SL changes | P1.1AN gate still blocked. |
| Live/real changes | This is paper-train recovery only. |

Only allowed patch:

```text
P1.1AT — Paper Sampler Rate-Cap Reservation Fix
```

---

## 5. P1.1AT Surgical Scope

### Required change

Move rate-cap timestamp commit from `_training_quality_gate()` to after successful paper entry creation.

Correct behavior:

```python
def open_paper_position(...):
    result = create_entry(...)

    if result["status"] == "opened":
        _entry_times_minute.append(now)
        _entry_times_hour.append(now)

    return result
```

or equivalent inside the actual function that confirms final `PAPER_TRAIN_ENTRY`.

### Required constraints

- Commit rate-cap timestamp only after actual entry exists.
- If downstream entry creation fails, do not consume a rate slot.
- Preserve existing `flow_id` tracing from P1.1AQ/P1.1AR/P1.1AS.
- Keep scope paper-train / training-sampler only.
- Do not change EV, TP/SL, strategy, attribution, live, or real execution.

---

## 6. P1.1AT Acceptance Criteria

After deploy:

```bash
bash scripts/p11ag_quality_audit.sh --since "45 min ago"
bash scripts/p11as_sampler_state_check.sh --since "45 min ago"
```

PASS:

```text
PAPER_TRAIN_ENTRY_REAL > 0
PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL
rate-cap recent_entries tracks actual successful entries/reservations
```

FAIL:

```text
PAPER_TRAIN_ENTRY_REAL = 0
recent_entries = 3
rate_limit = 3
open_total = 0
closed_training = 0
```

If FAIL persists, stop and inspect rate-cap accounting directly. Do not create another broad diagnostics patch.

---

## 7. P1.1AN Gate

P1.1AN remains locked until:

```text
closed_training_trades >= 10
quality_entry_mismatch = 0
quality_exit_missing = 0
lm_update_mismatch = 0
one attribution case clearly dominates
```

Until then:

```text
TUNE_ALLOWED = NO
```

---

## 8. Final Next Step

Implement only P1.1AT.

No additional diagnostics, no economic tuning, no feature expansion.
