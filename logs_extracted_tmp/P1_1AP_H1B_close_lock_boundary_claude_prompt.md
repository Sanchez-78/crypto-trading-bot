# Claude Code Prompt — P1.1AP-H1B Close-Lock Boundary Fix

## Goal

Fix the remaining close-lock duplicate log throttle boundary conflict in `src/services/trade_executor.py`.

This is a narrow H1B patch only. Do **not** change trading strategy, live order execution, TP/SL, paper sampler, P1.1AO probe logic, Android snapshot publishing, Firebase writes, or learning logic.

## Current state

These tests were run:

```bash
python -m pytest -q tests/test_v10_13u_patches.py::test_duplicate_close_logs_throttled
python -m pytest -q tests/test_v10_13u_patches.py::test_close_skip_duplicate_is_throttled
```

Result:

- `test_close_skip_duplicate_is_throttled` passes
- `test_duplicate_close_logs_throttled` fails

Failure:

```text
AssertionError: last_log should not update within throttle window
assert meta.get("last_log") == last_log_1
```

The failing test calls `_try_acquire_close_lock()` exactly at:

```python
now + 5.0
```

Current code updates `_CLOSING_POSITIONS[key]["last_log"]` at exactly `CLOSE_DUP_LOG_INTERVAL_S`.

## Required behavior

Use a strict boundary:

```text
elapsed == CLOSE_DUP_LOG_INTERVAL_S  -> do NOT update last_log
elapsed >  CLOSE_DUP_LOG_INTERVAL_S  -> update last_log
```

This preserves both expectations:

```text
now + 5.0s -> no last_log update
now + 6.0s -> last_log update
```

## Implementation instructions

In `src/services/trade_executor.py`, inspect `_try_acquire_close_lock()`.

Find the duplicate close / already_closing branch where `[CLOSE_SKIP_DUPLICATE]` is logged and `last_log` is updated.

Change the condition from inclusive to strict.

Expected logic shape:

```python
elapsed = now - float(meta.get("last_log", meta.get("ts", now)))

if elapsed > CLOSE_DUP_LOG_INTERVAL_S:
    logger.warning(
        "[CLOSE_SKIP_DUPLICATE] %s reason=%s key=%s status=already_closing age=%.1fs attempts=%s",
        symbol,
        reason,
        key,
        now - float(meta.get("ts", now)),
        meta.get("attempts", 0),
    )
    meta["last_log"] = now
```

Important:

- Do **not** change duplicate close protection.
- `_try_acquire_close_lock()` must still return `acquired=False` and `status="already_closing"` for duplicate attempts.
- Only change log-throttle boundary behavior.
- Do not reset or clear `_CLOSING_POSITIONS` in production code.
- Do not modify unrelated close-lock stale recovery logic.

## Required tests

Run these first:

```bash
python -m pytest -q tests/test_v10_13u_patches.py::test_duplicate_close_logs_throttled
python -m pytest -q tests/test_v10_13u_patches.py::test_close_skip_duplicate_is_throttled
```

Then run the close-lock subset:

```bash
python -m pytest -q tests/test_v10_13u_patches.py   -k "duplicate_close_logs_throttled or close_skip_duplicate_is_throttled or close_lock_cleanup_runs_before_duplicate_skip"
```

Then run the broader H1B/H2 conflict subset:

```bash
python -m pytest -q tests/test_v10_13u_patches.py   -k "canonical_rr_handles_zero_sl or canonical_rr_abs_values or lm_economic_health_uses_canonical_pf or economic_health_pf_hard_rule or economic_health_profitable_pf_good or scratch_guard_holds_negative_net_in_econ_bad or close_lock_cleanup_runs_before_duplicate_skip or duplicate_close_logs_throttled or close_skip_duplicate_is_throttled"
```

## Acceptance criteria

- `test_duplicate_close_logs_throttled` passes.
- `test_close_skip_duplicate_is_throttled` still passes.
- `close_lock_cleanup_runs_before_duplicate_skip` still passes.
- No changes to live trading logic beyond duplicate log throttle boundary.
- No runtime/local files are committed.

## Commit message

```text
P1.1AP-H1B: Fix close-lock duplicate throttle boundary
```

## Do not commit

Do not commit:

```text
data/paper_open_positions.json
.env*
venv/
server_local_backups/
data/archive/
data/research/
temporary shell output files
```
