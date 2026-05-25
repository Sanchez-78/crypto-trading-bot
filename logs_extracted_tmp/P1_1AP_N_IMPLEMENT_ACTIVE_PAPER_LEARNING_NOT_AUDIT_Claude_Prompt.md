# P1.1AP-N — IMPLEMENT ACTIVE PAPER LEARNING LOOP
## NOT A FIREBASE AUDIT. NOT A SHADOW-DIAGNOSTIC TASK. DO NOT WAIT FOR PHASE 2B.

## Operator decision

CryptoMaster is a **PAPER/TRAINING bot**. It must keep running, open simulated paper trades, learn from their closed outcomes, update learning metrics, and use those updated metrics to improve subsequent paper decisions.

Current problem:

```text
The bot is alive, but historical economic_health=BAD / PF≈0.49 gates starve new paper-learning entries.
No new useful paper samples => no new learning => metrics cannot improve.
```

The user explicitly does **not** want another read-only audit, Firebase schema probe, or diagnostic shadow lane. Implement active PAPER learning.

## Current source baseline

At the time of this task:

```text
HEAD may be 20944de, which added research/probe files only.
Runtime trading source remains functionally based on safe state 735ba35 / pre-P1.1AP-L content.
P1.1AP-L/L1 E-shadow experiment is reverted and must not be restored.
Validated pre-research server-safe tests: 854 passed, 0 failed, 0 warnings.
```

Preserve these existing fixes:

```text
P1.1AP-I/I2  D_NEG_EV_CONTROL stays excluded from learning and emits no canonical LEARNING_UPDATE.
P1.1AP-J/J2  B_RECOVERY_READY telemetry/attribution stays intact.
P1.1AP-K     ATR absolute-price normalization before C_WEAK cost-edge stays intact.
```

## Workflow safety

`main` triggers deployment/restart. Do not work directly on `main`.

Start:

```bash
cd /opt/CryptoMaster_srv
git status --short
git log --oneline -12
git switch -c p11ap-n-active-paper-learning
```

Do not commit:
```text
data/paper_open_positions.json
data/research/*
phase2b_firebase_probe.py
.env*
venv/
server_local_backups/
logs/output artifacts
```

Do not run Firebase probe. Do not touch app/Firebase/Android contracts.

## Required investigation before coding

Find the exact existing hot paths:

```bash
grep -R "paper_train\|PAPER_TRAIN\|PAPER_EXIT\|C_WEAK_EV_TRAIN\|B_RECOVERY_READY\|D_NEG_EV_CONTROL\|PAPER_LEARNING_SHADOW_SKIP" -n src/services tests | head -700

grep -R "REJECT_ECON_BAD_ENTRY\|ECON_BAD\|lm_economic_health\|canonical_closed_trades\|cost_edge_too_low\|training_sampler" -n src/services tests | head -700

grep -R "update_from_paper_trade\|LEARNING_UPDATE\|LM_STATE_AFTER_UPDATE\|feature_weights\|calibrat\|policy\|max_seen\|min_seen\|mfe_pct\|mae_pct" -n src/services tests | head -700
```

Before implementation, report in your work log:

```text
A. Current function that decides/routs paper candidates.
B. Exact historical BAD/cost gate causing sample starvation.
C. Current function that closes paper trades and updates learning.
D. Existing persisted metrics/adaptation mechanism that should be reused.
E. Minimal files to change.
```

Prefer extending the current paper learner over creating an unrelated subsystem.

---

# Implementation objective

Create a clean active training epoch for ongoing PAPER learning:

```text
epoch_id = "p11ap_n_clean_v1"
active training bucket = "N_ACTIVE_PAPER_LEARN"
```

This is **not shadow-only**. Trades in `N_ACTIVE_PAPER_LEARN` are valid simulated training samples and must update active learning metrics.

Historical baseline:

```text
historical PF≈0.49 / health=BAD remains preserved for comparison.
It must not permanently veto new N_ACTIVE_PAPER_LEARN admissions.
```

Active epoch:

```text
new paper trades -> close -> active metrics update -> adaptive paper policy update -> next admissions respond to evidence.
```

## A. Restore controlled paper sample flow

Routing priority:

```text
1. Existing normal eligible paper-learning route always keeps priority.
2. If a valid positive-direction candidate is blocked only because the historical economic health is BAD / training-starvation gate, route it to N_ACTIVE_PAPER_LEARN.
3. D_NEG_EV_CONTROL remains isolated; never route it to N.
4. Invalid candidates (missing side, missing/invalid price, NO_CANDIDATE_PATTERN) never route to N.
```

Required N eligibility:

```text
- paper training mode only
- side in BUY/SELL
- valid symbol and current/entry price
- positive EV > 0
- original decision and reject reason recorded
- regime/score/EV available where present
- expected_move_pct / expected_move_src / cost_edge_ok recorded
```

Important paper-learning rule:

```text
A candidate rejected by cost_edge may still be sampled in N during the bootstrap collection phase,
because the learner must measure fee-dominated failures and adapt away from them.
It must preserve and log cost data; this does not approve the candidate for anything except paper learning.
```

Do not route negative-EV D_NEG rows into active learning.

## B. Sampling limits sufficient for learning

Use constants/configuration, with tests:

```text
N_ACTIVE_MAX_OPEN_GLOBAL = 3
N_ACTIVE_MAX_OPEN_PER_SYMBOL = 1
N_ACTIVE_MAX_ENTRIES_PER_HOUR = 12
N_ACTIVE_MAX_ENTRIES_PER_DAY = 100
N_ACTIVE_BOOTSTRAP_CLOSED = 20
```

Initially keep existing paper TP/SL/hold/cost calculation. Do not tune entry and exit economics in this same patch.

Logs:

```text
[PAPER_ACTIVE_EPOCH_ENTRY]
epoch=p11ap_n_clean_v1 bucket=N_ACTIVE_PAPER_LEARN trade_id=...
symbol=... side=... ev=... score=... regime=...
original_decision=... reject_reason=...
expected_move_pct=... expected_move_src=... cost_edge_ok=...

[PAPER_ACTIVE_EPOCH_ENTRY_BLOCKED]
epoch=... reason=max_open_global|max_open_symbol|max_entries_hour|max_entries_day|invalid_candidate|negative_ev ...
```

## C. Metrics must update after every N close

Every closed `N_ACTIVE_PAPER_LEARN` trade must update active epoch learning.

Persist/aggregate at minimum:

```text
trade_id, symbol, side, entry_regime, exit_regime,
entry_ts, exit_ts, entry, exit,
ev, score, original_decision, original_reject_reason,
expected_move_pct, expected_move_src, cost_edge_ok,
gross_move_pct, fee_drag_pct, net_pnl_pct,
reason, outcome, hold_s, tp_pct, sl_pct,
mfe_pct, mae_pct (derived from existing max_seen/min_seen path if available).
```

Required logs:

```text
[PAPER_ACTIVE_EPOCH_EXIT]
epoch=... trade_id=... bucket=N_ACTIVE_PAPER_LEARN
symbol=... side=... outcome=... reason=...
gross_move_pct=... fee_drag_pct=... net_pnl_pct=...
mfe_pct=... mae_pct=...

[PAPER_ACTIVE_LEARNING_UPDATE]
epoch=... trade_id=...
closed_total=... segment_n=...
segment=...
outcome=... net_pnl_pct=...
pf_total=... expectancy_total=...
pf_segment=... expectancy_segment=...
policy_action=...
```

An N close without active update must emit:

```text
[PAPER_ACTIVE_LEARNING_ANOMALY] reason=close_without_active_learning_update ...
```

## D. Active metrics must influence later PAPER decisions

Bootstrap:

```text
active closed_total < 20:
sample valid N candidates within caps;
policy_action=bootstrap_collect;
no pruning/downweighting solely from tiny sample.
```

After bootstrap, compute active segment metrics using the existing closest segmentation mechanism; prefer:

```text
symbol × regime × side
```

or reuse the existing bucket/calibration key if already stable.

Minimum paper-only adaptive behavior:

```text
For segment n >= 20:
- If post-fee expectancy < 0 AND PF < 0.80:
    downweight or temporarily pause N sampling for that segment.
    policy_action=downweight_unprofitable_segment.

- If post-fee expectancy > 0 AND PF > 1.10:
    prefer that segment within existing caps.
    policy_action=prefer_promising_segment.

- Otherwise:
    continue balanced paper sampling.
    policy_action=continue_collecting.
```

Do not claim improved strategy before:

```text
active total closed >= 100
active PF > 1.20 after costs
active expectancy > 0
positive result is not concentrated in a single tiny segment
```

Status is paper-only:

```text
COLLECTING
ADAPTING
FAILING
PROMISING_PAPER_ONLY
```

It must never enable external/live execution.

Required log:

```text
[PAPER_ACTIVE_POLICY_UPDATE]
epoch=... segment=... n=...
pf=... expectancy=...
old_weight=... new_weight=...
action=... reason=...
```

Test that the updated weight/policy changes a later paper admission or priority outcome.

## E. Persistence across restart

Persist only runtime state, ignored from git:

```text
data/paper_active_epoch/p11ap_n_clean_v1/
  learner_state.json
  policy_state.json
  closed_trades.jsonl
```

Requirements:

```text
- create folder safely when absent;
- atomic writes for JSON state;
- reload after restart;
- corrupt state is backed up/quarantined and falls back safely;
- old historical metrics are not overwritten;
- D_NEG and legacy rows are not imported into N.
```

Startup/summary logs:

```text
[PAPER_ACTIVE_EPOCH_START]
epoch=p11ap_n_clean_v1 baseline_pf=... baseline_closed=...
active_closed=... sampling_enabled=True

[PAPER_ACTIVE_EPOCH_RESTORE]
epoch=... state_ok=True closed=... segments=...

[PAPER_ACTIVE_EPOCH_HEALTH]
epoch=... closed=... pf=... expectancy=...
baseline_pf=... delta_pf=...
status=COLLECTING|ADAPTING|FAILING|PROMISING_PAPER_ONLY
```

Add runtime folder to `.gitignore` only if it is not already ignored.

---

# Hard boundaries

Do not modify:

```text
src/services/app_metrics_contract.py
src/services/firebase_client.py
phase2b_firebase_probe.py
data/research/*
Android snapshot/Firebase metrics contract
D_NEG learning isolation semantics
P1.1AP-K ATR normalization/cost-edge logging
P1.1AP-J2 B attribution behavior
```

Do not restore `E_ECON_BAD_NEAR_MISS_SHADOW`.

Do not spend this implementation on offline audit. The task succeeds only when paper trades can flow and active learning updates/adapts.

---

# Required tests

Create focused tests for the active epoch and run existing regressions.

## Routing/sample-flow tests

1. `historical health=BAD` does not prevent a valid positive N paper sample.
2. Missing side / invalid price / invalid candidate is rejected.
3. Negative EV is not N; D_NEG ownership remains unchanged.
4. Existing normally eligible B/C route wins priority over N.
5. Candidate blocked only by historical BAD/cost starvation can enter N in paper mode.

## Caps tests

6. Max global open N = 3.
7. Max per-symbol open N = 1.
8. Hour admission cap = 12.
9. Daily admission cap = 100.
10. N caps do not consume/block normal B/C routing capacity.

## Learning tests

11. N close emits active exit and active learning update.
12. N close captures net/gross/cost and MFE/MAE fields.
13. Losses update PF/expectancy negatively; wins update them positively.
14. D_NEG closes do not mutate active epoch state.
15. Historical baseline values remain unchanged.

## Adaptive-policy tests

16. Fewer than 20 active closes => bootstrap sampling, no premature pruning.
17. Segment with `n>=20`, `PF<0.80`, negative expectancy => downweight/pause next N admissions.
18. Segment with `n>=20`, `PF>1.10`, positive expectancy => preferred sampling within caps.
19. Policy update changes a subsequent paper decision.
20. No `PROMISING_PAPER_ONLY` before total `n>=100`, PF>1.20, expectancy>0 and minimum diversification.

## Persistence/regression tests

21. State reloads across simulated restart.
22. Corrupt state fails safe without crash.
23. Runtime epoch state is git-ignored.
24. D_NEG I/I2 tests continue passing.
25. J/J2 tests continue passing.
26. K cost-edge normalization tests continue passing.
27. Server-safe full suite passes with zero failures/warnings.

Run:

```bash
./venv/bin/python -m pytest -q \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_v10_13u_patches.py \
  <new active-epoch test file>

./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

## Commit/deploy

Remain on the feature branch until all tests pass.

Before proposing merge:

```bash
git status --short
git diff --name-status 20944de..HEAD
git diff --stat 20944de..HEAD
```

Allowed changed files only:

```text
minimal src/services paper/learning files
tests for P1.1AP-N
possibly .gitignore
```

Forbidden in this commit:

```text
data/research/*
phase2b_firebase_probe.py
runtime JSON/log files
.env*
venv/
server_local_backups/
```

Suggested commit:

```text
P1.1AP-N: Reactivate adaptive clean-epoch paper learning
```

Do not merge/push main until reporting tests and receiving operator approval for intentional deployment restart.

## Report back

Return:

```text
ROOT CAUSE OF CURRENT PAPER LEARNING STARVATION:
EXISTING PATHS REUSED:
ACTIVE EPOCH DESIGN:
FILES CHANGED:
HOW EACH PAPER CLOSE UPDATES METRICS:
HOW UPDATED METRICS CHANGE LATER PAPER DECISIONS:
TEST RESULTS:
FEATURE BRANCH / COMMIT:
READY TO MERGE TO MAIN?:
POST-DEPLOY EXPECTED LOGS:
