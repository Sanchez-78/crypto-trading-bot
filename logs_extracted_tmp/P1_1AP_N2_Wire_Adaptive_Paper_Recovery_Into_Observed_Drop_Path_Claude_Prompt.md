# Claude Code — P1.1AP-N2: Wire PAPER Adaptive Recovery Into the Real Drop Path

## Objective

Fix the final remaining blocker in the **one integrated PAPER learning workflow**.

P1.1AP-N1 successfully stopped `D_NEG_EV_CONTROL` from contaminating adaptive/canonical learning. However, production proves that `paper_adaptive_recovery` admissions never fire, even when the exact eligible positive PAPER candidates repeatedly occur.

This is a narrow routing/wiring correction only:
- do not create another lane/learner/epoch;
- do not change learning metrics architecture;
- do not change Android/Firebase contracts;
- do not alter real-mode readiness criteria;
- do not restore E-shadow;
- do not tune TP/SL or economic thresholds.

## Confirmed current deployed state

```text
HEAD: 64a9311 P1.1AP-N1: Exclude D_NEG and restore adaptive paper admissions
Full server-safe suite: 893 passed, 0 failures, 0 warnings
Current PID used for runtime evidence: 1319191
```

### N1 success already proven — preserve it

Current-PID D_NEG closes:

```text
paper_a19a1cdb4367 SOLUSDT D_NEG LOSS -0.4225
paper_e6c7c708f577 ETHUSDT D_NEG FLAT +0.0275
```

Both emitted:

```text
[PAPER_LEARNING_SHADOW_SKIP] ... bucket=D_NEG_EV_CONTROL ...
```

Neither emitted:

```text
[PAPER_CANONICAL_LEARNING_UPDATE] ... same trade_id
```

Do not regress this.

## Runtime failure requiring N2

The bot repeatedly sees valid positive candidates under ECON_BAD, but never opens a learning trade.

Observed current-PID sequence, repeated for XRPUSDT/ADAUSDT:

```text
[ECON_BAD_ENTRY_RETURN_TRACE]
symbol=XRPUSDT ev=0.0338 ... pf=0.495 econ_status=BAD
entry_reason=weak_ev (ev=0.0338<0.045)
actual_recovery_checked=True
actual_recovery_allowed=False
actual_recovery_reason=below_deadlock_ev
open_positions=0
final_decision=REJECT_ECON_BAD_ENTRY

[PAPER_EXPLORE_SKIP]
reason=cost_edge_too_low
bucket=C_WEAK_EV
symbol=XRPUSDT
expected_move_pct=0.0004
expected_move_src=atr_abs_price_normalized
required_move_pct=0.2300

[PAPER_TRAIN_SKIP]
reason=cost_edge_too_low
symbol=XRPUSDT
side=SELL
bucket=C_WEAK_EV_TRAIN
source_reject=REJECT_ECON_BAD_ENTRY
```

Additional candidates:

```text
XRPUSDT ev=0.0300, 0.0338, 0.0348
ADAUSDT ev=0.0300
all REJECT_ECON_BAD_ENTRY weak_ev
all positive EV
open_positions=0
```

Periodic proof of starvation:

```text
[ECON_BAD_DIAG_HEARTBEAT] total=72 neg_ev=60 weak_ev=12
best_symbol=XRPUSDT best_ev=0.0348 econ_status=BAD pf=0.495

[PAPER_EXPLORE_SKIP_SUMMARY]
window_s=600 cost_edge_too_low=19 ... entries=0
```

No logs occur for:

```text
[PAPER_LEARNING_ENTRY] learning_source=paper_adaptive_recovery
[PAPER_CANONICAL_LEARNING_UPDATE] for any new eligible recovery trade
```

## Root cause to confirm before edit

N1 added an admission block in `src/services/trade_executor.py` around lines ~1763–1796, but it is not on the actual runtime path that handles:

```text
REJECT_ECON_BAD_ENTRY → PAPER_EXPLORE_SKIP cost_edge_too_low → PAPER_TRAIN_SKIP cost_edge_too_low
```

or it is improperly dependent on the older RDE recovery/deadlock gate:

```text
actual_recovery_allowed=False reason=below_deadlock_ev
```

That older gate must **not** veto integrated PAPER learning continuation. It may still govern its original behavior; N2 must not weaken live/real/RDE semantics.

Before editing, show exact source flow and identify which of these is true:

```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git status --short

nl -ba src/services/trade_executor.py | sed -n '1680,1825p'
nl -ba src/services/paper_exploration.py | sed -n '360,475p'
nl -ba src/services/paper_training_sampler.py | sed -n '410,495p'
nl -ba src/services/realtime_decision_engine.py | sed -n '3850,3910p'

grep -R "paper_adaptive_recovery\|PAPER_LEARNING_ENTRY\|actual_recovery_allowed\|below_deadlock_ev\|cost_edge_too_low\|PAPER_TRAIN_SKIP" -n src/services tests
```

Report the root cause in one sentence before changing code.

## Required behavior

### Same canonical learner; admission only in PAPER mode

For a candidate on the **observed production drop path**:

```text
final_decision/original_decision = REJECT_ECON_BAD_ENTRY
reject reason = weak_ev
EV > 0
side = BUY or SELL
valid symbol and valid current/entry price
mode = paper/paper_train
normal eligible paper route did not already accept it
rejection/drop is due to historical BAD and/or cost_edge_too_low
```

the bot must open a normal canonical PAPER learning position tagged only with metadata:

```text
learning_source=paper_adaptive_recovery
admission_reason=paper_learning_must_continue
historical_health=BAD
cost_edge_ok=False  # when that is the observed gate
expected_move_pct=...
expected_move_src=atr_abs_price_normalized
required_move_pct=...
original_decision=REJECT_ECON_BAD_ENTRY
original_reject_reason=weak_ev
```

This is not a new shadow bucket and not real trading. It is the same integrated PAPER learner collecting evidence that can later downweight fee-dominated candidates.

### Do not require older deadlock/recovery gate approval

For `paper_adaptive_recovery` only:

```text
actual_recovery_allowed=False reason=below_deadlock_ev
```

must not block the admission if all PAPER-learning eligibility rules and caps pass.

Do not change the older gate's behavior for any non-paper-learning path.

### Preserve negative/invalid rejection

Must never admit through adaptive recovery:

```text
REJECT_NEGATIVE_EV / EV <= 0
NO_CANDIDATE_PATTERN
no_side
missing/invalid price
D_NEG_EV_CONTROL
live/real execution path
already accepted normal B/C entry
```

### Preserve and use caps

Use/reuse N1 caps:

```text
max recovery open global = 3
max recovery open per symbol = 1
hour/day caps if already implemented by N/N1
```

If a recovery candidate is blocked by a cap, emit:

```text
[PAPER_LEARNING_ENTRY_BLOCKED] reason=...
```

If accepted, emit:

```text
[PAPER_LEARNING_ENTRY]
trade_id=...
learning_source=paper_adaptive_recovery
admission_reason=paper_learning_must_continue
symbol=... side=... ev=... score=...
original_decision=REJECT_ECON_BAD_ENTRY reject_reason=weak_ev
expected_move_pct=... expected_move_src=... cost_edge_ok=False
```

## Learning close acceptance

A new admitted `paper_adaptive_recovery` position must close through the current production close path and emit exactly once:

```text
[PAPER_EXIT] ... learning_source=paper_adaptive_recovery ...
[PAPER_CANONICAL_LEARNING_UPDATE] ... learning_source=paper_adaptive_recovery ...
rolling20_pf=... rolling20_expectancy=...
```

and may then influence policy through the existing adaptive module.

D_NEG remains:

```text
PAPER_LEARNING_SHADOW_SKIP
no PAPER_CANONICAL_LEARNING_UPDATE
```

## Required tests

Add tests that reproduce the **actual log path**, not merely directly call a helper.

1. `REJECT_ECON_BAD_ENTRY weak_ev`, EV `0.0338`, `cost_edge_too_low`, `open_positions=0`, PAPER mode:
   - reaches production drop/routing chain;
   - opens paper position;
   - emits `PAPER_LEARNING_ENTRY`;
   - stores `learning_source=paper_adaptive_recovery`;
   - preserves expected-move/cost metadata.

2. Same for ADA-like positive EV candidate rejected by cost edge.

3. `actual_recovery_allowed=False`, `actual_recovery_reason=below_deadlock_ev` does **not** veto paper adaptive recovery.

4. EV `<=0` / `REJECT_NEGATIVE_EV` remains rejected from canonical learning.

5. `NO_CANDIDATE_PATTERN` / `no_side` remains rejected.

6. Normal existing accepted B/C route is not duplicated/rerouted.

7. Recovery cap blocks correctly and logs `PAPER_LEARNING_ENTRY_BLOCKED`.

8. End-to-end admission → close:
   - `PAPER_CANONICAL_LEARNING_UPDATE` occurs exactly once;
   - rolling metrics change.

9. End-to-end D_NEG after N2:
   - `PAPER_LEARNING_SHADOW_SKIP`;
   - no adaptive/canonical update;
   - adaptive state unchanged.

10. Existing N/N1, I/I2, J/J2, K regressions remain green.

## Scope

Allowed files only as required by the confirmed runtime path:

```text
src/services/trade_executor.py
src/services/paper_exploration.py and/or src/services/paper_training_sampler.py
src/services/realtime_decision_engine.py only if the production handoff absolutely requires a minimal PAPER-only hook
src/services/paper_trade_executor.py only if close metadata needs minimal propagation
tests/test_paper_adaptive_learning.py
existing directly relevant paper-routing test file
```

Do not change:

```text
src/services/app_metrics_contract.py
src/services/firebase_client.py
data/research/*
phase2b_firebase_probe.py
D_NEG semantics
REAL_READY thresholds/unlock
TP/SL/timeout geometry
cost-edge threshold value
ECON_BAD threshold value
live/real execution behavior
```

## Validation

Run targeted tests:

```bash
./venv/bin/python -m pytest -q \
  tests/test_paper_adaptive_learning.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_v10_13u_patches.py
```

Run server-safe full suite:

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_n2_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_n2_fullsuite.txt || true
tail -30 /tmp/p11ap_n2_fullsuite.txt
```

Current N1 baseline:

```text
893 passed in 3.77s
```

Required N2 result:

```text
0 failures, 0 errors, 0 warnings, >=893 passed plus new tests
```

## Commit/deploy

If and only if root cause is shown, scope is clean, and tests pass:

```bash
git status --short
git diff --name-status
git diff --stat

git add <only allowed source/test files>
git commit -m "P1.1AP-N2: Wire adaptive paper recovery into rejected-candidate flow"
git push origin main
```

## Post-deploy acceptance

Use current new PID after deploy:

```bash
PID=$(systemctl show cryptomaster -p MainPID --value)
echo "CURRENT_PID=$PID"

sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat | grep -E \
"PAPER_LEARNING_ENTRY|paper_adaptive_recovery|PAPER_EXIT|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_POLICY_ADAPTATION|REAL_READINESS_CHECK|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL|Traceback|UnboundLocalError"
```

Acceptance:

```text
1. At least one positive rejected weak-EV/cost-edge candidate emits PAPER_LEARNING_ENTRY learning_source=paper_adaptive_recovery.
2. Its later close emits one PAPER_CANONICAL_LEARNING_UPDATE and rolling metrics change.
3. New D_NEG close emits shadow skip and no canonical adaptive update.
4. No crashes; no automatic real activation.
```

## Return report

```text
ROOT CAUSE OF MISSING ADMISSION:
FILES CHANGED:
HOW THE OBSERVED DROP PATH NOW OPENS PAPER LEARNING:
HOW D_NEG EXCLUSION REMAINS SAFE:
TEST RESULTS:
COMMIT/PUSH:
POST-DEPLOY PAPER_LEARNING_ENTRY EVIDENCE:
POST-DEPLOY LEARNING UPDATE EVIDENCE:
```
