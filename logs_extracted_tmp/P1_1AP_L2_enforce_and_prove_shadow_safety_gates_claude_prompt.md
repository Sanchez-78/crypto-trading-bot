# Claude Code Prompt — P1.1AP-L2: Enforce and Prove Missing Shadow Safety Gates

## HARD STOP

Do **not** deploy/restart production on `1a86bf5` or `ad56e57` yet.

The P1.1AP-L1 audit report is internally inconsistent and does not prove safety. Its own requirement table explicitly states:

```text
closed_trades >=100: "(passed as context; not enforced in E-shadow scope)"
```

That is a **FAIL**, not PASS. A post-bootstrap-only sampler must enforce the post-bootstrap gate in code.

Other items were marked PASS without direct E-shadow proof:

```text
- idle >=60m: config exists, no explicit behavior test
- paper-only/live-real isolation: no explicit route proof
- max global open / max per-symbol open: "implicit"
- exit attribution: "not E-specific"
- canonical LM skipped: cites D_NEG test instead of E-shadow isolation test
```

The report also says both:

```text
867 passed, 0 failures, 0 warnings
(4 pre-existing environment failures unrelated to P1.1AP-L)
```

These cannot both describe the same exact test run. The clean trusted baseline was `321f10b: 854 passed, 0 warnings, 0 failures`.

Finally, the claimed "Exact Diff Between Baseline (321f10b) and Final (ad56e57)" listing only `+4 -4` and `+1 -1` appears to be the L1 corrective diff, not the full `321f10b..ad56e57` feature diff. Prove actual scope.

## Trusted baseline and current commits

```text
321f10b Tests: Replace legacy boolean-return pytest checks with assertions
  Trusted server-safe baseline: 854 passed, 0 warnings, 0 failures

1a86bf5 P1.1AP-L: Add post-bootstrap ECON_BAD near-miss shadow sampler
ad56e57 P1.1AP-L1: Reconcile shadow sampler safety boundaries
```

L1 claimed to fix:
```text
- E-shadow rate cap 2/30m -> 1/30m
- app_metrics_contract.py restored to 321f10b
- firebase_client.py restored to 321f10b
```

Verify those claims, but do not treat L as accepted until all missing gates below are enforced and directly tested.

## Goal

Create the minimal follow-up patch required to make `E_ECON_BAD_NEAR_MISS_SHADOW` genuinely:

```text
post-bootstrap only
ECON_BAD only
starvation-only
paper-only
strictly capped
shadow-only / never canonical
non-interfering with B/C/D_NEG paths
```

Use commit message only if changes are required and tests pass:

```text
P1.1AP-L2: Enforce post-bootstrap shadow safety gates
```

## Phase 1 — Audit exact committed diff and current implementation

Run exactly:

```bash
cd /opt/CryptoMaster_srv
git fetch origin
git log --oneline -12
git status --short

git --no-pager diff --name-status 321f10b..ad56e57
git --no-pager diff --stat 321f10b..ad56e57
git --no-pager diff 321f10b..ad56e57 -- src/services tests

git diff --quiet 321f10b ad56e57 -- src/services/app_metrics_contract.py \
  && echo "PASS: app_metrics_contract identical to baseline" \
  || echo "FAIL: app_metrics_contract differs from baseline"

git diff --quiet 321f10b ad56e57 -- src/services/firebase_client.py \
  && echo "PASS: firebase_client identical to baseline" \
  || echo "FAIL: firebase_client differs from baseline"

grep -R "E_ECON_BAD_NEAR_MISS_SHADOW\|ECON_BAD_NEAR_MISS\|econ_bad_shadow\|postbootstrap_econ_bad" -n src/services tests
```

Report the actual full diff from baseline. The feature implementation files and all newly added tests must appear; do not present only the L1 patch delta as baseline-to-final scope.

## Phase 2 — Inspect exact route condition

Open the E-shadow selection and exit/isolation code. Prove from file:line evidence whether each condition is currently enforced.

Required table:

| Requirement | Must be executable code gate? | Current file:line | Current test | PASS/FAIL |
|---|---:|---|---|---|
| paper mode only; never live/real | yes | | | |
| `economic_status == BAD` | yes | | | |
| canonical/global closed count `>= 100` | yes | | | |
| no normal canonical/B/C evidence entry for `>= 3600s` | yes | | | |
| only weak-positive `REJECT_ECON_BAD_ENTRY` | yes | | | |
| `0.030 <= ev < B threshold (0.038)` | yes | | | |
| B route wins before E-shadow | yes | | | |
| normal C_WEAK candidate not stolen | yes | | | |
| D_NEG owns negative EV | yes | | | |
| max `1` new E-shadow per rolling 30m | yes | | | |
| max `1` open E-shadow globally | yes | | | |
| max `1` open E-shadow per symbol | yes | | | |
| lifetime closed limit `20` | yes | | | |
| E-shadow exit attribution emitted | yes | | | |
| E-shadow no canonical updater call/log | yes | | | |
| E-shadow no PF/economic-health mutation | yes | | | |

No line may be marked PASS because it was present only in production context or inherited implicitly unless the inherited gate is conclusively called for E-shadow and there is a direct regression test.

## Mandatory fixes

### A. Enforce post-bootstrap gate in executable routing code

The L1 report confirms this is missing. E-shadow admission must explicitly obtain the canonical training/closed count using the same trusted canonical count helper used by the current architecture and require:

```python
canonical_closed_trades >= 100
```

Boundary tests:

```text
closed_trades=99  -> E-shadow blocked
closed_trades=100 -> eligible if all other gates pass
closed_trades=101 -> eligible if all other gates pass
```

Do not reactivate or alter P1.1AO.

### B. Enforce and test starvation-idle gate

A constant alone is not proof. Routing must require a real state signal proving no accepted normal evidence route in at least 3600 seconds:

```text
no accepted B_RECOVERY_READY entry for >=3600s
no accepted C_WEAK_EV_TRAIN entry for >=3600s
no canonical learning-producing paper entry for >=3600s
```

Use existing tracking if it represents accepted qualifying entries. Do not incorrectly use RDE rejected-candidate timestamps or D_NEG/E-shadow shadow entries to reset canonical evidence starvation.

Tests:

```text
last canonical/B/C entry at now-3599 -> E blocked
last canonical/B/C entry at now-3600 -> boundary allowed using documented >= convention
D_NEG/E-shadow entry does not falsely end canonical starvation
new B or C accepted entry resets starvation and blocks E
```

### C. Prove live/real isolation

E-shadow routing must require existing paper mode explicitly. Add direct tests:

```text
paper_train mode -> eligible when all conditions true
live mode -> no E route
real mode -> no E route
```

### D. Enforce E-specific caps

Do not rely on an unrelated total paper cap unless tests prove no interference.

Requirements:

```text
1 E-shadow entry per rolling 30m
1 open E-shadow globally
1 open E-shadow per symbol
20 closed lifetime E-shadow limit
```

Tests must construct E-shadow state directly and prove each boundary.

Normal opportunity priority test:
```text
An open E-shadow must not prevent an otherwise valid B_RECOVERY_READY or C_WEAK_EV_TRAIN evidence entry solely because E occupied a diagnostic cap/slot. If architecture's hard global safety cap makes this impossible, report and do not deploy until a non-interfering design is implemented.
```

### E. Prove E-shadow exit path directly

Create an actual E-shadow position and close it through the same production close function. Assert E-specific behavior:

```text
PAPER_EXIT includes bucket=E_ECON_BAD_NEAR_MISS_SHADOW
PAPER_TRAIN_QUALITY_EXIT emitted
PAPER_TRAIN_ECON_ATTRIB emitted with E bucket and attribution
PAPER_LEARNING_SHADOW_SKIP emitted with real trade_id and reason=postbootstrap_econ_bad_near_miss_shadow_only
bucket metrics remain diagnostic
```

Explicitly patch/mock and assert not called/not emitted:

```text
update_from_paper_trade not called for E-shadow
LM_STATE_AFTER_UPDATE absent for E-shadow
[LEARNING_UPDATE] ok=True absent for E-shadow
canonical PF/economic-health state unchanged
```

A D_NEG-only isolation test is not sufficient.

### F. Ensure contracts are identical to baseline

Keep:

```text
src/services/app_metrics_contract.py identical to 321f10b
src/services/firebase_client.py identical to 321f10b
```

Do not add workarounds in tests for schema changes.

## Forbidden changes

Do not change:

```text
ECON_BAD threshold 0.045
B_RECOVERY_READY threshold 0.038
C_WEAK required_move_pct 0.2300 or K normalization
P1.1AO activation/lifetime rules
D_NEG I/I2 isolation
B J/J2 behavior
canonical LM/PF/economic health
live/real trading, RDE, sizing, TP/SL
Firebase/Android/app metrics contracts
```

## Tests to add or strengthen

There must be direct tests for all of these, not just comments:

```text
1. BAD + closed=100 + canonical idle=3600 + ev=0.0348 + weak reject + paper mode => E admission
2. closed=99 blocks
3. closed=101 eligible
4. econ status != BAD blocks
5. idle=3599 blocks; idle=3600 allowed
6. D_NEG/E entry does not reset accepted-evidence timer
7. recent B/C entry blocks E
8. ev=0.0299 blocks; ev=0.0300 allowed; ev=0.037999 allowed; ev=0.038 not E and B owns
9. negative EV stays D_NEG path
10. paper-only: live/real modes block E
11. strict 1/30m rate cap boundaries
12. max E open global and symbol
13. lifetime closed=20 blocks
14. E open does not steal/block valid B/C
15. E close emits E-specific quality/attrib/shadow skip/bucket metrics
16. E close cannot update canonical LM, PF or health
17. D_NEG remains unchanged
18. J/J2 B route/attribution remains unchanged
19. K normalization/cost-edge unchanged
20. app_metrics_contract/firebase_client equal baseline
```

## Run tests from exact current branch before and after edits

Before edits, preserve evidence:

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_l1_before_l2_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_l1_before_l2_fullsuite.txt || true
tail -40 /tmp/p11ap_l1_before_l2_fullsuite.txt
```

Then after fixes:

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
  --ignore=data/research 2>&1 | tee /tmp/p11ap_l2_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_l2_fullsuite.txt || true
tail -40 /tmp/p11ap_l2_fullsuite.txt
```

Required final result:

```text
0 failed
0 errors
0 warnings
at least 867 passed (greater if direct safety tests are added)
```

Do not describe any failures as "pre-existing" unless reproduced on `321f10b` using the exact identical command; trusted baseline is clean.

## Commit hygiene

Before committing:

```bash
git diff --stat
git diff --name-only
git diff -- src/services tests
git status --short

git diff --quiet 321f10b HEAD -- src/services/app_metrics_contract.py \
  && echo "PASS app contract unchanged from baseline" \
  || echo "FAIL app contract differs"

git diff --quiet 321f10b HEAD -- src/services/firebase_client.py \
  && echo "PASS firebase unchanged from baseline" \
  || echo "FAIL firebase differs"
```

Commit only required E-shadow source/test changes. Never commit runtime files, `.env*`, `venv/`, backups or logs.

## Commit

Only once all direct gates and full suite pass:

```text
P1.1AP-L2: Enforce post-bootstrap shadow safety gates
```

Push, but do **not** restart production until reporting the final audit evidence.

## Report back

Return:
- full `321f10b..HEAD` changed-file list;
- corrected audit table with every PASS supported by file:line and direct E-specific test;
- whether L1 already had any missing gate besides closed count;
- exact full-suite before/after outputs;
- final commit hash;
- proof app/Firebase contracts remain identical to `321f10b`;
- statement that production was not restarted pending acceptance.
