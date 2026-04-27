# CryptoMaster V10.13u+18e — Runtime Entrypoint ECON BAD Diagnostics Hook

## Diagnosis
Production systemd runs:
`ExecStart=/usr/bin/python3 start.py`

Current diagnostics are only wired in:
- `src/core/v5_main.py`
- `src/core/live_path_heartbeat.py`

Live logs show `[RUNTIME_VERSION] commit=2597ef1`, but no:
- `[ECON_BAD_DIAG_HOOK_ACTIVE]`
- `[ECON_BAD_DIAG_HEARTBEAT]`
- `[ECON_BAD_NEAR_MISS_SUMMARY]`

Therefore V10.13u+18d code is deployed, but not connected to the actual production runtime path. Fix only wiring/observability.

## Goal
Wire ECON BAD diagnostics into the real runtime entrypoint used by systemd: `start.py`.

## Hard Constraints
- Do not change trading behavior.
- Do not change EV gating, score thresholds, recovery probe logic, exit logic, sizing, PF formula, Firebase reads/writes, or close-lock logic.
- Diagnostics must be exception-safe and non-fatal.
- Use WARNING level so journalctl grep sees it.
- Do not import heavy modules inside high-frequency paths unless already safe.
- Keep token/code diff small.

## Implementation Plan

### 1. Locate real startup and loop in `start.py`
Inspect `start.py` and find:
- where runtime startup/logging happens
- where `format_runtime_version()` or equivalent `[RUNTIME_VERSION]` call is emitted
- main async/sync loop or periodic dashboard/heartbeat tick

### 2. Add startup marker after runtime version log
Immediately after `[RUNTIME_VERSION]` is logged in `start.py`, add:

```python
try:
    from src.services.realtime_decision_engine import emit_econ_bad_diag_hook_marker
    emit_econ_bad_diag_hook_marker()
except Exception as e:
    try:
        import logging
        logging.getLogger(__name__).warning(
            "[ECON_BAD_DIAG_HOOK_ERROR] source=start.py phase=startup error=%r", e
        )
    except Exception:
        pass
```

If `emit_econ_bad_diag_hook_marker()` does not accept a `source` argument, do not change its signature unless needed. If changing signature, preserve backward compatibility:
`def emit_econ_bad_diag_hook_marker(source: str = "realtime_decision_engine") -> None:`

### 3. Add periodic heartbeat in the actual active loop
In the real repeated loop in `start.py`, add a throttled call every ~30 seconds. Use a local timestamp to avoid calling the helper every tick.

Example:

```python
_last_econ_bad_diag_heartbeat_ts = 0.0
_ECON_BAD_RUNTIME_HEARTBEAT_EVERY_S = 30.0
```

Inside the loop:

```python
try:
    import time
    now = time.time()
    if now - _last_econ_bad_diag_heartbeat_ts >= _ECON_BAD_RUNTIME_HEARTBEAT_EVERY_S:
        _last_econ_bad_diag_heartbeat_ts = now
        from src.services.realtime_decision_engine import maybe_emit_econ_bad_diag_heartbeat
        maybe_emit_econ_bad_diag_heartbeat(source="start.py", force=False)
except Exception as e:
    try:
        import logging
        logging.getLogger(__name__).warning(
            "[ECON_BAD_DIAG_HOOK_ERROR] source=start.py phase=heartbeat error=%r", e
        )
    except Exception:
        pass
```

If `start.py` already has a periodic heartbeat/dashboard function, place this there instead of the tight price loop.

### 4. Ensure first heartbeat is visible
Confirm `maybe_emit_econ_bad_diag_heartbeat()` bypasses throttle on first call:
- first heartbeat must emit within 30–90 seconds after restart when ECON BAD is active
- keep WARNING level

### 5. Preserve existing heartbeat paths
Do not remove hooks from:
- `src/core/v5_main.py`
- `src/core/live_path_heartbeat.py`

They are harmless but not production-active.

## Validation Commands

Run on Hetzner:

```bash
cd /opt/cryptomaster
source venv/bin/activate

python -m py_compile start.py src/services/realtime_decision_engine.py src/core/live_path_heartbeat.py src/core/v5_main.py
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u18" -v
git diff --check
git status --short
```

Ignore unrelated:
- `?? logs/`
- `?? venv/`

Do not commit `logs/` or `venv/`.

## Commit

```bash
git add start.py src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+18e: wire ECON BAD diagnostics into production start.py"
git push origin main
```

Adjust `git add` to include only files actually modified.

## Deployment Validation

Restart service:

```bash
sudo systemctl restart cryptomaster
sleep 90
sudo journalctl -u cryptomaster --since "3 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_DIAG_HOOK_ACTIVE|ECON_BAD_DIAG_HEARTBEAT|ECON_BAD_NEAR_MISS_SUMMARY|ECON_BAD_DIAG_HOOK_ERROR|Traceback"
```

Expected:
```text
[RUNTIME_VERSION] ... commit=<new_commit>
[ECON_BAD_DIAG_HOOK_ACTIVE] ...
[ECON_BAD_DIAG_HEARTBEAT] source=start.py ...
```

If only `[RUNTIME_VERSION]` appears again, `start.py` has another nested runtime path; trace and hook the exact function that runs after service start.

## Acceptance Criteria
- `[RUNTIME_VERSION]` shows new commit.
- `[ECON_BAD_DIAG_HOOK_ACTIVE]` appears once after startup.
- `[ECON_BAD_DIAG_HEARTBEAT] source=start.py` appears within 90s when ECON BAD is active.
- No `Traceback`.
- No trading behavior change.
- No new Firebase writes.
