# CryptoMaster — P1.1AT Test Isolation Fix Prompt

## Goal

Fix failing `tests/test_paper_mode.py` after P1.1AT without changing trading behavior.

This is **test-harness cleanup only**. Do not add new diagnostics, dashboards, strategy changes, TP/SL changes, EV changes, live/real changes, or production tuning.

## Current Situation

Production validation after P1.1AT is good:

- `PAPER_TRAIN_ENTRY_REAL > 0`
- `PAPER_TRAIN_QUALITY_ENTRY == PAPER_TRAIN_ENTRY_REAL`
- `PAPER_TRAIN_QUALITY_EXIT` present
- `LM_STATE_AFTER_UPDATE` present
- rate-cap no longer blocks phantom entries
- closed training trades are accumulating

But the local pytest suite fails because tests share dirty module-level sampler state.

## Failing Tests

```text
FAILED TestP1AT_RateCapReservationFix.test_gate_does_not_consume_rate_slot
FAILED TestP1AT_RateCapReservationFix.test_rate_cap_blocks_phantom_attempts
FAILED TestP1AT_RateCapReservationFix.test_flow_id_propagated_through_entry_path
FAILED TestP1AS_RateCapStateLogging.test_open_positions_computed_before_rate_cap_check
FAILED TestP1AS_RateCapStateLogging.test_drop_logs_include_flow_id
FAILED TestP1AE1BootstrapCostEdgeBypass.test_bootstrap_cost_edge_bypass_paper_train
```

## Root Cause

The failures are caused by test isolation problems:

1. `_entry_times_minute` and `_entry_times_hour` are not cleared before P1.1AT tests.
   - Result: `_training_quality_gate()` returns `max_entries_per_minute`.
   - This breaks tests that expect the gate to allow a candidate.

2. Duplicate-training-sample state is not cleared before bootstrap bypass tests.
   - Result: `_training_quality_gate()` returns `duplicate_training_sample`.
   - This breaks `test_bootstrap_cost_edge_bypass_paper_train`.

3. `_log_bypass_flow()` is throttled.
   - Prior tests can suppress the log.
   - This breaks `test_drop_logs_include_flow_id`.

4. `test_flow_id_propagated_through_entry_path` calls `_training_quality_gate` without importing it locally.
   - Result: `NameError`.

5. Some deny results do not include `open_symbol`, `open_bucket`, `open_total`.
   - For P1.1AS diagnostics, these fields should be safe to include in gate results whenever open-position counts are computed.
   - This is diagnostic metadata only, not behavior.

## Required Changes

### 1. Add or update a test reset helper

In `tests/test_paper_mode.py`, create a helper that clears sampler module state before tests that directly call `_training_quality_gate()`.

Example shape:

```python
def _reset_paper_sampler_test_state():
    import src.services.paper_training_sampler as pts

    for name in (
        "_entry_times_minute",
        "_entry_times_hour",
    ):
        obj = getattr(pts, name, None)
        if hasattr(obj, "clear"):
            obj.clear()

    # Clear duplicate/signature caches if present.
    for name in (
        "_recent_training_signatures",
        "_training_sample_signatures",
        "_duplicate_training_samples",
        "_candidate_signatures",
        "_duplicate_cache",
    ):
        obj = getattr(pts, name, None)
        if hasattr(obj, "clear"):
            obj.clear()

    # Clear throttles if present.
    for name in (
        "_bypass_flow_throttle",
        "_rate_cap_state_throttle",
        "_hblock_throttle",
        "_paper_explore_skip_throttle",
    ):
        obj = getattr(pts, name, None)
        if hasattr(obj, "clear"):
            obj.clear()
```

Use actual variable names from `src/services/paper_training_sampler.py`. Do not invent names without checking the module.

Call this helper at the start of all failing tests, or integrate it into the existing `clean_positions` fixture if that fixture is specifically intended to reset paper-training state.

### 2. Fix local import in `test_flow_id_propagated_through_entry_path`

Add:

```python
from src.services.paper_training_sampler import _training_quality_gate
```

inside that test, or import it together with `_gen_flow_id`.

### 3. Fix throttled log test

In `test_drop_logs_include_flow_id`, clear the bypass-flow throttle before calling `_log_bypass_flow()`.

Also use a unique symbol or unique `flow_id` to avoid collision with prior tests.

Expected assertion:

```python
assert any("stage=drop" in msg and "flow_id=" in msg for msg in log_capture)
```

### 4. Ensure `_training_quality_gate()` test payload includes open counts

In `src/services/paper_training_sampler.py`, keep behavior unchanged, but make the gate result include diagnostic fields when counts are available:

```python
open_symbol=...
open_bucket=...
open_total=...
```

This may be added to both allow and deny results. It must not change decision logic.

### 5. Preserve P1.1AT behavior

Do not reintroduce premature appends:

```python
_entry_times_minute.append(now)
_entry_times_hour.append(now)
```

must remain outside `_training_quality_gate()`.

Rate slots may be committed only after a real paper training position is successfully created and persisted.

## Validation Commands

Use Python 3 / venv on Ubuntu:

```bash
cd /opt/cryptomaster
source venv/bin/activate

python -m pytest tests/test_paper_mode.py -q
bash -n scripts/p11ag_quality_audit.sh
bash -n scripts/p11ak_core_flow_viewer.sh
bash -n scripts/p11ak_core_flow_viewer_cs.sh
git status
```

If `python` is unavailable outside venv:

```bash
python3 -m pytest tests/test_paper_mode.py -q
```

## Acceptance Criteria

- `tests/test_paper_mode.py` passes.
- Shell syntax checks pass.
- No runtime JSON, `.env*`, `venv/`, backups, or `data/paper_open_positions.json` are committed.
- No trading behavior changes.
- No live/real behavior changes.
- P1.1AT invariant remains true: gate-only phantom attempts do not consume rate-cap slots.

## Git Hygiene

Do not commit:

```text
data/paper_open_positions.json
.env*
venv/
server_local_backups/
data/archive/
FETCH_HEAD
daily_log_fix_prompt_bot/*
```

Only commit source/test/script changes required for the test isolation fix.
