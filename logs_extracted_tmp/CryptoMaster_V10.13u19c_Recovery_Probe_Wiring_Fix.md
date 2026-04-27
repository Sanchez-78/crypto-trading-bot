# CryptoMaster V10.13u+19c — Recovery Probe Wiring Fix + Return-Path Audit

## Goal

Fix the confirmed invariant in production logs:

- Diagnostics repeatedly show `probe_ready=True probe_block=none`
- Best candidate is safe enough for the controlled recovery path:
  - `ADAUSDT ev=0.0434 score=0.204 p=0.523 coh=0.868 af=0.750`
  - `pf=0.739 econ_status=BAD`
- But the runtime still returns:
  - `decision=REJECT_ECON_BAD_ENTRY weak_ev (ev=0.0300/0.0338/0.0348<0.045)`
- No `[ECON_BAD_RECOVERY_TRACE]`, `[ECON_BAD_READY_BUT_REJECTED]`, `[ECON_BAD_RECOVERY_PROBE]`, or `[ECON_BAD_DEADLOCK_PROBE]` appears after commit `7351e66`.

Conclusion: V10.13u+19b tracing is not wired into the actual production `REJECT_ECON_BAD_ENTRY weak_ev` return path, or the weak-EV gate returns before the recovery probe override is evaluated.

This patch must **not loosen global gates**. It must only ensure that the already-designed controlled recovery/deadlock probe path is evaluated before the weak-EV ECON BAD return, and log the exact reason when it is not allowed.

## Current Production Evidence

Runtime is correct:

```text
[RUNTIME_VERSION] commit=7351e66
```

Invariant:

```text
[ECON_BAD_DIAG_HEARTBEAT] source=rde_reject pf=0.739 econ_status=BAD ... best_symbol=ADAUSDT best_ev=0.0434 best_score=0.204 best_p=0.523 best_coh=0.868 best_af=0.750 probe_ready=True probe_block=none
[ECON_BAD_NEAR_MISS_SUMMARY] ... probe_ready=True probe_block=none
decision=REJECT_ECON_BAD_ENTRY weak_ev (ev=0.0300<0.045)
decision=REJECT_ECON_BAD_ENTRY weak_ev (ev=0.0348<0.045)
```

Expected but missing:

```text
[ECON_BAD_RECOVERY_TRACE]
[ECON_BAD_READY_BUT_REJECTED]
[ECON_BAD_RECOVERY_PROBE]
[ECON_BAD_DEADLOCK_PROBE]
```

## Files

Primary:

```text
src/services/realtime_decision_engine.py
tests/test_v10_13u_patches.py
```

Do not change Firebase, TP/SL, exit logic, portfolio sizing outside the existing probe size multiplier, or Android/dashboard code.

## Required Implementation

### 1. Add a return-path trace helper

Add a helper near the existing ECON BAD diagnostic helpers:

```python
def _trace_econ_bad_entry_return(
    *,
    symbol: str,
    ev: float,
    score: float,
    p: float,
    coh: float,
    af: float,
    entry_reason: str,
    final_decision: str,
    actual_recovery_checked: bool = False,
    actual_recovery_allowed: bool = False,
    actual_recovery_reason: str = "not_checked",
    open_positions: int = 0,
    idle_s: float = 0.0,
    forced: bool = False,
) -> None:
    """Trace the actual production return path for ECON BAD entry rejection.

    Observability only. Never raises.
    """
    try:
        snap = get_econ_bad_diagnostics_snapshot()
        pf = snap.get("pf")
        econ_status = snap.get("econ_status")
        snapshot_ready = snap.get("probe_ready")
        snapshot_block = snap.get("probe_block")

        log.warning(
            "[ECON_BAD_ENTRY_RETURN_TRACE] "
            "symbol=%s ev=%.4f score=%.3f p=%.3f coh=%.3f af=%.3f "
            "pf=%s econ_status=%s entry_reason=%s "
            "snapshot_probe_ready=%s snapshot_probe_block=%s "
            "actual_recovery_checked=%s actual_recovery_allowed=%s "
            "actual_recovery_reason=%s open_positions=%s idle_s=%.0f forced=%s "
            "final_decision=%s",
            symbol,
            float(ev or 0.0),
            float(score or 0.0),
            float(p or 0.0),
            float(coh or 0.0),
            float(af or 0.0),
            pf,
            econ_status,
            entry_reason,
            snapshot_ready,
            snapshot_block,
            actual_recovery_checked,
            actual_recovery_allowed,
            actual_recovery_reason,
            open_positions,
            float(idle_s or 0.0),
            forced,
            final_decision,
        )

        if (
            snapshot_ready is True
            and str(snapshot_block) == "none"
            and str(final_decision).startswith("REJECT")
        ):
            log.error(
                "[ECON_BAD_READY_BUT_REJECTED] "
                "symbol=%s ev=%.4f score=%.3f p=%.3f coh=%.3f af=%.3f "
                "pf=%s econ_status=%s entry_reason=%s "
                "actual_recovery_checked=%s actual_recovery_allowed=%s "
                "actual_recovery_reason=%s final_decision=%s",
                symbol,
                float(ev or 0.0),
                float(score or 0.0),
                float(p or 0.0),
                float(coh or 0.0),
                float(af or 0.0),
                pf,
                econ_status,
                entry_reason,
                actual_recovery_checked,
                actual_recovery_allowed,
                actual_recovery_reason,
                final_decision,
            )
    except Exception as exc:
        try:
            log.warning("[ECON_BAD_ENTRY_RETURN_TRACE_ERROR] err=%s", str(exc)[:160])
        except Exception:
            pass
```

### 2. Wire it into the real `REJECT_ECON_BAD_ENTRY weak_ev` return path

Find every branch that logs or returns:

```text
decision=REJECT_ECON_BAD_ENTRY  weak_ev
```

or returns:

```python
"REJECT_ECON_BAD_ENTRY"
```

especially where the reason is `weak_ev`, `below_probe_ev`, `probe_ev_too_low`, or ECON BAD entry quality gate.

Before returning rejection, perform this order:

1. Update near-miss diagnostics as today.
2. Try the existing V10.13u+17 recovery probe / V10.13u+19 deadlock probe decision path.
3. If actual recovery/deadlock probe is allowed, return the existing controlled `TAKE` path with existing probe metadata and size multiplier.
4. If not allowed, log `_trace_econ_bad_entry_return(...)` and then return `REJECT_ECON_BAD_ENTRY`.

Pseudocode:

```python
# Existing ECON BAD weak_ev gate
if econ_bad and ev < econ_bad_entry_ev_floor:
    _update_econ_bad_near_miss(...)
    _maybe_emit_econ_bad_diag_from_reject(source="rde_reject")

    actual_checked = False
    actual_allowed = False
    actual_reason = "not_checked"

    # Critical: call the real existing recovery/deadlock probe logic here,
    # before returning REJECT_ECON_BAD_ENTRY.
    try:
        actual_checked = True

        # Reuse existing helper/logic. Do not duplicate thresholds if a helper exists.
        # Preferred:
        # actual_allowed, actual_reason, recovery_meta = _econ_bad_recovery_probe_allowed(signal, ctx)
        #
        # If normal recovery blocks only on below_probe_ev/probe_ev_too_low, then test deadlock helper:
        # deadlock_allowed, deadlock_reason, deadlock_meta = _econ_bad_deadlock_nearmiss_probe_allowed(signal, ctx)

        if actual_allowed:
            signal["_econ_bad_recovery_probe"] = True
            signal["_size_mult"] = recovery_meta.get("size_mult", ECON_BAD_RECOVERY_PROBE_SIZE_MULT)
            log.warning("[ECON_BAD_RECOVERY_PROBE] ...")
            _trace_econ_bad_entry_return(
                symbol=symbol, ev=ev, score=score, p=p, coh=coh, af=af,
                entry_reason="weak_ev",
                final_decision="TAKE",
                actual_recovery_checked=True,
                actual_recovery_allowed=True,
                actual_recovery_reason=actual_reason,
                open_positions=open_positions,
                idle_s=idle_s,
                forced=forced,
            )
            return TAKE_WITH_EXISTING_CONTRACT
    except Exception as exc:
        actual_reason = f"recovery_check_error:{str(exc)[:120]}"

    _trace_econ_bad_entry_return(
        symbol=symbol, ev=ev, score=score, p=p, coh=coh, af=af,
        entry_reason="weak_ev",
        final_decision="REJECT_ECON_BAD_ENTRY",
        actual_recovery_checked=actual_checked,
        actual_recovery_allowed=actual_allowed,
        actual_recovery_reason=actual_reason,
        open_positions=open_positions,
        idle_s=idle_s,
        forced=forced,
    )
    return REJECT_ECON_BAD_ENTRY_WITH_EXISTING_CONTRACT
```

### 3. Important logic constraints

Do **not** lower these existing global thresholds:

```text
ECON_BAD_ENTRY_EV floor = 0.045
normal recovery EV floor = 0.038
deadlock EV band = 0.0370–0.0380
EV-only hard rule: EV <= 0 must always reject
```

Do **not** allow a probe if:

```text
ev <= 0
open_positions >= configured cap
forced weak/explore signal
LOSS_CLUSTER / TOXIC / SPREAD / NEGATIVE_EV / FAST_FAIL tag present
cooldown or per-24h cap exceeded
required score/p/coh/af floors fail
```

This patch is a wiring fix: existing controlled probe should be reachable before the weak-EV reject return.

### 4. Tests

Add tests focused on the real return path, not only helper functions.

Required tests:

```python
def test_v10_13u19c_econ_bad_entry_return_trace_emits_on_weak_ev_reject(...):
    """Weak-EV ECON BAD reject emits ECON_BAD_ENTRY_RETURN_TRACE."""

def test_v10_13u19c_ready_but_rejected_invariant_emits(...):
    """If snapshot says ready=True/block=none but final reject occurs, emit ECON_BAD_READY_BUT_REJECTED."""

def test_v10_13u19c_recovery_checked_before_weak_ev_return(...):
    """The weak-EV ECON BAD branch calls the actual recovery probe check before returning reject."""

def test_v10_13u19c_recovery_allowed_converts_weak_ev_reject_to_controlled_take(...):
    """If existing recovery helper says allowed, weak-EV ECON BAD returns controlled TAKE, not reject."""

def test_v10_13u19c_negative_ev_still_rejects(...):
    """EV <= 0 is never converted to recovery/deadlock probe."""

def test_v10_13u19c_no_global_threshold_change(...):
    """Constants for ECON_BAD entry/recovery/deadlock thresholds remain unchanged."""
```

Use monkeypatching to avoid live Firebase/network access.

### 5. Validation commands

Run locally/server-side:

```bash
cd /opt/cryptomaster
source venv/bin/activate

python -m py_compile src/services/realtime_decision_engine.py
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u19c or v10_13u19 or v10_13u18" -v
git diff --check
git status --short
```

Commit:

```bash
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+19c: wire recovery probe before ECON BAD weak-EV return"
git push origin main
```

### 6. Production validation

After deploy/restart:

```bash
sudo journalctl -u cryptomaster --since "20 minutes ago" --no-pager   | grep -E "RUNTIME_VERSION|ECON_BAD_ENTRY_RETURN_TRACE|ECON_BAD_READY_BUT_REJECTED|ECON_BAD_RECOVERY_TRACE|ECON_BAD_RECOVERY_PROBE|ECON_BAD_DEADLOCK_PROBE|REJECT_ECON_BAD_ENTRY|Traceback|EXIT_INTEGRITY"
```

Expected outcomes:

Healthy allowed probe:

```text
[ECON_BAD_ENTRY_RETURN_TRACE] ... actual_recovery_checked=True actual_recovery_allowed=True actual_recovery_reason=recovery_probe_allowed final_decision=TAKE
[ECON_BAD_RECOVERY_PROBE] ...
```

Healthy rejected with clear reason:

```text
[ECON_BAD_ENTRY_RETURN_TRACE] ... actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=<exact_reason> final_decision=REJECT_ECON_BAD_ENTRY
```

Bug still present:

```text
[ECON_BAD_READY_BUT_REJECTED] ... snapshot_probe_ready=True snapshot_probe_block=none ... final_decision=REJECT_ECON_BAD_ENTRY
```

No acceptable result:

```text
decision=REJECT_ECON_BAD_ENTRY weak_ev
```

without nearby:

```text
[ECON_BAD_ENTRY_RETURN_TRACE]
```

That means the real production return path is still not instrumented.

## Acceptance Criteria

- `RUNTIME_VERSION` shows new commit.
- No `Traceback`.
- Every `REJECT_ECON_BAD_ENTRY weak_ev` has a nearby `[ECON_BAD_ENTRY_RETURN_TRACE]`.
- If `probe_ready=True probe_block=none` and reject still occurs, `[ECON_BAD_READY_BUT_REJECTED]` appears with exact blocker reason.
- If actual recovery probe is allowed, a controlled `TAKE` occurs through existing recovery/deadlock metadata and size multiplier.
- Negative EV remains blocked.
- No Firebase write/read increase.
- No TP/SL/exit logic changes.

## Rollback

If anything behaves unexpectedly:

```bash
git revert HEAD
git push origin main
sudo systemctl restart cryptomaster
```

Or disable only deadlock probe if that is the issue:

```python
ECON_BAD_DEADLOCK_PROBE_ENABLED = False
```
