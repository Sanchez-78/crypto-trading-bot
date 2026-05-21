# P1.1AP-G — Full Test Suite Stabilization + Safety Regression Triage

## Context

Current production/server HEAD:

- `c0df167 P1.1AP-F: Deployment verification — snapshot publishing live and working`
- Earlier relevant commits:
  - `8aa10ff P1.1AP-E: Suppress LEARNING_UPDATE for quarantined positions`
  - `8a839f5 P1.1AP-D: Refine stale position quarantine thresholds`
  - `5c2de10 P1.1AP-C: Move stale position quarantine before quality/econ/learning logs`

The Windows-only test collection failure was bypassed with:

```bash
python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

Result:

```text
16 failed, 818 passed, 6 warnings
```

This is not a crash-loop or total suite failure. It is a focused set of regressions/stale invariants.

## Hard Rules

Do **not** change live/real trading behavior unless a failing test proves a safety invariant is currently broken.

Do **not** retune strategy, TP/SL, RDE thresholds, sampler logic, P1.1AO probe logic, Android snapshot publishing, Firebase write contracts, or learning economics beyond the failing invariants.

Do **not** “fix” by deleting tests unless a test is clearly obsolete and you document why.

Prefer minimal compatibility shims and defensive normalization over broad rewrites.

Runtime/local files must not be committed:

- `data/paper_open_positions.json`
- `.env*`
- `venv/`
- `server_local_backups/`
- `data/archive/`
- `data/research/`
- temporary shell artifacts

## Failure Groups

### Group A — Current Paper State / Timeout Regressions

These are likely real current-code issues and should be fixed first.

#### A1. Robust loader drops legacy list positions missing `size_usd`

Failing test:

```text
tests/test_p1_paper_exploration.py::TestRobustStateLoader::test_list_with_missing_keys_generates_fallback_keys
```

Observed log:

```text
[PAPER_STALE_RECONCILE_ERROR] trade_id=legacy_0_XRPUSDT_1700000000 err='size_usd'
```

Expected behavior:

- Legacy list entries without `trade_id` / `id` should get fallback keys.
- Missing optional fields such as `size_usd` must not cause the position to be discarded.
- Normalize defaults before stale reconcile logic touches the position.

Implement:

- In `src/services/paper_trade_executor.py`, ensure `_load_paper_state()` / normalization path provides safe defaults:
  - `size_usd` from `final_size_usd` or fallback paper default
  - `timestamp` from `entry_ts` / `ts` / `time`
  - `entry_price` from `entry` / `price` if needed
  - `side` from `action` if needed
  - `bucket` / `explore_bucket` compatibility
- Never let stale reconcile raise KeyError on legacy fields.

#### A2. `update_paper_positions()` does not close C_WEAK_EV at `max_hold_s`

Failing test:

```text
tests/test_p1_paper_exploration.py::TestMaxHoldWindow::test_c_weak_ev_closes_near_max_hold_s
```

Expected behavior:

- C_WEAK_EV position with `max_hold_s=600` stays open at 599s.
- It closes at 601s.
- This must work through `update_paper_positions({"XRPUSDT": price}, now)`.

Implement:

- Ensure timeout/max-hold checks are run from `update_paper_positions()` for all paper positions, not only from external timeout scanner.
- Use the per-position/effective `max_hold_s` value.
- Preserve existing behavior for `C_WEAK_EV_TRAIN` and P1.1AO `C_NEG_EV_PROBE`.
- Do not alter live/real position logic.

#### A3. `TIMEOUT_NO_PRICE` emits quality/econ logs but not `[PAPER_EXIT]`

Failing test:

```text
tests/test_paper_mode_p1_1ai.py::TestP1_1AI_QualityExit::test_quality_exit_emitted_for_timeout_close
```

Observed:

- `[PAPER_TIMEOUT_DUE]`
- `[PAPER_TIMEOUT_NO_PRICE]`
- `[PAPER_TRAIN_QUALITY_EXIT]`
- `[PAPER_TRAIN_ECON_ATTRIB]`
- `[PAPER_STATE_SAVE]`
- missing `[PAPER_EXIT]`

Expected behavior:

- Non-quarantined timeout close paths should emit `[PAPER_EXIT]` for observability.
- `TIMEOUT_NO_PRICE` may still skip `LEARNING_UPDATE` if there is no valid price.
- Must not reintroduce P1.1AP-E quarantine leak:
  - quarantined stale positions must still emit only `[PAPER_POSITION_QUARANTINED]`
  - no quality/econ/learning/Firebase write for quarantined positions

Implement:

- Emit `[PAPER_EXIT] reason=TIMEOUT_NO_PRICE` when closing/removing the position.
- Keep `LEARNING_UPDATE` skipped for no-price path unless current design explicitly supports flat/no-price learning.
- Verify no quarantine path logs `[PAPER_EXIT]`.

### Group B — V10.13u Compatibility / Safety Invariants

These failures are mixed: some may be stale tests, some are real safety issues. Triage before patching.

#### B1. `canonical_rr()` should use absolute TP/SL distances

Failing:

```text
test_canonical_rr_abs_values
```

Expected:

```python
canonical_rr(tp_distance=0.02, sl_distance=-0.01) == 2.0
canonical_rr(tp_distance=-0.02, sl_distance=0.01) == 2.0
```

Implement if still valid:

- `rr = abs(tp_distance) / abs(sl_distance)`
- if `sl_distance == 0` or invalid -> safe fallback 0.0
- no threshold tuning.

#### B2. `learning_monitor.lm_economic_health()` canonical PF compatibility

Failing:

```text
test_lm_economic_health_uses_canonical_pf
test_economic_health_pf_hard_rule
test_economic_health_profitable_pf_good
```

Observed:

- `src.services.learning_monitor` does not expose `canonical_profit_factor`
- mocked `learning_event.METRICS` with 100 trades still returns `INSUFFICIENT_DATA`

Triage:

- Determine canonical current source of trade count / PF after P1.1AF/P1.1AU canonical LM-count fixes.
- Do not revert to stale `learning_event.METRICS` if current canonical LM state is the source of truth.
- If tests are obsolete, update tests to target canonical source.
- If runtime `lm_economic_health()` no longer uses canonical PF at all, restore canonical PF as an import or wrapper.

Safety invariant:

- PF < 1.0 and net profit <= 0 must not be reported as GOOD.
- Good status should require enough canonical sample count plus profitable PF/net trend.
- Avoid returning GOOD on tiny samples.

#### B3. `version_info.get_git_commit()` env truncation mismatch

Failing:

```text
test_get_git_commit_from_env
```

Current behavior returns `abc1234567`; test expects `abc1234` while comment says “Truncated to 12 chars”.

Triage:

- Decide official format:
  - prefer 7-char short git hash for logs if existing runtime logs use short hash
  - or update stale test if full env SHA is now intentional
- This is low priority and should not block runtime patch unless easy.

#### B4. `compute_effective_maturity()` / `get_canonical_state` compatibility

Failing:

```text
test_maturity_handles_mixed_state
```

Observed:

```text
realtime_decision_engine has no attribute get_canonical_state
```

Triage:

- If `get_canonical_state` was replaced by canonical LM count/state helpers, update test.
- If downstream code still expects RDE-level helper, add thin compatibility wrapper that delegates to current canonical source.
- Avoid duplicate state sources.

#### B5. Scratch guard should block negative-net scratch in ECON BAD

Failing:

```text
test_scratch_guard_holds_negative_net_in_econ_bad
```

Likely issue:

- Test patches `src.services.learning_monitor.lm_economic_health`, but `SmartExitEngine` may use a stale direct import.

Implement if valid:

- Use module-level lookup inside `_check_scratch()`:
  - `import src.services.learning_monitor as learning_monitor`
  - call `learning_monitor.lm_economic_health()` at runtime
- If ECON BAD and estimated net-if-closed is negative, block scratch.
- Do not change TP/SL/trailing behavior.

#### B6. Close lock duplicate throttling/stale cleanup

Failing:

```text
test_close_skip_duplicate_is_throttled
test_close_lock_cleanup_runs_before_duplicate_skip
```

Triage:

- Validate current close-lock design after recent stale recovery changes.
- If duplicate skip logging should update `last_log` after 5s, restore that.
- For stale lock older than TTL:
  - stale cleanup should run before duplicate skip
  - if no active position reconciliation requires holding the lock, allow fresh acquisition
- Do not loosen duplicate-close protection for real orders.

#### B7. ECON BAD entry gates allow weak signals

Failing:

```text
test_v10_13u16_econ_bad_blocks_low_ev
test_v10_13u16_econ_bad_blocks_low_af
test_v10_13u16_econ_bad_blocks_forced_explore_weak
test_v10_13u17_econ_bad_still_blocks_normal_weak
```

This is safety-relevant.

Expected safety invariant:

- Under ECON BAD:
  - normal TAKE with `ev < 0.045` should be blocked unless an explicit recovery/probe path applies
  - normal TAKE with `auditor_factor < 0.70` should be blocked
  - forced exploration with weak EV should be blocked
  - very weak normal signals should stay blocked
- P1.1AO `C_NEG_EV_PROBE` must remain isolated and capped.
- Do not accidentally block the explicit cold-start probe path, but do block ordinary weak entries under ECON BAD.

Implement:

- Inspect `_econ_bad_entry_quality_gate()` and `_econ_bad_forced_explore_gate()`.
- Restore blocking behavior for normal/forced weak signals.
- Add explicit bypass only for documented cold-start probe path if needed, with bucket/source checks.
- Add/keep tests proving:
  - weak normal ECON BAD blocked
  - forced weak ECON BAD blocked
  - P1.1AO probe still accepted only through probe route and caps

## Required Test Commands

Run targeted first:

```bash
python -m pytest -q \
  tests/test_p1_paper_exploration.py::TestRobustStateLoader::test_list_with_missing_keys_generates_fallback_keys \
  tests/test_p1_paper_exploration.py::TestMaxHoldWindow::test_c_weak_ev_closes_near_max_hold_s \
  tests/test_paper_mode_p1_1ai.py::TestP1_1AI_QualityExit::test_quality_exit_emitted_for_timeout_close
```

Then V10.13u failing subset:

```bash
python -m pytest -q tests/test_v10_13u_patches.py \
  -k "canonical_rr_abs_values or lm_economic_health_uses_canonical_pf or get_git_commit_from_env or maturity_handles_mixed_state or economic_health_pf_hard_rule or economic_health_profitable_pf_good or scratch_guard_holds_negative_net_in_econ_bad or close_skip_duplicate_is_throttled or close_lock_cleanup_runs_before_duplicate_skip or v10_13u16 or v10_13u17"
```

Then broader related tests:

```bash
python -m pytest -q \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_p1_1ab_stale_quarantine.py \
  tests/test_v10_13u_patches.py
```

Then server-safe full suite:

```bash
python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

## Acceptance Criteria

- Targeted Group A tests pass.
- Safety-relevant ECON BAD tests pass or are consciously updated with documented rationale.
- No quarantine regression:
  - stale/corrupt positions still emit only `[PAPER_POSITION_QUARANTINED]`
  - no `[PAPER_EXIT]`, no `[PAPER_TRAIN_QUALITY_EXIT]`, no `[PAPER_TRAIN_ECON_ATTRIB]`, no `LEARNING_UPDATE`, no Firebase write for quarantined positions
- No live/real behavior changes except safety gate restoration if proven.
- Full server-safe suite improves from `16 failed, 818 passed` to either:
  - all pass, or
  - only documented obsolete legacy tests remain, with explicit rationale.
- Commit message:
  - `P1.1AP-G: Stabilize server test suite and restore paper/econ safety invariants`

## Post-Deploy Validation

After commit/push/pull on server:

```bash
git log --oneline -5
git status --short

sudo systemctl restart cryptomaster
sleep 120

sudo systemctl status cryptomaster --no-pager

sudo journalctl -u cryptomaster --since "15 min ago" --no-pager | grep -E \
"Started cryptomaster|Firebase initialized|Model state restored|PAPER_TRAIN_ENTRY|PAPER_EXIT|PAPER_POSITION_QUARANTINED|LEARNING_UPDATE|PAPER_TRAIN_STARVATION_STATE|PAPER_NEG_EV_PROBE_ACCEPTED|ANDROID|SNAPSHOT|dashboard_snapshot|Traceback|UnboundLocalError"
```

Production must show:

- no `Traceback`
- no `UnboundLocalError`
- Firebase/model restore OK
- normal paper exits still learn
- stale/quarantined positions do not leak into learning
- P1.1AO probe behavior unchanged
- P1.1AP-F snapshot publishing still active
