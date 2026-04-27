# CryptoMaster V10.13u+19f — Token-Safe Patch Prompt

## Goal
Fix ECON BAD recovery override wiring. Production still logs:
`actual_recovery_checked=False actual_recovery_reason=not_overridable`
on weak ECON BAD rejects. That is wrong. Weak ECON BAD paths must call the recovery/deadlock override resolver before returning, then trace the exact blocker.

## Live symptom
Current logs after commit `b4177a9/0cc68b3`:
`[ECON_BAD_ENTRY_RETURN_TRACE] ... snapshot_probe_ready=True/False ... actual_recovery_checked=False actual_recovery_reason=not_overridable final_decision=REJECT_ECON_BAD_ENTRY`

Expected after fix:
`actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=<specific_blocker>`

Examples:
- `below_probe_ev`
- `below_probe_score`
- `below_probe_p`
- `below_probe_coh`
- `below_probe_af`
- `idle_too_low`
- `open_position_cap`
- `cooldown`
- `forced_blocked`
- `forbidden_tag`
- `negative_ev`
- `daily_cap`
- `econ_not_bad`

## Hard safety rules
Do NOT loosen or change:
- EV-only hard reject: `ev <= 0`
- ECON_BAD_ENTRY floor: `ev >= 0.045`
- normal recovery floor: `ev >= 0.038`
- deadlock band: `0.0370 <= ev < 0.0380`
- score/p/coh/af floors
- position caps/cooldowns/per-24h caps
- forced exploration blocks
- TP/SL/exit logic
- Firebase reads/writes

This is wiring + trace propagation only. If existing resolver allows a probe, allow TAKE through existing recovery/deadlock metadata. Otherwise reject with exact reason.

## Files
- `src/services/realtime_decision_engine.py`
- `tests/test_v10_13u_patches.py`

## Step 1 — Find weak ECON BAD return paths
Run:
```bash
grep -n "REJECT_ECON_BAD_ENTRY\|_trace_econ_bad_entry_return\|not_overridable\|weak_ev\|weak_score\|weak_p\|weak_coh\|weak_af" src/services/realtime_decision_engine.py
```

Patch every recoverable ECON BAD entry reject path:
- `weak_ev`
- `weak_score`
- if present: `weak_p`, `weak_coh`, `weak_af`

Do NOT make negative EV recoverable.

## Step 2 — Always resolve override before weak ECON BAD return
Before any recoverable:
```python
return ("REJECT_ECON_BAD_ENTRY", entry_reason)
```

add:
```python
override = _resolve_econ_bad_recovery_override_for_signal(
    signal=signal,
    ctx=ctx,
    entry_reason=entry_reason,
)
override = _normalize_econ_bad_override_result(override)
```

If allowed:
```python
if override.get("allowed"):
    signal["_econ_bad_recovery_probe"] = True
    signal["_econ_bad_recovery_kind"] = override.get("kind")
    signal["_econ_bad_recovery_size_mult"] = override.get("size_mult")
    signal["_econ_bad_recovery_reason"] = override.get("reason")
    signal["_econ_bad_recovery_meta"] = override.get("meta") or {}

    _trace_econ_bad_entry_return(
        signal=signal,
        ctx=ctx,
        entry_reason=entry_reason,
        override=override,
        final_decision="TAKE",
    )

    log.warning(
        "[ECON_BAD_RECOVERY_PROBE] symbol=%s kind=%s ev=%.4f score=%.3f p=%.3f coh=%.3f af=%.3f size_mult=%.3f reason=%s",
        symbol,
        override.get("kind"),
        ev,
        score,
        p,
        coh,
        af,
        float(override.get("size_mult") or 0.0),
        override.get("reason"),
    )
    return ("TAKE", "ECON_BAD_RECOVERY_PROBE")
```

If blocked:
```python
_trace_econ_bad_entry_return(
    signal=signal,
    ctx=ctx,
    entry_reason=entry_reason,
    override=override,
    final_decision="REJECT_ECON_BAD_ENTRY",
)
return ("REJECT_ECON_BAD_ENTRY", entry_reason)
```

## Step 3 — Trace must not hide missing override
In `_trace_econ_bad_entry_return()`, derive actual fields from normalized override:
```python
if override is None:
    norm = {
        "checked": False,
        "allowed": False,
        "reason": "override_missing_bug",
        "kind": "none",
        "size_mult": None,
        "meta": {},
    }
else:
    norm = _normalize_econ_bad_override_result(override)

actual_checked = bool(norm.get("checked"))
actual_allowed = bool(norm.get("allowed"))
actual_reason = str(norm.get("reason") or "unknown")
actual_kind = str(norm.get("kind") or "none")
```

`not_overridable` must not appear for weak ECON BAD paths after this patch. If override is missing, log `override_missing_bug`.

## Step 4 — Fix READY_BUT_REJECTED invariant
Do NOT use `snapshot_probe_ready` for invariant.

Only emit `[ECON_BAD_READY_BUT_REJECTED]` when:
```python
actual_checked is True and actual_allowed is True and final_decision != "TAKE"
```

Snapshot readiness is diagnostic only, not final authority.

## Step 5 — Tests
Add focused tests:
```python
def test_v10_13u19f_weak_ev_calls_override_before_reject():
    pass  # checked=True + exact blocker, not not_overridable

def test_v10_13u19f_weak_score_calls_override_before_reject():
    pass  # weak_score path calls resolver before reject

def test_v10_13u19f_override_missing_logs_bug_reason():
    pass  # override=None logs override_missing_bug

def test_v10_13u19f_snapshot_ready_does_not_trigger_invariant():
    pass  # snapshot_probe_ready alone is not invariant

def test_v10_13u19f_actual_allowed_reject_triggers_invariant():
    pass  # actual allowed=True + final REJECT emits READY_BUT_REJECTED

def test_v10_13u19f_allowed_override_returns_take():
    pass  # allowed resolver result returns TAKE with metadata
```

## Validation
```bash
python -m py_compile src/services/realtime_decision_engine.py
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u19f or v10_13u19e or v10_13u19d or v10_13u19c" -v
git diff --check
```

Commit:
```bash
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+19f: invoke recovery override before ECON BAD return"
git push origin main
```

## Live validation
```bash
sudo journalctl -u cryptomaster --since "20 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_ENTRY_RETURN_TRACE|ECON_BAD_READY_BUT_REJECTED|ECON_BAD_RECOVERY_PROBE|ECON_BAD_DEADLOCK|decision=TAKE|Traceback"
```

Good reject example after restart:
```text
[ECON_BAD_ENTRY_RETURN_TRACE] ... actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=idle_too_low final_decision=REJECT_ECON_BAD_ENTRY
```

Good blocker example:
```text
actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=below_probe_ev
```

Good allowed example:
```text
[ECON_BAD_RECOVERY_PROBE] ... decision=TAKE
```

Bad output after patch:
```text
actual_recovery_checked=False actual_recovery_reason=not_overridable
```

If bad output remains, another production return path still bypasses resolver.

## Interpretation
After restart, `idle_s` is low, so rejects are normal. The required fix is not more trades. The required fix is truthful trace:
`checked=True + exact blocker`.
