# Claude Code Prompt — P1.1AP-L HARD-STOP Audit and Minimal Reconciliation

## Mode

Do **not** assume P1.1AP-L is accepted. Perform a hard-stop audit of commit `1a86bf5` against the agreed specification and the clean pre-L baseline. Do not deploy/restart production from this commit until the audit passes.

If and only if the audit confirms a violation, implement the smallest corrective follow-up commit named `P1.1AP-L1: Reconcile shadow sampler safety boundaries`. Do not add new strategy behavior.

## Trusted pre-L baseline

Immediately before P1.1AP-L:

```text
HEAD 321f10b
Server-safe full suite: 854 passed, 0 warnings
Runtime: stable, D_NEG shadow-only confirmed
P1.1AO correctly inactive at canonical closed_trades=100
Confirmed post-bootstrap gap: ECON_BAD starvation with no B/C canonical evidence
```

Validated production state:

```text
[ECON_CANONICAL_ACTIVE] closed_trades=100 pf=0.49 status=BAD
Total trades in LM: 200
[ECON_BAD_DIAG_HEARTBEAT] total=822 neg_ev=650 weak_ev=172 best_ev=0.0348
probe_ready=False probe_block=below_probe_ev
```

## Reported P1.1AP-L result requiring audit

Reported commit:

```text
1a86bf5 P1.1AP-L: Add post-bootstrap ECON_BAD near-miss shadow sampler
```

Reported implementation contains possible specification violations:

1. **Rate-cap mismatch**
   - Agreed cap: maximum `1` E-shadow entry per `30 minutes`.
   - Reported implementation: maximum `2` entries per `30-minute window`.
   - This is not acceptable unless the report is wrong; audit and correct to `1/30m`.

2. **Unrelated Android/app contract change**
   - Agreed hard boundary: no Firebase/Android/app-metrics contract changes.
   - Reported modifications include `src/services/app_metrics_contract.py`, removing `learning_monitor_alive` from `component_heartbeats`.
   - This must be reverted unless it was already present before `1a86bf5` and not actually part of the commit. P1.1AP-L must not change app contract fields.

3. **Full-suite inconsistency**
   - Trusted baseline: `854 passed, 0 warnings`.
   - Reported result: `867 total passing` but also `4 pre-existing failures remain`.
   - With 13 added tests, expected server-safe result is `867 passed, 0 failures, 0 warnings`.
   - Determine exact failing tests and whether the same established command was run.

4. **Eligibility requirements not proven in summary**
   Audit whether implementation actually enforces all:
   ```text
   economic_status == BAD
   canonical/global closed trades >= 100
   no accepted canonical/B/C evidence entry for >=60 minutes
   weak-positive REJECT_ECON_BAD_ENTRY only
   0.030 <= EV < 0.038
   paper mode only
   does not steal B or normal C_WEAK
   ```

5. **Caps/isolation requirements not proven**
   Audit whether implementation enforces all:
   ```text
   max 1 new E-shadow / 30 minutes
   max 1 E-shadow open globally
   max 1 E-shadow open per symbol
   max 20 lifetime closed E-shadow samples
   normal B/C route priority and capacity non-interference
   no canonical LM/PF/economic health mutation
   no canonical LEARNING_UPDATE or LM_STATE_AFTER_UPDATE
   ```

6. **Potential EV typo**
   - Summary says `0.030–0.348 EV`; expected upper boundary is `<0.038`, with observed `0.0348`.
   - Confirm constants and tests use `<0.038`, not `<0.348`.

7. **Unexpected file scope**
   - Summary mentions `firebase_client.py` and 706 lines across 5 files.
   - Verify exactly which files changed and whether every change is necessary and within scope.

## Step 1 — Freeze and inspect only

Run from server/repo:

```bash
cd /opt/CryptoMaster_srv
git fetch origin
git status --short
git log --oneline -12
git --no-pager show --stat --oneline 1a86bf5
git --no-pager diff --name-status 321f10b..1a86bf5
git --no-pager diff 321f10b..1a86bf5 -- \
  src/services/paper_exploration.py \
  src/services/paper_trade_executor.py \
  src/services/trade_executor.py \
  src/services/app_metrics_contract.py \
  src/services/firebase_client.py \
  tests/test_p11ap_l_econ_bad_shadow.py \
  tests/test_p1_paper_exploration.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py
```

Do not commit runtime artifacts. Do not restart production.

## Step 2 — Audit implementation against the gates

Locate every E-shadow reference:

```bash
grep -R "E_ECON_BAD_NEAR_MISS_SHADOW\|ECON_BAD_NEAR_MISS\|econ_bad_shadow\|postbootstrap_econ_bad" -n src/services tests
grep -R "learning_monitor_alive\|component_heartbeats" -n src/services/app_metrics_contract.py tests
```

Produce an audit table before changing code:

| Requirement | Code evidence | Test evidence | PASS/FAIL |
|---|---|---|---|
| BAD only | file:line | test | |
| closed trades >=100 | file:line | test | |
| idle/no canonical evidence >=60m | file:line | test | |
| weak positive 0.030 <= EV < 0.038 | file:line | test | |
| paper only / live-real isolation | file:line | test | |
| B priority | file:line | test | |
| C_WEAK priority | file:line | test | |
| 1 entry / 30m | file:line | test | |
| 1 global open | file:line | test | |
| 1 symbol open | file:line | test | |
| lifetime 20 | file:line | test | |
| exit attribution present | file:line | test | |
| canonical LM skipped | file:line | test | |
| app/Firebase contracts untouched | diff | test | |

## Step 3 — Run exact established test baseline

First run on current `1a86bf5` without edits:

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_l_pre_reconcile_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_l_pre_reconcile_fullsuite.txt || true
tail -40 /tmp/p11ap_l_pre_reconcile_fullsuite.txt
```

Expected if L is safe and only 13 new tests were added:

```text
867 passed, 0 failures, 0 warnings
```

If failures occur, list their exact names and determine whether they are caused by L. Do not label them pre-existing because baseline `321f10b` passed cleanly.

Run focused tests:

```bash
./venv/bin/python -m pytest -q \
  tests/test_p11ap_l_econ_bad_shadow.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_p11ab_stale_position_quarantine.py \
  tests/test_v10_13u_patches.py
```

## Step 4 — Mandatory reconciliation if confirmed

If the reported deviations exist, implement only the following minimal fixes.

### A. Enforce strict shadow rate cap

Change E-shadow rate cap to:

```text
max 1 admission per rolling 30-minute window
```

Tests:
```text
first admission allowed
second at +1s blocked
second at +1799s blocked
second at +1800s allowed according to existing boundary convention; document >= or > and test it
```

Do not change D_NEG, B, or C caps.

### B. Restore app metrics contract

If `1a86bf5` removed/changed `learning_monitor_alive` or any app/Firebase contract field, revert that diff completely to the `321f10b` behavior.

P1.1AP-L may not modify:

```text
src/services/app_metrics_contract.py
src/services/firebase_client.py
Android snapshot schema
Firebase contract
```

unless the diff proves the file was not changed by L. If reverting introduces a test failure in newly-added L tests, fix the L test; do not alter the contract.

### C. Add/fix missing gates

If any are absent, enforce and test:

```text
economic_status == BAD
canonical closed trades >=100
no B/C/canonical evidence entry >=60 minutes
0.030 <= ev < 0.038
original decision REJECT_ECON_BAD_ENTRY weak_ev
paper-only
B and normal C have priority
max open global=1 and per symbol=1
lifetime=20
```

Do not broaden candidate eligibility.

### D. Keep E-shadow fully non-canonical

Ensure:
```text
PAPER_LEARNING_SHADOW_SKIP with real trade_id
PAPER_TRAIN_ECON_ATTRIB available
bucket metrics allowed
diagnostic shadow save only
```

Never:
```text
update_from_paper_trade for E-shadow
LM_STATE_AFTER_UPDATE for E-shadow
canonical LEARNING_UPDATE for E-shadow
economic PF/health mutation from E-shadow
```

## Hard boundaries

Do not:
```text
- lower threshold 0.045 or B threshold 0.038
- lower cost edge 0.2300 %
- enable P1.1AO post-bootstrap
- change D_NEG/I/I2
- change B J/J2
- change K normalization
- alter live/real trading, RDE, TP/SL, sizing
- alter Firebase/Android/app metrics contracts
- deploy with failing server-safe suite
```

## Required regression tests after reconciliation

Tests must explicitly cover:

```text
1. BAD + closed_trades=100 + idle>=60m + ev=0.0348 => E-shadow eligible
2. status != BAD => blocked
3. closed_trades=99 => blocked
4. idle<60m => blocked
5. ev=0.0299 blocked; ev=0.0300 allowed; ev=0.037999 allowed; ev=0.038 blocked/B owns
6. negative EV => D_NEG owns
7. B-eligible => B wins
8. normal C eligible => C wins
9. strict cap = 1 / 30m
10. max one open global/per-symbol
11. lifetime closed=20 blocks
12. E-shadow does not block normal B/C
13. E-shadow close emits quality/attribution/shadow skip
14. no canonical learning/PF mutation for E-shadow
15. D_NEG unchanged
16. J/J2/K unchanged
17. live/real blocked
18. app_metrics/Firebase contract unchanged from baseline
```

## Final validation

```bash
./venv/bin/python -m pytest -q \
  tests/test_p11ap_l_econ_bad_shadow.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_p11ab_stale_position_quarantine.py \
  tests/test_v10_13u_patches.py

./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

Required final outcome:

```text
0 failed
0 errors
0 warnings
>=867 passed
```

## Commit and deployment rule

If no violations exist and the exact full suite passes, do not create a corrective commit; report audit PASS.

If violations are confirmed and corrected, commit only required source/tests:

```text
P1.1AP-L1: Reconcile shadow sampler safety boundaries
```

Do not deploy/restart until full-suite result is clean.

## Report back

Provide:
- exact diff file list from `321f10b..1a86bf5`;
- requirement audit table;
- exact initial full-suite failures if any;
- exact corrected behavior and files, if needed;
- final full-suite output;
- commit hash if L1 was required;
- confirmation that app/Firebase contract remains identical to `321f10b`.
