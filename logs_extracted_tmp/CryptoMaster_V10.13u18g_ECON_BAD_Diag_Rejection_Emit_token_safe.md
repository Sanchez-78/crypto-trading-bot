# CryptoMaster V10.13u+18g — ECON BAD Diagnostics Must Emit From Rejection Path

## Goal
Fix live issue: `[ECON_BAD_DIAG_HOOK_ACTIVE]` appears, `ECON_BAD_ENTRY` rejections continue, but no `[ECON_BAD_DIAG_HEARTBEAT]` / `[ECON_BAD_NEAR_MISS_SUMMARY]` appears after 10+ minutes.

## Current Evidence
- Runtime is correct: `RUNTIME_VERSION commit=9d0c0b5`.
- Startup hook is wired: `[ECON_BAD_DIAG_HOOK_ACTIVE]`.
- RDE is active: `decision=REJECT_ECON_BAD_ENTRY weak_ev (...)`.
- Missing: heartbeat/summary.
- Conclusion: diagnostics counters/rejections happen, but periodic emitter is not reached or is gated in the real runtime path. Do not keep patching `v5_main.py`; production is `start.py -> bot2/main.py`.

## Required Fix
Add a rejection-triggered diagnostic emitter inside `src/services/realtime_decision_engine.py`, so diagnostics are emitted from the same path that updates ECON BAD counters. This must not rely on `bot2/main.py` periodic loop.

## Hard Constraints
- Do NOT change trading decisions, EV gates, thresholds, recovery probes, close-lock logic, PF formula, Firebase reads/writes.
- Observability only.
- Exception-safe: diagnostics must never raise into trading path.
- WARNING-level logs for production visibility.
- Throttled: no spam.

## Implementation

### 1) Add module state
In `src/services/realtime_decision_engine.py` near existing ECON BAD diag globals:

```python
_ECON_BAD_DIAG_REJECT_EMIT_THROTTLE_S = 60.0
_econ_bad_diag_last_reject_emit_ts = 0.0
```

### 2) Add helper
Add below `maybe_emit_econ_bad_diag_heartbeat()` or near existing diagnostic helpers:

```python
def _maybe_emit_econ_bad_diag_from_reject(source: str = "rde_reject") -> None:
    """Emit ECON BAD diagnostics from rejection/update path.

    Purpose: production-safe fallback when periodic loop hook is not reached.
    Observability only. Never changes decision logic. Never raises.
    """
    global _econ_bad_diag_last_reject_emit_ts
    try:
        now = time.time()
        if _econ_bad_diag_last_reject_emit_ts and (
            now - _econ_bad_diag_last_reject_emit_ts
        ) < _ECON_BAD_DIAG_REJECT_EMIT_THROTTLE_S:
            return

        snap = get_econ_bad_diagnostics_snapshot()
        total = int(snap.get("total_econ_bad_blocks") or 0)
        if total <= 0:
            return

        # Re-use canonical heartbeat logger; force=True bypasses its 10m throttle,
        # but this helper has its own 60s throttle.
        maybe_emit_econ_bad_diag_heartbeat(force=True, source=source)
        _econ_bad_diag_last_reject_emit_ts = now
    except Exception as exc:
        try:
            log.warning("[ECON_BAD_DIAG_REJECT_EMIT_ERROR] err=%s", str(exc)[:160])
        except Exception:
            pass
```

### 3) Call helper after every diagnostic counter update
Wherever V10.13u+18/18b calls `_update_econ_bad_near_miss(...)` or increments negative EV diagnostic counters, add immediately after the update and before return:

```python
_maybe_emit_econ_bad_diag_from_reject(source="rde_reject")
```

Minimum call sites:
- `REJECT_ECON_BAD_ENTRY` weak/unsafe path after `_update_econ_bad_near_miss(...)`
- `REJECT_ECON_BAD_FORCED` path after forced diagnostic update
- `REJECT_NEGATIVE_EV` path after negative EV diagnostic counter update

Do not call this before counters are updated.

### 4) Keep existing hooks
Do not remove:
- `emit_econ_bad_diag_hook_marker()`
- `maybe_emit_econ_bad_diag_heartbeat()` in `bot2/main.py`
- live_path/v5 hooks

18g is a fallback/guarantee path, not a replacement.

## Expected Logs
Within 60 seconds after the first ECON BAD rejection:

```text
[ECON_BAD_DIAG_HEARTBEAT] source=rde_reject pf=0.74 econ_status=BAD pf_source=lm_economic_health pf_fallback=false total=...
[ECON_BAD_NEAR_MISS_SUMMARY] pf=0.74 econ_status=BAD pf_source=lm_economic_health pf_fallback=false total=...
```

If PF resolver fails, this is acceptable but must be explicit:

```text
pf=1.000 econ_status=UNKNOWN pf_source=fallback pf_fallback=true pf_error=...
```

## Tests
Add tests to `tests/test_v10_13u_patches.py`:

```python
def test_v10_13u18g_reject_path_emits_first_summary(monkeypatch, caplog):
    # reset diag state
    # mock lm_economic_health -> {"status":"BAD","profit_factor":0.74}
    # update near miss once
    # call _maybe_emit_econ_bad_diag_from_reject("test")
    # assert caplog contains ECON_BAD_DIAG_HEARTBEAT and source=test

def test_v10_13u18g_reject_path_throttles(monkeypatch, caplog):
    # call twice within 60s
    # assert only one heartbeat

def test_v10_13u18g_reject_path_no_emit_without_counters(caplog):
    # no counters
    # call helper
    # assert no heartbeat

def test_v10_13u18g_reject_path_exception_safe(monkeypatch):
    # make snapshot/heartbeat raise
    # assert helper does not raise

def test_v10_13u18g_no_decision_change():
    # same style as prior no-decision-change tests
    # helper returns None and does not mutate decision fields
```

## Validation Commands
On server:

```bash
cd /opt/cryptomaster
source venv/bin/activate

python -m py_compile src/services/realtime_decision_engine.py bot2/main.py
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u18g or v10_13u18" -v
git diff --check
git status --short
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+18g: emit ECON BAD diagnostics from rejection path"
git push origin main
```

Deploy/restart, then validate:

```bash
sudo systemctl restart cryptomaster
sleep 90
sudo journalctl -u cryptomaster --since "2 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_DIAG_HOOK_ACTIVE|ECON_BAD_DIAG_HEARTBEAT|ECON_BAD_NEAR_MISS_SUMMARY|ECON_BAD_DIAG_REJECT_EMIT_ERROR|Traceback"
```

## Success Criteria
- `RUNTIME_VERSION commit=<18g commit>` visible.
- `[ECON_BAD_DIAG_HOOK_ACTIVE]` visible.
- After first ECON BAD rejection, heartbeat appears within 60s with `source=rde_reject`.
- PF fields visible: `pf=... econ_status=... pf_source=... pf_fallback=...`.
- No Traceback.
- No change in TAKE/REJECT decisions except logs.
