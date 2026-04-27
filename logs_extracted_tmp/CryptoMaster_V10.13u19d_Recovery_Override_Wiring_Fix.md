# CryptoMaster V10.13u+19d — Recovery Override Wiring Fix

## Goal
Fix the live bug where ECON BAD recovery diagnostics show `probe_ready=True probe_block=none`, but the signal is still returned as `REJECT_ECON_BAD_ENTRY` because the actual recovery override is not evaluated before the weak-EV return.

This is an incremental, safety-preserving patch. Do not loosen global thresholds. Do not change Firebase writes, TP/SL, exits, or normal entry gates.

## Live Evidence
Production commit: `7351e66`

Representative log:
```text
[ECON_BAD_ENTRY_RETURN_TRACE] symbol=XRPUSDT ev=0.0348 score=0.172 p=0.636 coh=0.697 af=0.595 pf=0.739 econ_status=BAD
entry_reason=weak_ev (ev=0.0348<0.045)
snapshot_probe_ready=True snapshot_probe_block=none
actual_recovery_checked=False actual_recovery_allowed=False actual_recovery_reason=not_overridable
open_positions=0 idle_s=1904 forced=False final_decision=REJECT_ECON_BAD_ENTRY

[ECON_BAD_READY_BUT_REJECTED] ... final_decision=REJECT_ECON_BAD_ENTRY
```

Older stronger candidate:
```text
best_symbol=ADAUSDT best_ev=0.0434 best_score=0.204 best_p=0.523 best_coh=0.868 best_af=0.750
probe_ready=True probe_block=none
```

## Diagnosis
There are two separate issues:

1. **Recovery override is not actually checked in weak-EV return path**
   - Trace shows `actual_recovery_checked=False`
   - `actual_recovery_reason=not_overridable`
   - Final decision remains `REJECT_ECON_BAD_ENTRY`

2. **Snapshot readiness is global/stale, not necessarily per-current-signal**
   - Current rejected signal may have `ev=0.0300`, `p=0.500`, `coh=0.558`, `af=0.595`
   - These are unsafe and must remain rejected
   - Therefore `[ECON_BAD_READY_BUT_REJECTED]` must only fire when the **current signal’s actual recovery check** says allowed, not merely when snapshot says ready

## Required Behavior
Before returning `REJECT_ECON_BAD_ENTRY` for `weak_ev`, evaluate the actual per-signal recovery/deadlock override.

Allowed recovery override only if all existing recovery floors pass:
- EV > 0
- EV >= normal recovery floor, or deadlock near-miss band if deadlock mode applies
- score/p/coh/af floors pass
- ECON BAD status confirmed
- no open-position violation
- idle requirement passes
- cooldown/caps pass
- no forbidden tags
- not forced weak/explore
- hard negative EV still rejected before all overrides

Current low-quality candidates like these must still reject:
```text
ev=0.0300 score=0.168 p=0.636 coh=0.580 af=0.595
ev=0.0348 score=0.172 p=0.500 coh=0.697 af=0.595
```

A strong candidate like this should be allowed if all existing recovery caps pass:
```text
ev=0.0434 score=0.204 p=0.523 coh=0.868 af=0.750 open_positions=0 forced=False
```

## Implementation Plan

### 1. Add a single per-signal resolver
In `src/services/realtime_decision_engine.py`, add helper near recovery/deadlock helpers:

```python
def _resolve_econ_bad_recovery_override_for_signal(signal, ctx, entry_reason: str):
    """
    Decide whether current weak-EV ECON BAD rejection may be overridden by
    normal recovery probe or deadlock probe.

    Returns:
        dict {
          "checked": bool,
          "allowed": bool,
          "reason": str,
          "kind": "normal" | "deadlock" | "none",
          "size_mult": float | None,
          "meta": dict,
        }

    Observability-safe. Never raises.
    Must not mutate signal unless caller applies allowed result.
    """
```

Rules:
- If not ECON BAD: `{checked: False, allowed: False, reason: "econ_not_bad"}`
- If `entry_reason` is not weak-EV / probe-low candidate: `{checked: False, allowed: False, reason: "not_overridable"}`
- If EV <= 0: `{checked: True, allowed: False, reason: "negative_ev"}`
- First call the existing normal recovery probe check.
- If normal recovery allows: return `allowed=True, kind="normal", size_mult=<existing recovery size mult>`.
- If normal recovery blocks only because EV is slightly below normal probe floor, then call existing deadlock near-miss check.
- If deadlock allows: return `allowed=True, kind="deadlock", size_mult=ECON_BAD_DEADLOCK_SIZE_MULT`.
- Otherwise return exact blocker reason.

Do not create duplicate threshold constants unless already needed. Reuse existing V10.13u+17/+19 helpers and constants.

### 2. Wire before weak-EV return
Find both ECON BAD weak-EV return paths:
```python
return ("REJECT_ECON_BAD_ENTRY", ...)
```

Immediately before return:
```python
override = _resolve_econ_bad_recovery_override_for_signal(signal, ctx, entry_reason)

_trace_econ_bad_entry_return(
    signal=signal,
    ctx=ctx,
    entry_reason=entry_reason,
    actual_recovery_checked=override["checked"],
    actual_recovery_allowed=override["allowed"],
    actual_recovery_reason=override["reason"],
    final_decision="TAKE" if override["allowed"] else "REJECT_ECON_BAD_ENTRY",
)
```

If allowed:
```python
signal["_econ_bad_recovery_probe"] = override["kind"] == "normal"
signal["_econ_bad_deadlock_probe"] = override["kind"] == "deadlock"
signal["_econ_bad_probe_size_mult"] = override["size_mult"]
signal["_econ_bad_probe_reason"] = override["reason"]

log.warning(
    "[ECON_BAD_RECOVERY_PROBE] symbol=%s kind=%s ev=%.4f score=%.3f p=%.3f coh=%.3f af=%.3f size_mult=%.3f reason=%s",
    ...
)

return TAKE_RESULT  # Use the same TAKE contract used elsewhere in evaluate_signal()
```

Use the project’s real TAKE return contract. Do not invent a new return tuple shape.

### 3. Fix READY_BUT_REJECTED invariant
Change invariant trigger from:
```python
snapshot_probe_ready=True and snapshot_probe_block="none" and final_decision="REJECT"
```

to:
```python
actual_recovery_checked is True
and actual_recovery_allowed is True
and final_decision.startswith("REJECT")
```

Snapshot readiness can still be logged, but must not trigger an ERROR invariant by itself.

### 4. Keep hard safety order
Hard negative EV remains before any override:
```python
if ev <= 0:
    return REJECT_NEGATIVE_EV
```

Forbidden tags, forced exploration, open-position cap, cooldown and per-24h caps must remain enforced by the existing helper checks.

## Tests to Add

Add to `tests/test_v10_13u_patches.py`.

### test_v10_13u19d_weak_ev_recovery_checked_before_return
- Setup ECON BAD, no positions, idle ok.
- Signal: `ev=0.0434, score=0.204, p=0.523, coh=0.868, af=0.750`
- Entry reason: weak_ev.
- Assert actual recovery checked.
- Assert final decision is TAKE or recovery probe allowed according to project return contract.
- Assert no `REJECT_ECON_BAD_ENTRY`.

### test_v10_13u19d_low_quality_weak_ev_still_rejected
- Signal: `ev=0.0348, score=0.172, p=0.500, coh=0.697, af=0.595`
- Assert recovery checked or explicitly blocked.
- Assert final decision remains `REJECT_ECON_BAD_ENTRY`.
- Assert reason includes the real blocker, e.g. `below_probe_ev`, `weak_p`, `weak_af`, or `weak_coh`.

### test_v10_13u19d_negative_ev_still_hard_rejected
- Signal EV < 0.
- Assert `REJECT_NEGATIVE_EV`.
- Assert recovery override is not allowed.

### test_v10_13u19d_ready_but_rejected_uses_actual_not_snapshot
- Mock snapshot `probe_ready=True probe_block=none`.
- Current signal fails actual floors.
- Assert no `[ECON_BAD_READY_BUT_REJECTED]`.
- Assert trace logs actual blocker.

### test_v10_13u19d_actual_allowed_but_rejected_emits_invariant
- Mock resolver returning `checked=True allowed=True`.
- Force final reject path only in test.
- Assert `[ECON_BAD_READY_BUT_REJECTED]` emits.

### test_v10_13u19d_no_global_threshold_change
- Assert existing constants unchanged:
  - ECON BAD entry floor remains 0.045
  - normal recovery floor remains 0.038
  - deadlock near-miss band remains 0.0370–0.0380

## Validation Commands
```bash
cd /opt/cryptomaster
source venv/bin/activate

python -m py_compile src/services/realtime_decision_engine.py
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u19d or v10_13u19c or v10_13u19 or v10_13u18" -v
git diff --check
git status --short
```

## Commit
```bash
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+19d: wire recovery override before ECON BAD weak-EV return"
git push origin main
```

## Production Validation
After deploy/restart:
```bash
sudo systemctl restart cryptomaster
sleep 90

sudo journalctl -u cryptomaster --since "15 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_ENTRY_RETURN_TRACE|ECON_BAD_READY_BUT_REJECTED|ECON_BAD_RECOVERY_TRACE|ECON_BAD_RECOVERY_PROBE|ECON_BAD_DEADLOCK|decision=TAKE|decision=REJECT_ECON_BAD_ENTRY|Traceback"
```

Expected:
```text
[RUNTIME_VERSION] ... commit=<new_commit>
[ECON_BAD_ENTRY_RETURN_TRACE] ... actual_recovery_checked=True ...
```

If strong candidate passes:
```text
[ECON_BAD_RECOVERY_PROBE] ... kind=normal ...
decision=TAKE
```

If weak candidate fails:
```text
[ECON_BAD_ENTRY_RETURN_TRACE] ... actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=<real_floor_reason>
decision=REJECT_ECON_BAD_ENTRY
```

Should disappear:
```text
actual_recovery_checked=False actual_recovery_reason=not_overridable
[ECON_BAD_READY_BUT_REJECTED] caused only by snapshot_probe_ready=True
```

## Rollback
```bash
git revert <new_commit>
sudo systemctl restart cryptomaster
```

Kill-switch alternative if implemented via env/config:
```text
ECON_BAD_RECOVERY_PROBE_ENABLED=False
ECON_BAD_DEADLOCK_PROBE_ENABLED=False
```

## Acceptance Criteria
- No negative/zero EV trade can pass.
- No global threshold loosened.
- Low-quality weak-EV candidates still reject.
- Strong recovery candidate is checked before weak-EV return.
- `actual_recovery_checked=False/not_overridable` no longer appears for weak-EV candidates that should be probe-evaluable.
- `READY_BUT_REJECTED` only fires when actual per-signal override says allowed but final return rejects.
