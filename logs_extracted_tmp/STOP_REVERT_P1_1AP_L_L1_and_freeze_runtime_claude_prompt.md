# Claude Code Prompt — STOP P1.1AP-L/L1/L2 and Revert E-Shadow Experiment

## Decision

Do **not** implement the missing P1.1AP-L2 gates.

The L2 audit confirmed that `P1.1AP-L/L1` is unsafe:
```text
economic_status == BAD                  NOT enforced
canonical_closed_trades >= 100          NOT enforced
idle >= 3600s without canonical/B/C     NOT enforced
paper mode only / live-real isolation   NOT enforced
```

More importantly, this E-shadow lane does not solve the core economic problem:
```text
canonical closed_trades=100
LM total=200
PF≈0.49
net_pnl<0
health=BAD
>800 rejected candidates
no new canonical evidence
```

We are stopping the runtime patch loop. The bot must remain safe/blocked while economic viability is assessed offline.

## Hard instructions

1. **Do not implement P1.1AP-L2.**
2. **Do not restart or deploy the service while `E_ECON_BAD_NEAR_MISS_SHADOW` exists on deployed HEAD.**
3. Revert only the P1.1AP-L experiment commits:
   ```text
   ad56e57 P1.1AP-L1: Reconcile shadow sampler safety boundaries
   1a86bf5 P1.1AP-L: Add post-bootstrap ECON_BAD near-miss shadow sampler
   ```
4. Restore source/test content to safe pre-L baseline `321f10b`.
5. Keep all already validated pre-L fixes:
   ```text
   P1.1AP-J2, K, I/I2, H2, warning cleanup
   ```
6. After revert, do not add more runtime paper sampling/threshold/routing patches. Next work is offline economics audit only.

## Before touching git

```bash
cd /opt/CryptoMaster_srv
git fetch origin
git log --oneline -12
git status --short
git branch --show-current
```

Do not touch or commit runtime/local artifacts:
```text
data/paper_open_positions.json
.env*
venv/
server_local_backups/
data/archive/
data/research/
temporary logs/output files
```

If any tracked source/test changes are already present in working tree, STOP and report them before reverting.

## Revert L/L1 as one controlled revert commit

Use `--no-commit` so the repository is never pushed with only L1 reversed while L remains active:

```bash
git revert --no-commit ad56e57 1a86bf5
```

If conflicts appear:
```bash
git status --short
git diff --name-only --diff-filter=U
```
Resolve only by restoring the affected E-shadow/app/firebase files to the `321f10b` content. Do not introduce new behavior.

## Verify content before commit

The complete `src/services` and `tests` content after staged revert must match `321f10b`:

```bash
git diff --cached --stat
git diff --cached --name-status

# Compare proposed post-revert tree with safe baseline:
git diff --quiet 321f10b -- src/services tests VERIFICATION_V10_13W \
  && echo "PASS: proposed tree matches safe baseline 321f10b" \
  || echo "FAIL: proposed tree still differs from safe baseline"
```

If this reports FAIL, do not commit. Print:

```bash
git diff --name-status 321f10b -- src/services tests VERIFICATION_V10_13W
git diff 321f10b -- src/services tests VERIFICATION_V10_13W
```

and fix only residual L/L1 differences.

Also explicitly confirm E-shadow is gone:

```bash
grep -R "E_ECON_BAD_NEAR_MISS_SHADOW\|ECON_BAD_NEAR_MISS_SHADOW\|econ_bad_shadow\|postbootstrap_econ_bad" -n src/services tests || true
```

Expected:
```text
no E-shadow matches
```

Confirm contracts match safe baseline:

```bash
git diff --quiet 321f10b -- src/services/app_metrics_contract.py \
  && echo "PASS: app_metrics_contract baseline restored" \
  || echo "FAIL: app_metrics_contract differs"

git diff --quiet 321f10b -- src/services/firebase_client.py \
  && echo "PASS: firebase_client baseline restored" \
  || echo "FAIL: firebase_client differs"
```

## Commit the controlled revert

Only if all checks pass:

```bash
git commit -m "Revert P1.1AP-L shadow sampler experiment"
git push origin main
```

## Verify pushed safe tree

```bash
git log --oneline -12
git diff --quiet 321f10b HEAD -- src/services tests VERIFICATION_V10_13W \
  && echo "PASS: HEAD source/tests match pre-L safe baseline" \
  || echo "FAIL: HEAD differs from pre-L baseline"

grep -R "E_ECON_BAD_NEAR_MISS_SHADOW\|ECON_BAD_NEAR_MISS_SHADOW\|econ_bad_shadow\|postbootstrap_econ_bad" -n src/services tests || true
```

## Run safe baseline tests

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research
```

Required result:
```text
854 passed
0 failed
0 errors
0 warnings
```

## Service handling

Do **not** restart the running production service during the revert/test operation.

The running process was started before L/L1; leave it running if it is healthy. Only after the revert has been pushed and the clean test result is proven may a restart be separately considered. Do not restart merely for this task.

## Freeze rule after revert

Create no new runtime patches for:
```text
shadow buckets
recovery probes
threshold lowering
cost-edge bypasses
entry routing
TP/SL or timeout tuning
canonical learning changes
```

The runtime result is already conclusive:
```text
the current strategy has not demonstrated positive edge after costs.
```

## Next task, separate session only

After reporting successful revert, propose a separate **OFFLINE GO/NO-GO ECONOMICS AUDIT** task. It must analyze exported history/signals/rejects without changing production runtime.

## Report back

Return:
- source/test working tree status before revert;
- revert commit hash;
- proof `HEAD` source/tests equal `321f10b`;
- proof E-shadow symbols are absent;
- proof app_metrics_contract.py/firebase_client.py equal baseline;
- exact full-suite result;
- confirmation service was not restarted;
- confirmation runtime patch freeze is in effect pending offline economics audit.
