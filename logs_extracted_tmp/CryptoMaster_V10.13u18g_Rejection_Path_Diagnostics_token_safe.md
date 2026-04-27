# CryptoMaster V10.13u+18g — ECON BAD Diagnostics From Rejection Path

## Goal
Fix live state where:
- `[RUNTIME_VERSION] commit=9d0c0b5` is visible.
- `[ECON_BAD_DIAG_HOOK_ACTIVE]` is visible.
- `REJECT_ECON_BAD_ENTRY` / `REJECT_NEGATIVE_EV` continue.
- But `[ECON_BAD_DIAG_HEARTBEAT]` / `[ECON_BAD_NEAR_MISS_SUMMARY]` do not appear reliably.

Implement a production-safe fallback: emit ECON BAD diagnostics directly from the rejection path after diagnostic counters are updated.

## Scope
Observability only.

Do not change:
- TAKE / REJECT decision semantics
- EV-only enforcement
- ECON BAD thresholds
- recovery probe thresholds
- close-lock / exit logic
- PF formula
- Firebase reads/writes
- sizing / TP / SL / PARTIAL_TP

## Files
- `src/services/realtime_decision_engine.py`
- `tests/test_v10_13u_patches.py`

---

## 1. Add module state

In `src/services/realtime_decision_engine.py`, near existing ECON BAD diagnostic globals:

```python
_ECON_BAD_DIAG_REJECT_EMIT_THROTTLE_S = 60.0
_econ_bad_diag_last_reject_emit_ts = 0.0
```

---

## 2. Add rejection-path emitter helper

Place after `maybe_emit_econ_bad_diag_heartbeat()`:

```python
def _maybe_emit_econ_bad_diag_from_reject(source: str = "rde_reject") -> None:
    """Emit ECON BAD diagnostics from rejection/update path.

    Production-safe fallback when periodic loop heartbeat is not reached.
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

        # Force bypasses the 10-minute heartbeat throttle.
        # This helper has its own 60-second throttle.
        maybe_emit_econ_bad_diag_heartbeat(force=True, source=source)
        _econ_bad_diag_last_reject_emit_ts = now
    except Exception as exc:
        try:
            log.warning("[ECON_BAD_DIAG_REJECT_EMIT_ERROR] err=%s", str(exc)[:160])
        except Exception:
            pass
```

---

## 3. Add calls after diagnostic updates

Call this helper immediately after diagnostic counters are updated, before returning rejection.

### A. `REJECT_ECON_BAD_ENTRY`

Find every `_update_econ_bad_near_miss(...)` used for ECON BAD entry rejection and add:

```python
_maybe_emit_econ_bad_diag_from_reject(source="rde_reject")
```

Order must be:

```python
_update_econ_bad_near_miss(...)
_maybe_emit_econ_bad_diag_from_reject(source="rde_reject")
return ...
```

### B. `REJECT_ECON_BAD_FORCED`

After forced diagnostic counter/update:

```python
_maybe_emit_econ_bad_diag_from_reject(source="rde_reject")
```

### C. `REJECT_NEGATIVE_EV`

After negative-EV diagnostic counter/update:

```python
_maybe_emit_econ_bad_diag_from_reject(source="rde_reject")
```

Do not call before counters are updated.

---

## 4. Tests

Append to `tests/test_v10_13u_patches.py`.

Import required helpers inside each test or at the test section top, matching project style.

### Test 1 — first reject emits

```python
def test_v10_13u18g_reject_path_emits_first_summary(monkeypatch, caplog):
    """First diagnostic emission from rejection path triggers heartbeat."""
    from src.services import realtime_decision_engine as rde

    rde._reset_econ_bad_diagnostics()
    monkeypatch.setattr(rde, "_econ_bad_diag_last_reject_emit_ts", 0.0)
    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"profit_factor": 0.74, "status": "BAD"},
    )

    rde._update_econ_bad_near_miss(
        symbol="BTCUSDT",
        reason="weak_ev",
        ev=0.037,
        score=0.183,
        p=0.523,
        coh=0.741,
        af=0.750,
    )
    rde._maybe_emit_econ_bad_diag_from_reject("test")

    assert "[ECON_BAD_DIAG_HEARTBEAT]" in caplog.text
    assert "source=test" in caplog.text
```

### Test 2 — throttles

```python
def test_v10_13u18g_reject_path_throttles(monkeypatch, caplog):
    """Reject-path emission throttles at 60 seconds."""
    from src.services import realtime_decision_engine as rde

    rde._reset_econ_bad_diagnostics()
    monkeypatch.setattr(rde, "_econ_bad_diag_last_reject_emit_ts", 0.0)
    monkeypatch.setattr(
        "src.services.learning_monitor.lm_economic_health",
        lambda: {"profit_factor": 0.74, "status": "BAD"},
    )

    rde._update_econ_bad_near_miss(
        symbol="BTCUSDT",
        reason="weak_ev",
        ev=0.037,
        score=0.183,
        p=0.523,
        coh=0.741,
        af=0.750,
    )

    rde._maybe_emit_econ_bad_diag_from_reject("test")
    first_count = caplog.text.count("[ECON_BAD_DIAG_HEARTBEAT]")

    caplog.clear()
    rde._maybe_emit_econ_bad_diag_from_reject("test")
    second_count = caplog.text.count("[ECON_BAD_DIAG_HEARTBEAT]")

    assert first_count == 1
    assert second_count == 0
```

### Test 3 — no counters, no emit

```python
def test_v10_13u18g_reject_path_no_emit_without_counters(caplog):
    """No emission if no diagnostic counters exist."""
    from src.services import realtime_decision_engine as rde

    rde._reset_econ_bad_diagnostics()
    rde._maybe_emit_econ_bad_diag_from_reject("test")

    assert "[ECON_BAD_DIAG_HEARTBEAT]" not in caplog.text
```

### Test 4 — exception-safe

```python
def test_v10_13u18g_reject_path_exception_safe(monkeypatch):
    """Helper never raises, even if snapshot fails."""
    from src.services import realtime_decision_engine as rde

    def boom():
        raise ValueError("mock error")

    monkeypatch.setattr(rde, "get_econ_bad_diagnostics_snapshot", boom)

    rde._maybe_emit_econ_bad_diag_from_reject("test")
```

### Test 5 — no decision change

```python
def test_v10_13u18g_no_decision_change():
    """Reject-path emitter is observability-only."""
    from src.services import realtime_decision_engine as rde

    result = rde._maybe_emit_econ_bad_diag_from_reject("test")
    assert result is None
```

If `_update_econ_bad_near_miss()` has a different signature in the live code, adapt the test call to the actual function signature. Do not change production behavior just to satisfy the test.

---

## 5. Validation commands

Run on server:

```bash
cd /opt/cryptomaster
source venv/bin/activate

python -m py_compile src/services/realtime_decision_engine.py
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u18g or v10_13u18" -v
git diff --check
git status --short
```

Ignore unrelated untracked runtime folders:
- `logs/`
- `venv/`

Commit only intended source/test files:

```bash
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+18g: emit ECON BAD diagnostics from rejection path"
git push origin main
```

---

## 6. Deploy validation

```bash
sudo systemctl restart cryptomaster
sleep 90

sudo journalctl -u cryptomaster --since "2 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_DIAG_HOOK_ACTIVE|ECON_BAD_DIAG_HEARTBEAT|ECON_BAD_NEAR_MISS_SUMMARY|ECON_BAD_DIAG_REJECT_EMIT_ERROR|Traceback"
```

Expected after first ECON BAD rejection:

```text
[RUNTIME_VERSION] ... commit=<18g_commit>
[ECON_BAD_DIAG_HOOK_ACTIVE] ...
[ECON_BAD_DIAG_HEARTBEAT] source=rde_reject pf=0.74 econ_status=BAD pf_source=lm_economic_health pf_fallback=false total=...
[ECON_BAD_NEAR_MISS_SUMMARY] ... pf=0.74 econ_status=BAD pf_source=lm_economic_health pf_fallback=false ...
```

Acceptable fallback case:

```text
pf=1.000 econ_status=UNKNOWN pf_source=fallback pf_fallback=true pf_error=...
```

Fallback must be explicit. Silent `pf=1.000` is not acceptable.

---

## Success Criteria
- Heartbeat appears from `source=rde_reject` within 60 seconds of ECON BAD rejection.
- PF diagnostic fields are visible.
- No Traceback.
- No decision behavior changes.
- No new Firebase writes.
