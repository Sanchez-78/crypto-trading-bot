# CryptoMaster V10.13u+19e — ECON BAD Trace Reason Propagation Fix

## Goal

Fix misleading observability in the ECON BAD weak-EV rejection path.

Current production logs show safe rejection, but the trace reason is wrong:

```text
snapshot_probe_ready=False
snapshot_probe_block=below_probe_ev
actual_recovery_checked=False
actual_recovery_allowed=False
actual_recovery_reason=not_overridable
final_decision=REJECT_ECON_BAD_ENTRY
```

Expected:

```text
snapshot_probe_ready=False
snapshot_probe_block=below_probe_ev
actual_recovery_checked=True
actual_recovery_allowed=False
actual_recovery_reason=below_probe_ev
final_decision=REJECT_ECON_BAD_ENTRY
```

This patch is observability-only except for correctly routing the already-existing recovery/deadlock override resolver before the weak-EV return.

Do not loosen thresholds. Do not change EV gates. Do not change Firebase reads/writes. Do not change TP/SL/exit logic.

---

## Context

Production behavior after V10.13u+19d:

- Runtime commit observed: `0cc68b3`
- Bot rejects weak candidates correctly.
- Candidates are below recovery/deadlock EV floors:
  - `ev=0.0300–0.0348`
  - recovery floor ≈ `0.0380`
  - deadlock band min ≈ `0.0370`
- `snapshot_probe_ready=False`
- `snapshot_probe_block=below_probe_ev`
- `idle_s` after restart is low, so deadlock probe must not fire.

Bug:

- Trace says `actual_recovery_checked=False actual_recovery_reason=not_overridable`
- That hides the real blocker.
- It also previously caused noisy `[ECON_BAD_READY_BUT_REJECTED]` logs from stale snapshot state.

Correct behavior:

- If weak EV path reaches override resolver, `actual_recovery_checked=True`.
- If EV is below floors, reason must be `below_probe_ev`.
- `[ECON_BAD_READY_BUT_REJECTED]` may only fire when actual resolver allowed a TAKE but final decision still rejects.

---

## Files

Primary file:

```text
src/services/realtime_decision_engine.py
```

Tests:

```text
tests/test_v10_13u_patches.py
```

Do not touch unrelated modules unless import/test setup requires it.

---

## Required Implementation

### 1. Make recovery override resolver always return precise checked/reason state

Find existing helper from V10.13u+19d, likely named:

```python
_resolve_econ_bad_recovery_override_for_signal(...)
```

It must always return a dict with this shape:

```python
{
    "checked": True,
    "allowed": False,
    "reason": "below_probe_ev",
    "kind": None,
    "size_mult": None,
    "meta": {},
}
```

Use exactly these keys everywhere:

```python
checked
allowed
reason
kind
size_mult
meta
```

Rules:

- If the helper is called, `checked=True`.
- Never return `checked=False` from inside this helper except for a truly unreachable/internal-disabled path where the caller intentionally skipped calling the helper.
- For weak-EV ECON BAD candidates, the helper should be called and should return the exact blocker:
  - `negative_ev`
  - `below_probe_ev`
  - `weak_score`
  - `weak_p`
  - `weak_coh`
  - `weak_af`
  - `forbidden_tag`
  - `forced_signal`
  - `open_positions`
  - `idle_too_short`
  - `diag_blocks_too_low`
  - `probe_cooldown`
  - `probe_cap_24h`
  - `recovery_probe_allowed`
  - `deadlock_probe_allowed`
  - `econ_not_bad`
  - `disabled`
  - `exception`

For EV floor logic, use these meanings:

```python
if ev <= 0:
    reason = "negative_ev"
elif ev < ECON_BAD_DEADLOCK_MIN_EV:
    reason = "below_probe_ev"
elif ev < ECON_BAD_RECOVERY_PROBE_MIN_EV and not in_deadlock_band:
    reason = "below_probe_ev"
```

Do not loosen:

```python
ECON_BAD_ENTRY_MIN_EV = 0.045
ECON_BAD_RECOVERY_PROBE_MIN_EV = 0.038
ECON_BAD_DEADLOCK_MIN_EV = 0.0370
ECON_BAD_DEADLOCK_MAX_EV = 0.0380
```

If constants have different existing names, use current names and preserve values.

---

### 2. Add a small normalizer for override result

Add near the trace/helper section:

```python
def _normalize_econ_bad_override_result(result: object, default_reason: str = "not_overridable") -> dict:
    """Normalize recovery/deadlock override result for logging only.

    Observability helper. Never raises.
    """
    try:
        if not isinstance(result, dict):
            return {
                "checked": False,
                "allowed": False,
                "reason": default_reason,
                "kind": None,
                "size_mult": None,
                "meta": {},
            }

        reason = result.get("reason") or default_reason
        return {
            "checked": bool(result.get("checked", True)),
            "allowed": bool(result.get("allowed", False)),
            "reason": str(reason),
            "kind": result.get("kind"),
            "size_mult": result.get("size_mult"),
            "meta": result.get("meta") if isinstance(result.get("meta"), dict) else {},
        }
    except Exception:
        return {
            "checked": False,
            "allowed": False,
            "reason": "normalize_error",
            "kind": None,
            "size_mult": None,
            "meta": {},
        }
```

Important:

- This helper must not affect trading decisions.
- It is only to keep trace fields consistent.

---

### 3. Wire override resolver before every weak-EV ECON BAD return

Find all return paths similar to:

```python
return ("REJECT_ECON_BAD_ENTRY", reason, ...)
```

or:

```python
return decision object with decision="REJECT_ECON_BAD_ENTRY"
```

especially where reason contains:

```text
weak_ev
ev < 0.045
```

Before returning `REJECT_ECON_BAD_ENTRY`, call:

```python
override = _resolve_econ_bad_recovery_override_for_signal(signal, ctx)
override = _normalize_econ_bad_override_result(override, default_reason="not_overridable")
```

Then:

```python
if override["allowed"]:
    # preserve existing V10.13u+17/+19 behavior
    # set metadata only as existing code expects
    signal["_econ_bad_recovery_probe"] = True if override["kind"] == "recovery" else False
    signal["_econ_bad_deadlock_probe"] = True if override["kind"] == "deadlock" else False
    signal["_econ_bad_probe_kind"] = override["kind"]
    signal["_econ_bad_probe_size_mult"] = override["size_mult"]

    # merge optional meta
    if isinstance(override.get("meta"), dict):
        signal.update(override["meta"])

    _trace_econ_bad_entry_return(
        signal=signal,
        ctx=ctx,
        entry_reason=entry_reason,
        override=override,
        final_decision="TAKE",
    )

    log.warning(
        "[ECON_BAD_RECOVERY_PROBE] symbol=%s kind=%s ev=%.4f score=%.3f p=%.3f coh=%.3f af=%.3f size_mult=%s reason=%s",
        symbol,
        override.get("kind"),
        ev,
        score,
        p,
        coh,
        af,
        override.get("size_mult"),
        override.get("reason"),
    )

    return TAKE using the existing project return format
```

If not allowed:

```python
_trace_econ_bad_entry_return(
    signal=signal,
    ctx=ctx,
    entry_reason=entry_reason,
    override=override,
    final_decision="REJECT_ECON_BAD_ENTRY",
)

return existing REJECT_ECON_BAD_ENTRY unchanged
```

Critical:

- Do not invent a new TAKE return format.
- Use the existing format around V10.13u+17/V10.13u+19 recovery probe.
- Do not bypass hard negative EV returns.
- Negative EV must remain `REJECT_NEGATIVE_EV` before this weak-EV override path.

---

### 4. Fix `_trace_econ_bad_entry_return()`

Find V10.13u+19c helper, likely named:

```python
_trace_econ_bad_entry_return(...)
```

Change it so it accepts or derives the normalized override result.

Expected log fields:

```text
[ECON_BAD_ENTRY_RETURN_TRACE]
symbol=<symbol>
ev=<ev>
score=<score>
p=<p>
coh=<coh>
af=<af>
pf=<pf>
econ_status=<status>
entry_reason=<entry_reason>
snapshot_probe_ready=<snapshot_probe_ready>
snapshot_probe_block=<snapshot_probe_block>
actual_recovery_checked=<override.checked>
actual_recovery_allowed=<override.allowed>
actual_recovery_reason=<override.reason>
actual_recovery_kind=<override.kind>
open_positions=<n>
idle_s=<idle_s>
forced=<bool>
final_decision=<TAKE|REJECT_ECON_BAD_ENTRY>
```

Bug fix:

- Do not derive `actual_recovery_checked` from snapshot.
- Do not default to `not_overridable` after the resolver has returned `below_probe_ev`.
- Use `override["checked"]`, `override["allowed"]`, `override["reason"]`.

---

### 5. Fix READY_BUT_REJECTED invariant

Current noisy behavior is wrong if based on snapshot:

```text
snapshot_probe_ready=True snapshot_probe_block=none
actual_recovery_checked=False actual_recovery_allowed=False
final_decision=REJECT
```

New invariant condition must be:

```python
if (
    override.get("checked") is True
    and override.get("allowed") is True
    and final_decision != "TAKE"
):
    log.error("[ECON_BAD_READY_BUT_REJECTED] ...")
```

Do not trigger on:

```python
snapshot_probe_ready=True
snapshot_probe_block="none"
```

Snapshot can be stale or global-best based. The invariant must use actual per-signal resolver result only.

---

### 6. Expected production log after patch

For weak EV below recovery floor:

```text
[ECON_BAD_ENTRY_RETURN_TRACE] symbol=XRPUSDT ev=0.0338 ... snapshot_probe_ready=False snapshot_probe_block=below_probe_ev actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=below_probe_ev final_decision=REJECT_ECON_BAD_ENTRY
```

For strong recovery candidate:

```text
[ECON_BAD_ENTRY_RETURN_TRACE] symbol=ADAUSDT ev=0.0434 ... actual_recovery_checked=True actual_recovery_allowed=True actual_recovery_reason=recovery_probe_allowed actual_recovery_kind=recovery final_decision=TAKE
[ECON_BAD_RECOVERY_PROBE] symbol=ADAUSDT kind=recovery ev=0.0434 ...
decision=TAKE
```

For deadlock candidate:

```text
[ECON_BAD_ENTRY_RETURN_TRACE] symbol=XRPUSDT ev=0.0370 ... actual_recovery_checked=True actual_recovery_allowed=True actual_recovery_reason=deadlock_probe_allowed actual_recovery_kind=deadlock final_decision=TAKE
[ECON_BAD_DEADLOCK_PROBE] symbol=XRPUSDT ...
decision=TAKE
```

---

## Tests to Add

Append to `tests/test_v10_13u_patches.py`.

Use the existing helper reset functions if present. If names differ, adapt to current test style.

### Test 1 — below floor reason propagates

```python
def test_v10_13u19e_below_probe_ev_reason_propagates(caplog):
    """Weak-EV reject below recovery/deadlock floors logs exact actual reason."""
    from src.services.realtime_decision_engine import (
        _normalize_econ_bad_override_result,
        _trace_econ_bad_entry_return,
    )

    override = _normalize_econ_bad_override_result({
        "checked": True,
        "allowed": False,
        "reason": "below_probe_ev",
        "kind": None,
        "size_mult": None,
        "meta": {},
    })

    signal = {
        "symbol": "XRPUSDT",
        "ev": 0.0338,
        "score": 0.174,
        "p": 0.500,
        "coh": 0.675,
        "af": 0.595,
    }
    ctx = {
        "open_positions": 0,
        "idle_s": 1234,
        "forced": False,
        "snapshot_probe_ready": False,
        "snapshot_probe_block": "below_probe_ev",
    }

    _trace_econ_bad_entry_return(
        signal=signal,
        ctx=ctx,
        entry_reason="weak_ev (ev=0.0338<0.045)",
        override=override,
        final_decision="REJECT_ECON_BAD_ENTRY",
    )

    assert "[ECON_BAD_ENTRY_RETURN_TRACE]" in caplog.text
    assert "actual_recovery_checked=True" in caplog.text
    assert "actual_recovery_allowed=False" in caplog.text
    assert "actual_recovery_reason=below_probe_ev" in caplog.text
    assert "[ECON_BAD_READY_BUT_REJECTED]" not in caplog.text
```

### Test 2 — no stale snapshot invariant

```python
def test_v10_13u19e_snapshot_ready_does_not_trigger_invariant(caplog):
    """Snapshot readiness alone must not trigger READY_BUT_REJECTED."""
    from src.services.realtime_decision_engine import (
        _normalize_econ_bad_override_result,
        _trace_econ_bad_entry_return,
    )

    override = _normalize_econ_bad_override_result({
        "checked": True,
        "allowed": False,
        "reason": "below_probe_ev",
        "kind": None,
        "size_mult": None,
        "meta": {},
    })

    signal = {
        "symbol": "ADAUSDT",
        "ev": 0.0338,
        "score": 0.174,
        "p": 0.523,
        "coh": 0.675,
        "af": 0.595,
    }
    ctx = {
        "open_positions": 0,
        "idle_s": 3000,
        "forced": False,
        "snapshot_probe_ready": True,
        "snapshot_probe_block": "none",
    }

    _trace_econ_bad_entry_return(
        signal=signal,
        ctx=ctx,
        entry_reason="weak_ev (ev=0.0338<0.045)",
        override=override,
        final_decision="REJECT_ECON_BAD_ENTRY",
    )

    assert "snapshot_probe_ready=True" in caplog.text
    assert "snapshot_probe_block=none" in caplog.text
    assert "actual_recovery_allowed=False" in caplog.text
    assert "actual_recovery_reason=below_probe_ev" in caplog.text
    assert "[ECON_BAD_READY_BUT_REJECTED]" not in caplog.text
```

### Test 3 — actual allowed but rejected triggers invariant

```python
def test_v10_13u19e_actual_allowed_reject_triggers_invariant(caplog):
    """READY_BUT_REJECTED fires only if actual resolver allowed TAKE."""
    from src.services.realtime_decision_engine import (
        _normalize_econ_bad_override_result,
        _trace_econ_bad_entry_return,
    )

    override = _normalize_econ_bad_override_result({
        "checked": True,
        "allowed": True,
        "reason": "recovery_probe_allowed",
        "kind": "recovery",
        "size_mult": 0.15,
        "meta": {},
    })

    signal = {
        "symbol": "ADAUSDT",
        "ev": 0.0434,
        "score": 0.204,
        "p": 0.523,
        "coh": 0.868,
        "af": 0.750,
    }
    ctx = {
        "open_positions": 0,
        "idle_s": 50000,
        "forced": False,
        "snapshot_probe_ready": True,
        "snapshot_probe_block": "none",
    }

    _trace_econ_bad_entry_return(
        signal=signal,
        ctx=ctx,
        entry_reason="weak_ev (ev=0.0434<0.045)",
        override=override,
        final_decision="REJECT_ECON_BAD_ENTRY",
    )

    assert "[ECON_BAD_READY_BUT_REJECTED]" in caplog.text
    assert "actual_recovery_allowed=True" in caplog.text
    assert "actual_recovery_reason=recovery_probe_allowed" in caplog.text
```

### Test 4 — TAKE path does not trigger invariant

```python
def test_v10_13u19e_allowed_take_no_invariant(caplog):
    """Allowed recovery TAKE path is not an invariant violation."""
    from src.services.realtime_decision_engine import (
        _normalize_econ_bad_override_result,
        _trace_econ_bad_entry_return,
    )

    override = _normalize_econ_bad_override_result({
        "checked": True,
        "allowed": True,
        "reason": "recovery_probe_allowed",
        "kind": "recovery",
        "size_mult": 0.15,
        "meta": {},
    })

    signal = {
        "symbol": "ADAUSDT",
        "ev": 0.0434,
        "score": 0.204,
        "p": 0.523,
        "coh": 0.868,
        "af": 0.750,
    }
    ctx = {"open_positions": 0, "idle_s": 50000, "forced": False}

    _trace_econ_bad_entry_return(
        signal=signal,
        ctx=ctx,
        entry_reason="weak_ev (ev=0.0434<0.045)",
        override=override,
        final_decision="TAKE",
    )

    assert "[ECON_BAD_ENTRY_RETURN_TRACE]" in caplog.text
    assert "actual_recovery_allowed=True" in caplog.text
    assert "final_decision=TAKE" in caplog.text
    assert "[ECON_BAD_READY_BUT_REJECTED]" not in caplog.text
```

### Test 5 — normalizer is exception safe

```python
def test_v10_13u19e_override_normalizer_handles_bad_input():
    from src.services.realtime_decision_engine import _normalize_econ_bad_override_result

    out = _normalize_econ_bad_override_result(None)

    assert out["checked"] is False
    assert out["allowed"] is False
    assert out["reason"] == "not_overridable"
    assert isinstance(out["meta"], dict)
```

### Test 6 — no global thresholds changed

```python
def test_v10_13u19e_no_threshold_changes():
    import src.services.realtime_decision_engine as rde

    # Adapt names if project uses different constant names.
    assert getattr(rde, "ECON_BAD_DEADLOCK_MIN_EV") == 0.0370
    assert getattr(rde, "ECON_BAD_DEADLOCK_MAX_EV") == 0.0380
```

---

## Validation Commands

Run from project root on server/local:

```bash
source venv/bin/activate 2>/dev/null || true

python -m py_compile src/services/realtime_decision_engine.py

python -m pytest tests/test_v10_13u_patches.py -k "v10_13u19e or v10_13u19d or v10_13u19c" -v

git diff --check
git status --short
```

If full suite is noisy due unrelated old tests, at minimum require all V10.13u tests around this family to pass.

---

## Commit

```bash
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+19e: propagate recovery blocker reason in ECON BAD traces"
git push origin main
```

---

## Deploy Validation

After deploy/restart:

```bash
sudo journalctl -u cryptomaster --since "20 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_ENTRY_RETURN_TRACE|ECON_BAD_READY_BUT_REJECTED|ECON_BAD_RECOVERY_PROBE|ECON_BAD_DEADLOCK|Traceback"
```

Expected after weak low-EV reject:

```text
actual_recovery_checked=True
actual_recovery_allowed=False
actual_recovery_reason=below_probe_ev
final_decision=REJECT_ECON_BAD_ENTRY
```

Expected absent unless real bug:

```text
[ECON_BAD_READY_BUT_REJECTED]
```

If actual strong candidate appears:

```text
[ECON_BAD_RECOVERY_PROBE]
decision=TAKE
```

If deadlock candidate appears after 12h+ and all floors pass:

```text
[ECON_BAD_DEADLOCK_PROBE]
decision=TAKE
```

---

## Safety Notes

Do not patch thresholds in this step.

Do not change:

- `0.045` ECON BAD normal entry floor
- `0.038` recovery probe floor
- `0.0370–0.0380` deadlock band
- negative EV hard block
- forced-explore gate
- open-position cap
- cooldowns
- per-24h caps
- Firebase behavior

This patch should make logs truthful and prove whether recovery/deadlock override is actually evaluated before weak-EV rejection.
