# CLAUDE CODE — P1.1AP-N1 URGENT CORRECTION
## Fix D_NEG contamination + actually restore integrated PAPER learning admissions

## Critical runtime evidence

P1.1AP-N commit is deployed:

```text
e225b78 P1.1AP-N: Integrate adaptive paper learning and real-readiness gate
Files changed:
  A src/services/paper_adaptive_learning.py
  M src/services/paper_trade_executor.py
  A tests/test_paper_adaptive_learning.py
Full suite: 884 passed
```

But runtime proves two critical acceptance failures.

### Failure 1 — D_NEG contaminates the new adaptive/canonical rolling learner

Observed after deploy:

```text
[PAPER_EXIT] ... bucket=D_NEG_EV_CONTROL ... outcome=LOSS net_pnl_pct=-0.1871
[PAPER_LEARNING_SHADOW_SKIP] ... bucket=D_NEG_EV_CONTROL ... reason=d_neg_ev_control_shadow_only
[PAPER_CANONICAL_LEARNING_UPDATE] ... trade_id=paper_47fda421767d ... learning_source=paper_training_sampler outcome=LOSS ... lifetime_n=1 ...

[PAPER_EXIT] ... bucket=D_NEG_EV_CONTROL ... outcome=LOSS net_pnl_pct=-0.1514
[PAPER_LEARNING_SHADOW_SKIP] ... bucket=D_NEG_EV_CONTROL ... reason=d_neg_ev_control_shadow_only
[PAPER_CANONICAL_LEARNING_UPDATE] ... trade_id=paper_933268b6ab15 ... learning_source=paper_training_sampler outcome=LOSS ... lifetime_n=2 ...
```

This violates the non-negotiable invariant:

```text
D_NEG_EV_CONTROL is diagnostic/control-only and must never mutate canonical/rolling/adaptive learning metrics.
```

The new adaptive state is already contaminated by at least 2 D_NEG LOSS records.

### Failure 2 — No evidence that P1.1AP-N restored paper admissions

The source diff shows only:

```text
src/services/paper_adaptive_learning.py
src/services/paper_trade_executor.py
tests/test_paper_adaptive_learning.py
```

Search output finds:

```text
paper_trade_executor.py → learner.record_close(trade_data)
```

but no production source hit for:

```text
[PAPER_LEARNING_ENTRY]
paper_adaptive_recovery
historical_health=BAD admission_reason=paper_learning_must_continue
```

Only test references contain `learning_source="paper_adaptive_recovery"`.

Therefore N currently appears to attach a learner to closes that already occur, but it did **not** implement the required admission path that lets valid positive PAPER candidates pass old `ECON_BAD`/starvation blocking. In production the only observed closes are D_NEG controls — the exact rows that must be excluded.

## Operator intent

The bot is PAPER/training only and must keep running and learn through one integrated canonical workflow.

Do not:
- create branches;
- restore shadow/E-lane concepts;
- run Firebase probes;
- stop the project direction;
- modify Android/Firebase contracts;
- let D_NEG train the learner.

Implement one minimal corrective commit on top of `e225b78` that makes the original integrated design real:

```text
valid positive paper candidate blocked only by old BAD/starvation
→ enters same canonical PAPER learning stream
→ close updates lifetime/rolling adaptive metrics exactly once
→ metrics influence next paper admission

D_NEG/control/quarantine invalid rows
→ never update rolling/adaptive learner
```

Because `main` auto-deploys, do edits + tests first. Push only after every required acceptance check below passes.

---

# Phase 0 — Confirm current source wiring and contaminated state

Run:

```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git status --short
git log --oneline -8
git --no-pager show --stat --oneline e225b78

grep -R "paper_adaptive_learning\|record_close\|PAPER_CANONICAL_LEARNING_UPDATE\|PAPER_LEARNING_ENTRY\|paper_adaptive_recovery\|PAPER_POLICY_ADAPTATION\|REAL_READINESS_CHECK" -n src/services tests | head -400

grep -R "_safe_learning_update_for_paper_trade\|_is_d_neg_control_trade\|D_NEG_EV_CONTROL\|PAPER_LEARNING_SHADOW_SKIP\|quarantined" -n src/services tests | head -500

grep -R "REJECT_ECON_BAD_ENTRY\|ECON_BAD\|cost_edge_too_low\|paper_train\|C_WEAK_EV_TRAIN\|B_RECOVERY_READY\|training_sampler" -n src/services tests | head -700

ls -lh server_local_backups/paper_adaptive_learning_state.json 2>/dev/null || true
sed -n '1,240p' server_local_backups/paper_adaptive_learning_state.json 2>/dev/null || true
```

Before editing, report in work notes:

```text
A. Exact call location that invokes adaptive learner for D_NEG after PAPER_LEARNING_SHADOW_SKIP.
B. Why existing tests failed to catch this (missing D_NEG end-to-end exclusion assertion or wrong mock scope).
C. Exact current paper admission path and whether e225b78 altered it.
D. Exact gate(s) still rejecting positive learning candidates.
E. State file contents and whether its only new rows are the two D_NEG trades shown above.
```

---

# Fix 1 — Exclude all non-learning rows before adaptive `record_close()`

The adaptive learner hook must obey the same eligibility contract as the existing canonical learner.

Implement one authoritative predicate, placed where both canonical update and adaptive rolling update can reuse it, such as:

```python
_is_eligible_canonical_paper_learning_trade(pos, pnl_data, closed_trade) -> tuple[bool, str]
```

It must return false for at least:

```text
D_NEG_EV_CONTROL from any of:
  training_bucket
  explore_bucket
  bucket
  nested metadata/extra/canon fields already used in I/I2 detection

quarantined=True
shadow_only=True / learning_shadow_skip=True
stale quarantined records
TIMEOUT_NO_PRICE / invalid-price outcomes already excluded by existing learning contract
```

For D_NEG, the existing behavior must remain:

```text
[PAPER_EXIT]
[PAPER_TRAIN_QUALITY_EXIT]
[PAPER_LEARNING_SHADOW_SKIP] with real trade_id
bucket diagnostics allowed
NO legacy/canonical LEARNING_UPDATE
NO LM_STATE_AFTER_UPDATE
NO PAPER_CANONICAL_LEARNING_UPDATE
NO paper_adaptive_learning.record_close()
NO rolling/lifetime/policy/readiness mutation
```

Add a clear optional no-mutation debug log only if useful and non-spammy:

```text
[PAPER_ADAPTIVE_LEARNING_SKIP] trade_id=... bucket=D_NEG_EV_CONTROL reason=control_shadow_excluded
```

Do not call it a learning update.

## Mandatory tests for Fix 1

Add direct production-path tests:

1. Close a `D_NEG_EV_CONTROL` paper position through the same close function used in runtime.
   Assert:
   ```text
   PAPER_LEARNING_SHADOW_SKIP emitted
   paper_adaptive_learning.record_close NOT called
   PAPER_CANONICAL_LEARNING_UPDATE absent
   adaptive learner lifetime/rolling counts unchanged
   policy unchanged
   readiness unchanged
   ```

2. Repeat D_NEG recognition using all supported bucket fields:
   ```text
   bucket
   training_bucket
   explore_bucket
   any downstream shadow marker propagated by I/I2
   ```

3. Quarantined/stale closes do not call adaptive learner.

4. Normal eligible canonical PAPER close still calls `record_close()` once exactly.

Do not weaken or delete the existing I/I2 tests.

---

# Fix 2 — Wire the missing PAPER admission path

The deployed N cannot succeed if it only records closes but never admits new useful paper learning trades.

Implement in the existing paper candidate routing/admission path — not in a parallel bucket system.

## Admission requirement

In PAPER/training mode only:

```text
If a candidate is structurally valid and has EV > 0, but is rejected only because historical economic health is BAD / post-bootstrap training-starvation gating, it may enter the EXISTING canonical paper learning stream with:

learning_source = "paper_adaptive_recovery"
admission_reason = "paper_learning_must_continue"
historical_health = "BAD"
```

Required structural validity:

```text
symbol present
side BUY/SELL
valid current/entry price
EV > 0
original_decision/reject_reason recorded
regime/score preserved if present
expected_move_pct/expected_move_src/cost_edge_ok preserved
fee/slippage cost model preserved
```

Do not admit:

```text
negative/zero EV candidates — D_NEG continues to own diagnostic control behavior
NO_CANDIDATE_PATTERN
no_side
missing/invalid price
quarantined/stale data
candidates already accepted through normal B/C/current canonical paper path
```

## Cost-edge in PAPER learning

A positive candidate rejected for `cost_edge_too_low` may be sampled only through this canonical paper-learning continuation path and only under existing/new caps, because the bot must learn post-cost failure and then downweight it.

This does not make cost-edge irrelevant; every admitted trade must store/log:

```text
cost_edge_ok
expected_move_pct
expected_move_src
required_move_pct
fee_drag / slippage / net result
```

## Use the same canonical stream, not a new bucket truth

Do not add:

```text
N_ACTIVE_PAPER_LEARN bucket as a separate metrics truth
E-shadow
parallel learner
```

It is acceptable to retain existing training bucket names and add metadata:

```text
learning_source=paper_adaptive_recovery
```

The same close path must update the same adaptive learner.

## Caps

Implement/reuse explicit caps for adaptive recovery admissions:

```text
PAPER_LEARN_MAX_OPEN_GLOBAL = 3
PAPER_LEARN_MAX_OPEN_PER_SYMBOL = 1
PAPER_LEARN_MAX_ENTRIES_PER_HOUR = 12
PAPER_LEARN_MAX_ENTRIES_PER_DAY = 100
```

Normal accepted paper route has priority and must not be blocked merely because adaptive recovery used its own cap accounting.

## Required admission logs

```text
[PAPER_LEARNING_ENTRY]
trade_id=...
learning_source=paper_adaptive_recovery
symbol=... side=... regime=... ev=... score=...
original_decision=... reject_reason=...
expected_move_pct=... expected_move_src=... cost_edge_ok=...
historical_health=BAD admission_reason=paper_learning_must_continue
```

When blocked by controlled caps/invalidity:

```text
[PAPER_LEARNING_ENTRY_BLOCKED]
reason=max_open_global|max_open_symbol|max_entries_hour|max_entries_day|invalid_candidate|negative_ev
```

## Mandatory tests for Fix 2

5. `historical health=BAD` + valid positive rejected paper candidate causes actual entry through production routing and emits `PAPER_LEARNING_ENTRY`.

6. Same candidate with `EV<=0` does not enter canonical/adaptive learner.

7. Same candidate with no side or invalid price is blocked.

8. Existing normal B/C accepted route retains priority and is not rerouted by adaptive recovery.

9. Positive cost-edge-rejected paper candidate is admitted only under controlled paper learning mode and preserves cost metadata.

10. Live/real mode cannot use the adaptive paper continuation admission.

11. Caps apply as required.

12. An admitted `learning_source=paper_adaptive_recovery` trade is closed through production close path and:
    ```text
    calls adaptive learner exactly once
    emits PAPER_CANONICAL_LEARNING_UPDATE
    updates rolling/lifetime metrics
    retains cost/MFE/MAE fields
    ```

---

# Fix 3 — Scrub only contaminated new adaptive state, safely

The runtime evidence proves the newly added adaptive state has at least two contaminated D_NEG LOSS records:

```text
paper_47fda421767d ETHUSDT D_NEG LOSS -0.1871
paper_933268b6ab15 BTCUSDT D_NEG LOSS -0.1514
```

Do not delete historical canonical metrics.

After code is fixed and before/after controlled deployment, handle only the new `paper_adaptive_learning_state.json` state:

1. Inspect its structure and record backup path.
2. If and only if the adaptive state contains solely D_NEG contamination or identifies these rows cleanly, create a timestamped backup and reset/remove only D_NEG-derived adaptive entries/recomputed rolling aggregates.
3. If valid non-D_NEG adaptive recovery closes are already present, do not blind-reset; implement a one-time safe rebuild/filter that excludes D_NEG and preserves eligible rows.
4. Never commit runtime state files.

Required maintenance log or operator output:

```text
PAPER_ADAPTIVE_STATE_RECONCILED removed_d_neg=N preserved_eligible=N backup=...
```

Add unit tests for filtering/rebuild if state reconciliation code is introduced.

---

# Readiness / adaptation remains required

Preserve and validate the N module functionality:

```text
rolling20 / rolling50 / rolling100 metrics
segment policy adaptation
REAL_READINESS_CHECK
REAL_READY requires operator unlock before any real action
```

But readiness and policy state must be calculated from eligible canonical paper learning closes only — never D_NEG/shadow/quarantine.

Additional tests:

13. `REAL_READY` cannot be reached using D_NEG rows.
14. Segment downweight/preference cannot be changed by D_NEG rows.
15. Eligible adaptive-recovery closes can influence policy after sufficient samples.
16. Existing REAL_READY unlock gate remains non-automatic.

---

# Strict scope boundaries

Allowed files only after inspection:

```text
src/services/paper_adaptive_learning.py
src/services/paper_trade_executor.py
src/services/paper_exploration.py and/or src/services/paper_training_sampler.py only if required to implement actual admission
src/services/realtime_decision_engine.py only if that is the existing admission handoff and change is minimal
tests/test_paper_adaptive_learning.py
existing directly-related paper test file(s)
.gitignore only if necessary for new runtime state exclusion
```

Forbidden:

```text
data/research/*
phase2b_firebase_probe.py
src/services/app_metrics_contract.py
src/services/firebase_client.py
Android/Firebase metric contracts
committing runtime state or backups
.env*
venv/
server_local_backups/
restoring P1.1AP-L/L1 E-shadow
```

---

# Required validation

First targeted tests:

```bash
./venv/bin/python -m pytest -q \
  tests/test_paper_adaptive_learning.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_v10_13u_patches.py
```

Then server-safe suite:

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_n1_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_n1_fullsuite.txt || true
tail -30 /tmp/p11ap_n1_fullsuite.txt
```

Baseline at `e225b78`:

```text
884 passed in 3.68s
```

Final must be:

```text
0 failures
0 errors
0 warnings
>=884 passed plus new regression tests
```

## Before commit

```bash
git status --short
git diff --name-status
git diff --stat
grep -R "E_ECON_BAD_NEAR_MISS_SHADOW" -n src/services tests || true
```

Do not include dirty runtime/research files.

## Single corrective commit and deploy

After clean tests and clean scope, create one commit/push to `main`:

```bash
git add <only allowed source/test files>
git commit -m "P1.1AP-N1: Exclude D_NEG and restore adaptive paper admissions"
git push origin main
```

## Post-deploy acceptance logs

Immediately after restart:

```bash
sudo journalctl -u cryptomaster --since "5 minutes ago" --no-pager -o cat | grep -E \
"Traceback|UnboundLocalError|PAPER_LEARNING_STATE_RESTORE|LEARNING_LIFECYCLE_STATE|PAPER_LEARNING_ENTRY|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_POLICY_ADAPTATION|REAL_READINESS_CHECK|REAL_READY|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL"
```

Continuous validation:

```bash
sudo journalctl -u cryptomaster -f -o cat | grep --line-buffered -E \
"PAPER_LEARNING_ENTRY|PAPER_EXIT|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_POLICY_ADAPTATION|REAL_READINESS_CHECK|REAL_READY|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL|PAPER_LEARNING_ANOMALY|Traceback|UnboundLocalError"
```

Acceptance requires:

```text
A. New D_NEG close:
   PAPER_LEARNING_SHADOW_SKIP appears;
   NO PAPER_CANONICAL_LEARNING_UPDATE for same trade_id.

B. New valid positive adaptive paper admission:
   PAPER_LEARNING_ENTRY learning_source=paper_adaptive_recovery appears.

C. Its close:
   PAPER_CANONICAL_LEARNING_UPDATE appears once and rolling metrics move.

D. No crash and no automatic real execution.
```

---

# Report back

Return:

```text
ROOT CAUSE OF D_NEG LEAK:
ROOT CAUSE OF MISSING PAPER ADMISSIONS:
STATE RECONCILIATION RESULT:
FILES CHANGED:
TEST RESULTS:
COMMIT HASH:
POST-DEPLOY D_NEG EXCLUSION EVIDENCE:
POST-DEPLOY NEW PAPER ENTRY EVIDENCE:
POST-DEPLOY METRIC UPDATE EVIDENCE:
