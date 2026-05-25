# P1.1AP-H1B/H2 — Reconcile V10.13u Full File After H1

## Current verified state

H1 targeted deterministic subset is green:

```text
19 passed, 154 deselected
```

Broader V10.13u + paper/quarantine suite now shows:

```text
7 failed, 243 passed
```

This means H1 worked, but broader `tests/test_v10_13u_patches.py` still contains remaining H2 issues and a few internal test conflicts/order-state problems.

## Hard rules

Do not change live strategy, TP/SL geometry, paper sampler caps, P1.1AO probe logic, Android snapshot publishing, Firebase contracts, or production order execution.

Do not weaken ECON BAD gates restored by H1.

Do not blindly revert H1 fixes.

Prefer test-isolation fixes where failures are order/state contamination.

## Remaining failures and intended handling

### 1. canonical_rr test conflict

Failing:

```text
test_canonical_rr_handles_zero_sl
```

Conflict:
- H1 test `test_canonical_rr_abs_values` expects signed distances to be handled using absolute values:
  - `tp=0.02, sl=-0.01 -> 2.0`
- Older test expects:
  - `tp=0.02, sl=-0.005 -> 0.0`

These cannot both be true.

Decision:
- Keep H1 behavior: signed TP/SL distances are valid and should use absolute values.
- Invalid SL should mean exactly zero or non-numeric, not negative.
- Update `test_canonical_rr_handles_zero_sl` to remove the negative-SL invalid expectation or change it to a true zero/invalid case.

Expected:
```python
assert canonical_rr(tp_distance=0.02, sl_distance=0.0) == 0.0
assert canonical_rr(tp_distance=0.02, sl_distance=None) == 0.0  # if function supports it
assert canonical_rr(tp_distance=0.02, sl_distance=-0.005) == pytest.approx(4.0)
```

### 2. lm_economic_health / canonical PF — H2 core

Failing:
```text
test_lm_economic_health_uses_canonical_pf
test_economic_health_pf_hard_rule
test_economic_health_profitable_pf_good
```

Intent:
- Expose `learning_monitor.canonical_profit_factor` for patchability, delegating to `src.services.canonical_metrics.canonical_profit_factor`.
- Reconcile `lm_economic_health()` with the current canonical LM source after P1.1AF/P1.1AU.
- Do not blindly make old `learning_event.METRICS` the production source if canonical LM count/state is authoritative.

Safety invariant:
- PF < 1.0 and net profit <= 0 must return BAD, never GOOD, once sample count is sufficient.
- Profitable PF > 1.5 and positive net with sufficient sample count may return GOOD or CAUTION.
- Tiny sample count must remain INSUFFICIENT_DATA.

Implementation path:
- Add module-level wrapper/import:
  ```python
  from src.services.canonical_metrics import canonical_profit_factor as canonical_profit_factor
  ```
  or a wrapper function that delegates.
- Ensure `lm_economic_health()` calls the patchable `learning_monitor.canonical_profit_factor`, not only `canonical_metrics.canonical_profit_factor` through a hidden import.
- For tests that patch `learning_event.METRICS`, either:
  - update tests to patch the current canonical LM state source, or
  - add a compatibility fallback used only when canonical LM count is unavailable and `learning_event.METRICS["trades"]` is clearly sufficient.
- Document the chosen source.

### 3. scratch_guard order/state contamination

Failing in broader run:
```text
test_scratch_guard_holds_negative_net_in_econ_bad
```

But isolated run passed.

Likely cause:
- import/patch order or module-level direct import of `lm_economic_health`
- state contamination from earlier tests

Preferred fix:
- In `smart_exit_engine.py`, ensure scratch guard uses runtime module lookup:
  ```python
  import src.services.learning_monitor as learning_monitor
  health = learning_monitor.lm_economic_health()
  ```
- Avoid direct cached import if tests patch `src.services.learning_monitor.lm_economic_health`.
- Add/adjust test isolation if necessary.

### 4. close_lock stale cleanup order/state contamination

Failing in broader run:
```text
test_close_lock_cleanup_runs_before_duplicate_skip
```

But isolated run passed.

Observed broad-run captured count:
```text
[CLOSE_LOCK_STALE_RELEASE] ... count=3
[CLOSE_FORCE_RECONCILE] ... stale_count=3
[POSITION_CLOSE_STUCK] ... action=reconcile_required
```

Likely cause:
- `_STALE_CLOSE_COUNTS` polluted by previous tests; the test clears `_CLOSING_POSITIONS` but not `_STALE_CLOSE_COUNTS`.

Preferred fix:
- Update the test to clear all close-lock globals:
  ```python
  _CLOSING_POSITIONS.clear()
  _RECENTLY_CLOSED.clear()
  _STALE_CLOSE_COUNTS.clear()
  ```
- Do not weaken production duplicate-close safety.

### 5. duplicate close log throttle boundary conflict

Failing:
```text
test_duplicate_close_logs_throttled
```

Conflict:
- H1 restored `CLOSE_DUP_LOG_INTERVAL_S = 5`.
- H1 target expects last_log updated at `now + 6`.
- Older test attempts at exactly `now + 5` and expects no update.

Resolution:
- Use strict boundary:
  - update only when `(now - last_log) > CLOSE_DUP_LOG_INTERVAL_S`
  - do not update at exactly 5.0s
  - update at 6.0s
- This should satisfy both:
  - no update at +5
  - update at +6

If existing code uses `>=`, change to `>`.

## Required tests

Run these first:

```bash
python -m pytest -q tests/test_v10_13u_patches.py   -k "canonical_rr_handles_zero_sl or canonical_rr_abs_values or lm_economic_health_uses_canonical_pf or economic_health_pf_hard_rule or economic_health_profitable_pf_good or scratch_guard_holds_negative_net_in_econ_bad or close_lock_cleanup_runs_before_duplicate_skip or duplicate_close_logs_throttled or close_skip_duplicate_is_throttled"
```

Then:

```bash
python -m pytest -q tests/test_v10_13u_patches.py
```

Then:

```bash
python -m pytest -q   tests/test_p1_paper_exploration.py   tests/test_paper_mode_p1_1ai.py   tests/test_p11ab_stale_position_quarantine.py   tests/test_v10_13u_patches.py
```

Then server-safe full suite:

```bash
python -m pytest -q   --ignore=VERIFICATION_V10_13X   --ignore=venv   --ignore=server_local_backups   --ignore=data/archive   --ignore=data/research
```

## Acceptance criteria

- H1 target subset remains green.
- ECON BAD safety gates remain green.
- Paper/quarantine tests remain green.
- No P1.1AO probe behavior changes.
- All `tests/test_v10_13u_patches.py` pass, or remaining failures are explicitly documented as obsolete.
- No runtime/local files committed.

## Commit message

If this is mostly test conflict/isolation + LM health compatibility:

```text
P1.1AP-H2: Reconcile V10.13u full-suite compatibility
```

If split:
```text
P1.1AP-H1B: Fix V10.13u test conflicts and close-lock isolation
P1.1AP-H2: Reconcile lm_economic_health with canonical PF
```
