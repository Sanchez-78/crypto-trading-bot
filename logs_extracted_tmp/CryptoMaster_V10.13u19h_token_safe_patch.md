# CryptoMaster V10.13u+19h — Token-Safe Patch Prompt

## Goal
Fix ECON BAD recovery override tracing. Current production logs still show:
`actual_recovery_checked=False actual_recovery_reason=not_overridable`

Root cause: resolver receives decorated reasons like:
`weak_ev (ev=0.0300<0.045)`
but checks only exact strings:
`weak_ev`, `weak_score`.

So the resolver returns `not_overridable` before evaluating recovery/deadlock logic.

## Scope
File:
`src/services/realtime_decision_engine.py`

Patch only:
- reason normalization
- resolver metric extraction / ctx hydration
- tests

Do NOT change:
- EV hard floor
- ECON BAD entry floor `0.045`
- recovery probe floor `0.038`
- deadlock band `0.0370–0.0380`
- TP/SL/exit logic
- Firebase reads/writes
- position sizing except existing probe multipliers

## Required Fix

### 1. Normalize entry_reason inside `_resolve_econ_bad_recovery_override_for_signal`

Find the block similar to:

```python
if entry_reason not in ("weak_ev", "weak_score"):
    return {
        "checked": False,
        "allowed": False,
        "reason": "not_overridable",
        "kind": "none",
        "size_mult": None,
        "meta": {},
    }
```

Replace with normalized reason handling:

```python
_entry_reason_raw = str(entry_reason or "").strip().lower()
_entry_reason_base = (
    _entry_reason_raw.split("(", 1)[0]
    .strip()
    .split(" ", 1)[0]
    .strip()
)

_OVERRIDABLE_ECON_BAD_REASONS = {
    "weak_ev",
    "weak_score",
    "weak_p",
    "weak_coh",
    "weak_af",
}

if _entry_reason_base not in _OVERRIDABLE_ECON_BAD_REASONS:
    return {
        "checked": False,
        "allowed": False,
        "reason": f"not_overridable:{_entry_reason_base or 'unknown'}",
        "kind": "none",
        "size_mult": None,
        "meta": {"entry_reason_raw": _entry_reason_raw},
    }
```

### 2. Make metric extraction robust

Inside the same resolver, before recovery checks, use signal + ctx aliases:

```python
def _metric(name: str, *aliases, default=0.0) -> float:
    for src in (signal, ctx):
        if not isinstance(src, dict):
            continue
        for key in (name, *aliases):
            val = src.get(key)
            if val is not None:
                try:
                    return float(val)
                except Exception:
                    pass
    return float(default)

ev = _metric("ev")
score = _metric("score", "_score_adj")
p = _metric("p", "win_prob", "prob")
coh = _metric("coh", "coherence")
af = _metric("af", "auditor_factor")
```

Ensure downstream recovery/deadlock checks receive these values either via `ctx` or by using them directly.

### 3. Hydrate `_probe_ctx` before resolver call

Near the ECON BAD gate where resolver is called, before:

```python
override = _resolve_econ_bad_recovery_override_for_signal(signal, _probe_ctx, _econ_bad_reason)
```

add/update:

```python
_probe_ctx.update({
    "ev": ev,
    "score": _score_adj,
    "_score_adj": _score_adj,
    "p": win_prob,
    "win_prob": win_prob,
    "coh": _coh,
    "coherence": _coh,
    "af": auditor_factor,
    "auditor_factor": auditor_factor,
})
```

### 4. Add tests

Add focused tests to `tests/test_v10_13u_patches.py`.

Minimum required:

```python
def test_v10_13u19h_decorated_weak_ev_reason_is_overridable():
    from src.services.realtime_decision_engine import _resolve_econ_bad_recovery_override_for_signal

    signal = {
        "symbol": "XRPUSDT",
        "ev": 0.0300,
        "score": 0.171,
        "p": 0.5,
        "coh": 0.5,
        "af": 0.595,
    }
    ctx = {"open_positions": 0, "idle_s": 100}

    res = _resolve_econ_bad_recovery_override_for_signal(
        signal,
        ctx,
        "weak_ev (ev=0.0300<0.045)",
    )

    assert res["checked"] is True
    assert res["allowed"] is False
    assert res["reason"] != "not_overridable"
```

Also add:
- decorated `weak_score (score=0.190<0.22)` is checked
- non-overridable reason returns `not_overridable:<base>`
- metric aliases from ctx produce non-zero values in trace/resolver
- no negative EV override
- no threshold constants changed

## Expected Production Log After Patch

Bad current log:
```text
actual_recovery_checked=False actual_recovery_reason=not_overridable
```

Correct log:
```text
actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=below_probe_ev
```

or:
```text
actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=weak_p
actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=weak_coh
actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=weak_af
actual_recovery_checked=True actual_recovery_allowed=False actual_recovery_reason=idle_too_low
```

If allowed:
```text
[ECON_BAD_RECOVERY_PROBE] ...
final_decision=TAKE
```

## Validation Commands

```bash
python -m py_compile src/services/realtime_decision_engine.py
python -m pytest tests/test_v10_13u_patches.py -k "v10_13u19h or v10_13u19" -v
git diff --check
git status --short
```

## Commit

```bash
git add src/services/realtime_decision_engine.py tests/test_v10_13u_patches.py
git commit -m "V10.13u+19h: normalize ECON BAD override reasons"
git push origin main
```

## Deployment Check

```bash
sudo systemctl restart cryptomaster

sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|ECON_BAD_ENTRY_RETURN_TRACE|not_overridable|actual_recovery_checked|actual_recovery_reason|ECON_BAD_RECOVERY_PROBE|Traceback"
```

Pass criteria:
- runtime commit matches new commit
- no Traceback
- weak ECON BAD traces no longer show plain `not_overridable`
- decorated weak reasons show `actual_recovery_checked=True`
- blocked candidates show exact reason
- allowed candidates emit `ECON_BAD_RECOVERY_PROBE`
