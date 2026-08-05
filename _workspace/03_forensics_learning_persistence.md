# Forensics: qualification_n discrepancy — ROOT CAUSE CONFIRMED (static code trace, deterministic)

## Finding: `firebase_learning_persistence.py` silently drops fields on every save/load

`paper_adaptive_learning.py._save_state()` (line 361-394) builds a comprehensive
state dict — `lifetime_metrics`, `learning_controls`, `regime_tp_strategy`,
`rolling_windows`, `segment_weights`, `qualification_schema_version`,
`qualification_started_at`, `qualification_n`, `qualification_window`,
`operator_unlock`, `paper_admission_controls`, `recorded_trade_ids` — and
passes it to `save_learning(data)`, imported from
`src.services.firebase_learning_persistence` (`paper_adaptive_learning.py:22`).

`save_learning` → `FirebaseLearningPersistence.save_learning_state()`
(`firebase_learning_persistence.py:76-111`) **reconstructs a NEW dict keeping
only 3 fields**:
```python
data = {
    "timestamp": ...,
    "schema_version": 1,
    "lifetime_metrics": learning_obj.get("lifetime_metrics", {}),
    "regime_tp_strategy": learning_obj.get("regime_tp_strategy", {}),
    "rolling_windows": learning_obj.get("rolling_windows", {}),
}
```
Everything else — **`segment_weights`, `qualification_window`,
`qualification_n`, `qualification_started_at`, `operator_unlock`,
`paper_admission_controls`, `recorded_trade_ids`** — is silently discarded.
This truncated dict is what's written to this module's own local file
(`server_local_backups/learning_state_phase1.json` — note: a **different
file** from `paper_adaptive_learning.py`'s own
`server_local_backups/paper_adaptive_learning_state.json`) and queued for
Firebase sync.

`load_learning_state()` (line 112-140) returns exactly that truncated dict
unchanged (no further filtering on load — the loss happens entirely at save
time).

Back in `paper_adaptive_learning.py._load_state()` (line 246-263): **Firebase
is tried FIRST** (`load_learning()`), and only falls back to this class's own
local JSON (`self._state_file`) `if not data:`. Since Firebase-path load
succeeds (returns a non-None, non-stale, >=20-trade dict — confirmed live,
see below) but that dict never had the qualification/admission-control keys,
`data.get("qualification_n", 0)` → `0`, `data.get("qualification_window",
[])` → `[]`. **Same mechanism silently resets `segment_weights` to `{}` and
`paper_admission_controls` (cooldowns/quarantines) to defaults on every
process restart** — not just qualification_n.

## Confirmed deterministic, not conditional on network/quota flakiness

This is **not** a race condition or an occasional Firebase-quota-exhaustion
symptom (unlike documented past incidents) — every single call to
`save_learning_state()` drops these fields, unconditionally, by construction.
It manifests specifically **on process restart** (the only time
`_load_state()` runs); mid-process, everything is in-memory and correct.

## Verified live (read-only, 2026-08-05)

- Direct read of `paper_adaptive_learning.py`'s own local JSON: `qualification_n: 100`.
- Constructing `PaperAdaptiveLearning()` fresh (replicating what happens on
  every restart): `qualification_n: 0`, plus a `[VALIDATE_TP] ... n=0`
  validation-failure log — consistent with the Firebase-path
  `regime_tp_strategy` data also being from an older/less-evolved snapshot
  than the same class's own local JSON copy of the same field.

## Why this matters beyond the qualification counter

`segment_weights` and `paper_admission_controls` are the actual mechanism of
"automatic strategy adjustment" this session was asked to increase — segment
up/down-weighting and cooldown/quarantine state. If they reset to neutral on
every restart, previously-learned "avoid this losing segment" decisions are
silently undone each time the service restarts (systemd `Restart=always`,
gated deploys, crashes) — a plausible structural reason automatic adjustment
doesn't durably compound over time, independent of and prior to any inherent
question about whether more/faster learning is needed.

## Scope check before patching

- Only one caller of `firebase_learning_persistence` in the whole repo:
  `paper_adaptive_learning.py` (grep-verified, no test imports it directly).
- Existing durability test (`tests/test_p11ap_o2_cooldown_durability.py`)
  constructs `PaperAdaptiveLearning(state_file=<temp>)` and asserts against
  that class's own local JSON directly — it does **not** exercise the
  Firebase-bridge round-trip, so it does not currently catch this bug and
  will not be broken by fixing it. A new regression test is needed to cover
  the actual gap.

## Fix (proposed, not yet applied)

`save_learning_state()`: persist the **full** `learning_obj` given by the
caller (`{**learning_obj, "timestamp": ..., "schema_version": ...}`) instead
of reconstructing a 3-field allowlist. `load_learning_state()` needs no
change — it already returns whatever was saved. Single-function fix,
decouples this persistence module from needing to know every field name the
caller uses (better invariant: whatever you save is what you get back).
