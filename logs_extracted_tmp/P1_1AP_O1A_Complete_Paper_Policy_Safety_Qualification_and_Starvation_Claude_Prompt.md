# CLAUDE CODE — P1.1AP-O1A: Complete PAPER Policy Integration Safety, Qualification Provenance, and Starvation Evidence

## Status / purpose

P1.1AP-O1 is deployed as:

```text
a6ab55f P1.1AP-O1: Apply adaptive rolling policy to PAPER decisions
```

Do **not** revert O1. Runtime proves its main idea works: an EV-positive PAPER recovery candidate now reads adaptive state before opening.

This is a narrow O1 acceptance-completion patch, not a new strategy patch.

Implement only:
1. missing direct regression tests for the already deployed O1 behavior;
2. truthful PAPER adaptive-starvation diagnostics when no EV-positive supply exists;
3. a real qualification provenance mechanism so `REAL_READY` is safely impossible **now**, but not permanently impossible after 100 verified post-integration eligible PAPER closes plus operator unlock;
4. only if required for truthful logs/tests, minimal read-path cleanup.

Do **not** tune strategy, loosen gates, create lanes/branches, admit `EV<=0` to canonical learning, or touch live/real execution behavior.

---

# Confirmed evidence after O1 deploy

## Commit and test baseline

```text
HEAD: a6ab55f P1.1AP-O1: Apply adaptive rolling policy to PAPER decisions
Diff vs N2C:
  src/services/paper_adaptive_learning.py | +161/-10
  src/services/paper_training_sampler.py  | +145
No test files changed in commit.
Full server-safe suite: 912 passed in 3.99s, 0 failures, 0 warnings
N2C baseline before O1: 912 passed in 3.95s, 0 failures, 0 warnings
```

Critical conclusion:

```text
O1 added nearly 300 runtime lines but added zero committed regression tests.
The unchanged 912 result proves no existing regression, but does not prove O1 branches are tested.
```

## Runtime success: policy read is now live for EV>0 PAPER candidate

Current O1 process:

```text
PID=1435044
```

Proven runtime sequence:

```text
[PAPER_ADAPTIVE_POLICY_READ]
symbol=XRPUSDT regime=BEAR_TREND side=SELL
rolling20_n=20 rolling20_pf=2.024
rolling50_n=50 rolling50_pf=2.203
segment_n=0 segment_pf=1.000 segment_weight=1.00
action=reading_policy

[PAPER_POLICY_ADAPTATION]
segment=XRPUSDT:BEAR_TREND:SELL
n=0 pf=1.000 expectancy=0.000000
old_weight=1.00 new_weight=1.00
action=collect_bootstrap
reason=post_cost_rolling_learning
candidate_ev=0.0338 mode=PAPER

[PAPER_TRAIN_QUALITY_ENTRY]
trade_id=paper_0e7978649ca5
symbol=XRPUSDT side=SELL
source=paper_adaptive_recovery
bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN
regime=BEAR_TREND ev=0.0338
expected_move_src=atr_abs_price_normalized
cost_edge_ok=False
```

This proves:

```text
adaptive rolling state is now READ in a real PAPER adaptive-recovery entry flow.
Do not undo this.
```

## Runtime safety evidence: negative EV was not fabricated

In the same PID, many candidates still correctly show:

```text
decision=REJECT_NEGATIVE_EV ev=-0.0300 / -0.0316 / -0.0338 / -0.0399 / -0.0475
[PAPER_EXPLORE_SKIP] ... original_decision=REJECT_NEGATIVE_EV
```

D_NEG diagnostic entries may still exist, but they must remain shadow-only and not canonical/adaptive learned.

## Confirmed gaps in O1

### Gap A — no tests committed

The O1 commit changes only runtime files. All required O1 tests must now be added.

### Gap B — required `PAPER_ADAPTIVE_STARVATION` log is absent

Code search returned no implementation for:

```text
PAPER_ADAPTIVE_STARVATION
```

This is a real observability gap because recent production was dominated by negative EV drought. Policy reads only happen when an EV-positive candidate reaches the route, so without starvation telemetry the bot cannot distinguish:
- adaptive policy integrated but no EV-positive candidate supply;
- policy route no longer being reached.

### Gap C — REAL_READY is permanently hard-disabled, not safely gated

Current source evidence in `src/services/paper_adaptive_learning.py`:

```text
lines 387-402:
  always appends qualification_provenance_unverified and operator_unlock_required=True

lines 422+:
  comment states "Always false until operator explicitly unlocks with proven qualification"
```

There is no implemented persisted qualification provenance counter/epoch or operator unlock path shown. This is safe today but violates the required lifecycle:

```text
PAPER learning must eventually be able to qualify for controlled REAL_READY,
only after verified post-integration evidence and explicit operator unlock.
```

Do not enable REAL_READY now. Implement the safe future path.

---

# Hard constraints

## Must remain true

```text
- PAPER-only adaptive policy.
- `EV <= 0` never becomes canonical/adaptive learning because of O1A.
- Do not modify raw_ev/final_ev.
- Do not change ECON_BAD, EV, cost-edge, TP/SL, timeout thresholds or geometry.
- D_NEG_EV_CONTROL remains diagnostic shadow-only; no canonical/adaptive metric mutation and no qualification credit.
- Quarantined/stale/invalid trades receive no qualification credit.
- Live/real decision and order routing remain unchanged.
- No automatic transition to real trade.
- Explicit operator unlock remains required even after every metric gate passes.
- Existing historical dashboard/canonical PF may remain as audit context; do not rewrite it here.
```

## No parallel learner or lane

Qualification provenance must be a small metadata/counter extension to the same integrated adaptive learner state, not a second learner, shadow lane, or epoch architecture.

Permitted concept:

```text
qualification_started_at / qualification_schema_version
qualification_n
qualification rolling window containing only eligible closes recorded after provenance start
operator_unlock flag default False
```

This is qualification metadata for the existing one lifecycle, not a separate trading branch.

---

# Required pre-edit investigation

Run:

```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git status --short
git log --oneline -10
git diff --name-status 956a12e..HEAD
git diff --stat 956a12e..HEAD

grep -R "get_paper_policy_snapshot\|PAPER_ADAPTIVE_POLICY_READ\|PAPER_POLICY_ADAPTATION\|PAPER_ADAPTIVE_STARVATION\|check_real_readiness\|qualification\|record_close\|_is_eligible_canonical_paper_learning_trade" -n src/services tests | head -1000

grep -R "D_NEG_EV_CONTROL\|PAPER_LEARNING_SHADOW_SKIP\|quarantined\|paper_adaptive_recovery\|maybe_open_training_sample\|REJECT_NEGATIVE_EV" -n src/services tests | head -1000
```

Before editing, record:

```text
A. Exact point where O1 policy is called for EV>0 paper candidate and where size multiplier is applied.
B. Exact eligibility predicate used before `record_close()`; reuse it for qualification inclusion rather than duplicating weaker logic.
C. Exact current `check_real_readiness()` always-false branch and missing provenance/unlock storage.
D. Exact safe location to accumulate and rate-limit starvation diagnostics without changing routing.
E. Confirmation that no O1 tests exist in the current commit.
```

---

# Implementation A: direct O1 policy integration tests

Add tests to a directly relevant file, preferably:

```text
tests/test_paper_adaptive_learning.py
and/or tests/test_p11ap_o1_policy_integration.py
```

Required direct tests:

1. `get_paper_policy_snapshot()` safely returns expected fields for empty state.
2. Snapshot reflects persisted rolling metrics and segment weight after eligible closes.
3. EV-positive PAPER recovery candidate invokes adaptive snapshot read and returns policy metadata.
4. `collect_bootstrap` for segment_n < 20 leaves bounded weight at 1.0 and still permits existing recovery route.
5. Losing segment (`n>=20`, `pf<0.80`, expectancy<0) causes bounded PAPER downweight.
6. Improving segment (`n>=20`, `pf>1.10`, expectancy>0) causes bounded PAPER preference.
7. `EV<=0` candidate never executes policy preference/admission and never produces canonical learning entry.
8. D_NEG close does not update adaptive state and does not increment qualification state.
9. Quarantined/invalid close does not increment qualification state.
10. Live/real mode does not use/apply the PAPER adaptive policy.
11. Runtime-correlated recovery lifecycle still preserves `paper_adaptive_recovery` through close/update.
12. Same EV-positive candidate receives a different bounded PAPER size/priority after learned segment state changes, proving learning affects future paper behavior.

---

# Implementation B: truthful PAPER adaptive-starvation telemetry

Implement rate-limited diagnostics in the existing PAPER path. It must observe, not alter, routing.

Required log:

```text
[PAPER_ADAPTIVE_STARVATION]
window_s=600
positive_candidates=<count of EV>0 PAPER candidates considered>
negative_ev_rejects=<count of EV<=0 reject events observed in PAPER sampling path>
admitted_recovery=<count>
canonical_closes=<count>
policy_reads=<count>
reason=no_positive_ev_candidates|positive_candidates_gated|awaiting_samples|learning_active
```

Requirements:

```text
- Rate limit to at most once per 600 seconds.
- Counters reset or roll per logged window.
- Must not create/admit trades.
- For a window dominated by REJECT_NEGATIVE_EV with no EV>0 candidate:
    reason=no_positive_ev_candidates
- If EV>0 candidate is admitted:
    reason=learning_active or awaiting_samples as applicable.
```

Use the actual PAPER route invocation evidence; do not count live/real decisions.

Add tests:

```text
13. Window of only EV<=0 PAPER rejects logs no_positive_ev_candidates and opens no canonical trade.
14. Window with EV>0 recovery admission logs learning_active/awaiting_samples and does not falsely claim no supply.
15. Telemetry is rate-limited.
```

---

# Implementation C: REAL_READY qualification provenance without enabling real trading

## Current defect

O1 safely blocks readiness, but lacks any way to become eligible in the future because provenance is never established or counted.

## Required qualification metadata inside existing adaptive learner state

Persist, with safe defaults:

```python
qualification_schema_version = 1
qualification_started_at = <timestamp established only on O1A state migration/init>
qualification_n = 0
qualification_window = []  # maxlen=100 or existing equivalent, eligible closes only
operator_unlock = False     # must default false; do not set true automatically
```

### Migration safety

Existing rolling history (`rolling100_n=99`) may continue to guide bounded PAPER policy, but it must not be counted as qualification evidence.

On first O1A load/migration:

```text
- preserve existing rolling metrics and weights for PAPER-only adaptation;
- initialize qualification_n=0 and empty qualification_window;
- log:
  [PAPER_QUALIFICATION_EPOCH_STARTED]
  reason=provenance_migration_existing_history_not_counted
  existing_rolling100_n=...
  qualification_n=0
```

### Qualification eligible close

Increment qualification evidence only when the close is already eligible for canonical adaptive paper learning and is post-migration:

```text
- normal eligible canonical PAPER close or paper_adaptive_recovery close;
- not D_NEG_EV_CONTROL;
- not quarantined/stale;
- not shadow-only;
- contains valid trade_id/source/outcome/net pnl;
- was recorded after qualification_started_at.
```

Reuse authoritative existing eligibility predicate if available; do not invent a conflicting one.

Log after eligible close:

```text
[PAPER_QUALIFICATION_UPDATE]
trade_id=...
qualification_n=...
rolling100_pf=...
rolling100_expectancy=...
operator_unlock=False
```

### Readiness behavior

`check_real_readiness()` must use `qualification_window`, not old adaptive history, for real readiness metrics.

Rules:

```text
eligible=False when qualification_n < 100
eligible=False when any existing PF/expectancy/net/drawdown/symbol/concentration/stability gate fails
eligible=False when operator_unlock is False
```

Do not automatically submit real orders, even if a test sets operator_unlock True. This function only establishes readiness state.

When all evidence gates pass but operator unlock is false:

```text
eligible=False
reason=operator_unlock_required
```

When qualification provenance is initialized but insufficient:

```text
eligible=False
reason=insufficient_post_integration_samples
```

Only a test-controlled state with:
- qualification_n >= 100;
- passing metrics;
- `operator_unlock=True`;
may return `eligible=True` / lifecycle `REAL_READY`.

Add tests:

```text
16. Existing rolling100 history is not credited to qualification on migration.
17. New eligible adaptive PAPER close increments qualification_n exactly once.
18. D_NEG, quarantine and shadow-only closes do not increment qualification_n.
19. qualification_n <100 blocks readiness even if old rolling PF is high.
20. qualification_n >=100 with passing metrics but operator_unlock=False remains blocked.
21. qualification_n >=100 with passing metrics and operator_unlock=True may return REAL_READY in unit test only.
22. State persistence and reload retain qualification evidence safely.
```

---

# Implementation D: preserve O1 runtime behavior

The existing O1 runtime proof must remain possible:

```text
[PAPER_ADAPTIVE_POLICY_READ] candidate_ev=0.0338 flow
[PAPER_POLICY_ADAPTATION] action=collect_bootstrap
[PAPER_TRAIN_QUALITY_ENTRY] source=paper_adaptive_recovery
```

Do not move adaptive policy into shared RDE scoring. It is acceptable that policy runs only once an EV-positive paper candidate has reached the paper training/recovery route. It is not intended to rescue `REJECT_NEGATIVE_EV`.

Note clearly in logs/docs:

```text
Adaptive PAPER policy governs sampling/sizing of EV-positive paper candidates.
It does not generate EV-positive opportunities from negative market proposals.
```

---

# Allowed files

Only as required:

```text
src/services/paper_adaptive_learning.py
src/services/paper_training_sampler.py
src/services/paper_trade_executor.py only if authoritative eligibility must be imported/reused safely
tests/test_paper_adaptive_learning.py
tests/test_p11ap_n2_recovery_admission.py
tests/test_p11ap_o1_policy_integration.py (new allowed)
```

Do not modify:

```text
src/services/realtime_decision_engine.py
src/services/trade_executor.py
src/services/firebase_client.py
src/services/app_metrics_contract.py
Android/dashboard files
data/research/*
phase2b_firebase_probe.py
runtime state/logs/backups
TP/SL/timeout geometry
cost-edge/EV/ECON_BAD numeric thresholds
live/real order execution
```

---

# Validation

Targeted:

```bash
./venv/bin/python -m pytest -q \
  tests/test_paper_adaptive_learning.py \
  tests/test_p11ap_n2_recovery_admission.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_v10_13u_patches.py \
  tests/test_p11ap_o1_policy_integration.py
```

Server-safe full suite:

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_o1a_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_o1a_fullsuite.txt || true
tail -35 /tmp/p11ap_o1a_fullsuite.txt
```

Baseline:

```text
O1: 912 passed in 3.99s, 0 failures, 0 warnings
```

Required:

```text
>912 passed because direct O1A tests are added
0 failures
0 errors
0 warnings
```

---

# Commit/deploy

Keep current process running while implementing/testing. Before deployment, first capture whether currently open `paper_0e7978649ca5` closed and learned; avoid restarting over an open validation trade unless restoration is already proven safe.

Commit only after clean tests and allowed scope:

```bash
git status --short
git diff --name-status
git diff --stat

git add <allowed files only>
git commit -m "P1.1AP-O1A: Add paper policy evidence and readiness qualification provenance"
git push origin main
```

---

# Post-deploy acceptance

```bash
PID=$(systemctl show cryptomaster -p MainPID --value)
echo "CURRENT_PID=$PID"

sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat | grep -E \
"PAPER_ADAPTIVE_POLICY_READ|PAPER_POLICY_ADAPTATION|PAPER_ADAPTIVE_STARVATION|PAPER_QUALIFICATION_EPOCH_STARTED|PAPER_QUALIFICATION_UPDATE|PAPER_LEARNING_ENTRY|paper_adaptive_recovery|PAPER_CANONICAL_LEARNING_UPDATE|REAL_READINESS_CHECK|REAL_READY|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL|REJECT_NEGATIVE_EV|Traceback|UnboundLocalError"
```

Accept only if:

```text
1. New tests exist and full suite passes.
2. EV-positive PAPER recovery continues to produce POLICY_READ and policy action.
3. Negative-only window logs PAPER_ADAPTIVE_STARVATION reason=no_positive_ev_candidates, without fabricated learning trades.
4. Existing adaptive history is preserved for PAPER policy but qualification starts at 0.
5. New eligible post-O1A PAPER closes increment qualification_n.
6. D_NEG closes do not increment qualification or adaptive canonical learning.
7. REAL_READY stays false in production unless future verified qualification + explicit operator unlock exists.
```

---

# Report back

```text
O1 RUNTIME EVIDENCE PRESERVED:
MISSING TEST COVERAGE FIXED:
STARVATION TELEMETRY IMPLEMENTED:
QUALIFICATION MIGRATION / INITIAL N:
REAL_READY FUTURE PATH:
FILES CHANGED:
TARGETED TEST RESULTS:
FULL SUITE:
COMMIT/PUSH:
POST-DEPLOY POLICY READ:
POST-DEPLOY STARVATION EVIDENCE:
POST-DEPLOY QUALIFICATION UPDATE:
D_NEG NON-REGRESSION:
REAL_READY STATUS:
```
