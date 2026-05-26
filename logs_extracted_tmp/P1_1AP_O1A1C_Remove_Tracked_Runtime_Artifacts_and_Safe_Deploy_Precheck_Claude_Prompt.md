# Claude Code — P1.1AP-O1A1C EMERGENCY REPO HYGIENE + SAFE DEPLOY PRECHECK
## Remove tracked runtime/state artifacts from remote main before production pull

## Severity

**CRITICAL DEPLOYMENT BLOCKER.**

The production checkout is still on defective O1A:

```text
/opt/CryptoMaster_srv HEAD = f49e493 P1.1AP-O1A
running PID = 1436017
```

`git pull` was correctly aborted because remote commits would overwrite live/runtime files:

```text
Updating f49e493..6c52cc0
error: local changes would be overwritten:
  data/paper_open_positions.json
error: untracked working tree files would be overwritten:
  server_local_backups/paper_adaptive_learning_state.json
Aborting
```

Remote state:

```text
origin/main = 6c52cc0 P1.1AP-O1A1B: Restore readiness guard and prove adaptive state isolation
pending commits:
  3283ba1 P1.1AP-O1A1: Emergency fix - Test isolation, qualification provenance, REAL_READY gating, and starvation telemetry
  6c52cc0 P1.1AP-O1A1B: Restore readiness guard and prove adaptive state isolation
```

Remote has forbidden tracked runtime/artifact paths, proven by `git ls-tree` / diff:

```text
M data/paper_open_positions.json
A server_local_backups/paper_adaptive_learning_state.json
A server_local_backups/o1a1_incident_20260525T072716Z/*
A .claude/worktrees/*
A data/research/*
A logs_extracted_tmp/*
```

Separately, tests run on production while still at `f49e493` mutated the real local state file again:

```text
state hash before pytest:
7ae4eb1ea4d615104f9eff87692bd204d17009eefb99ee4fbad0939281d96c1a

state hash after pytest:
36902a04556d1e4cf05731d395c46ea798d363df68cd6b55aba2de766ab197f0

full suite on wrong local HEAD:
10 failed, 924 passed
```

Current disk state before that pytest was already inconsistent with real process logs:

```text
disk before pytest:
  lifetime_n=529
  qualification_n=427
  rolling100_len=100
  qualification_window_len=100

running PID journal:
  real adaptive updates approximately lifetime_n=103 → 111
  qualification_n=1 → 6 under defective O1A
```

## Non-negotiable rules

On production checkout `/opt/CryptoMaster_srv`:

```text
DO NOT git pull
DO NOT git stash
DO NOT git reset --hard
DO NOT run pytest
DO NOT restart/stop cryptomaster during repo repair
DO NOT overwrite/remove data/paper_open_positions.json
DO NOT overwrite/remove server_local_backups/paper_adaptive_learning_state.json
```

The running process is PAPER-only and may hold a better in-memory state than the polluted on-disk file. Keep it running while repairing the Git repository elsewhere.

No real trading enablement. No EV/threshold/TP-SL/cost-edge/ECON_BAD changes. No strategy tuning.

---

# Goal

Create a new cleanup commit on `main` **from a separate clean repair clone outside the production checkout** that:

1. Preserves legitimate O1A1/O1A1B source and test corrections.
2. Removes all tracked runtime state, backup incident data, temporary extracted prompts, accidental worktrees and local research artefacts introduced in the pending commits.
3. Adds/updates `.gitignore` so such paths cannot be recommitted.
4. Confirms O1A1B test isolation and strict readiness gate in the clean clone.
5. Runs full server-safe tests in the clean clone with no production state access.
6. Does not deploy/restart production yet.
7. Produces a later controlled deploy + state reconciliation plan.

Do not operate in `/opt/CryptoMaster_srv` except for read-only forensic capture.

---

# Phase 0 — Read-only forensic capture from production

Run in the active production checkout only for backup/evidence:

```bash
cd /opt/CryptoMaster_srv
TS=$(date -u +%Y%m%dT%H%M%SZ)
INCIDENT="/root/cryptomaster_o1a_repo_state_incident_$TS"
mkdir -p "$INCIDENT"

git rev-parse --short HEAD | tee "$INCIDENT/prod_head.txt"
git status --short | tee "$INCIDENT/prod_git_status.txt"
git log --oneline -15 | tee "$INCIDENT/prod_git_log.txt"

PID=$(systemctl show cryptomaster -p MainPID --value)
echo "$PID" | tee "$INCIDENT/prod_pid.txt"
sudo systemctl status cryptomaster --no-pager -l > "$INCIDENT/prod_service_status.txt"
sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat > "$INCIDENT/prod_current_pid_journal.txt"

cp -a data/paper_open_positions.json "$INCIDENT/paper_open_positions.prod_current.json" 2>/dev/null || true
cp -a server_local_backups/paper_adaptive_learning_state.json "$INCIDENT/paper_adaptive_learning_state.polluted_disk.json" 2>/dev/null || true
cp -a /tmp/p11ap_o1a1b_fullsuite.txt "$INCIDENT/fullsuite_wrong_head_f49e493.txt" 2>/dev/null || true

sha256sum data/paper_open_positions.json 2>/dev/null | tee "$INCIDENT/paper_positions_hash.txt" || true
sha256sum server_local_backups/paper_adaptive_learning_state.json 2>/dev/null | tee "$INCIDENT/adaptive_state_hash.txt" || true

git fetch origin main
git rev-parse --short origin/main | tee "$INCIDENT/remote_head.txt"
git log --oneline HEAD..origin/main | tee "$INCIDENT/remote_pending_commits.txt"
git diff --name-status HEAD..origin/main | tee "$INCIDENT/remote_diff_names.txt"
git ls-tree -r --name-only origin/main | grep -E \
"server_local_backups|data/paper_open_positions.json|data/research|logs_extracted_tmp|\.claude/worktrees" \
  | tee "$INCIDENT/remote_forbidden_tracked_paths.txt" || true

echo "INCIDENT=$INCIDENT"
```

Return the `INCIDENT` path in the final report.

---

# Phase 1 — Create isolated repair clone outside production

Use a fresh directory. Do not point the service at it.

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
REPAIR="/root/CryptoMaster_git_repair_$TS"
git clone --branch main https://github.com/Sanchez-78/crypto-trading-bot.git "$REPAIR"
cd "$REPAIR"

git rev-parse --short HEAD
git log --oneline -12
git status --short
```

Expected repair clone HEAD:

```text
6c52cc0
```

Capture current tracked forbidden paths:

```bash
mkdir -p /root/cryptomaster_repair_evidence
git ls-tree -r --name-only HEAD | grep -E \
"server_local_backups|data/paper_open_positions.json|data/research|logs_extracted_tmp|\.claude/worktrees" \
  | tee /root/cryptomaster_repair_evidence/tracked_forbidden_before_cleanup.txt || true

git --no-pager diff --name-status f49e493..HEAD \
  | tee /root/cryptomaster_repair_evidence/o1a_to_o1a1b_diff_before_cleanup.txt
```

---

# Phase 2 — Inspect and preserve only legitimate code/test fixes

Before removing artifacts, identify allowed O1A1/O1A1B code changes:

```bash
cd "$REPAIR"

git --no-pager diff --name-status f49e493..HEAD -- \
  src/services tests scripts .gitignore

git --no-pager diff --stat f49e493..HEAD -- \
  src/services tests scripts .gitignore

git --no-pager diff f49e493..HEAD -- \
  src/services/paper_adaptive_learning.py \
  src/services/paper_training_sampler.py \
  src/services/paper_trade_executor.py \
  src/services/realtime_decision_engine.py \
  tests/test_p11ap_o1a_completion.py \
  tests/test_paper_adaptive_learning.py \
  tests/test_p11ap_n2_recovery_admission.py \
  > /root/cryptomaster_repair_evidence/legitimate_o1a1b_code_diff.patch
```

Allowed retained changes are only directly related to:
```text
- adaptive test state isolation;
- qualification epoch/provenance/dedup/FLAT inclusion;
- qualification-only readiness;
- strict recent PF `<= 1.00` boundary;
- starvation telemetry;
- directly relevant tests.
```

If pending commits changed threshold/economics/live-real paths beyond this, STOP and report before committing cleanup.

---

# Phase 3 — Remove forbidden tracked artifacts from Git index

In the repair clone, remove from tracking. These files may remain only as runtime/local ignored files on production; they must not be distributed by Git.

```bash
cd "$REPAIR"

git rm -r --cached --ignore-unmatch \
  server_local_backups \
  logs_extracted_tmp \
  .claude/worktrees \
  data/research

git rm --cached --ignore-unmatch data/paper_open_positions.json
```

Do **not** add any runtime state content elsewhere in the repo.

## Update `.gitignore`

Append only missing rules, preserving existing file:

```bash
cat >> .gitignore <<'EOF'

# Runtime state / server-local backups — never commit
server_local_backups/
data/paper_open_positions.json

# Local forensic/research/log extraction artifacts — never commit
data/research/
logs_extracted_tmp/
.claude/worktrees/
EOF

# deduplicate exact duplicate lines without reordering unrelated content
awk '!seen[$0]++' .gitignore > .gitignore.tmp && mv .gitignore.tmp .gitignore
```

Check:

```bash
git status --short
git diff --cached --name-status
git diff -- .gitignore

git ls-files | grep -E \
"server_local_backups|data/paper_open_positions.json|data/research|logs_extracted_tmp|\.claude/worktrees" \
  && { echo "ERROR: forbidden paths still tracked"; exit 1; } || true
```

Important: a cleanup commit removes these from current `main`, preventing future pulls from overwriting live state. Older Git history may still contain them; assess history purge separately only after production safety is restored and only if sensitive data/secrets were committed.

---

# Phase 4 — Verify O1A1B source correctness in repair clone

Inspect source and tests:

```bash
grep -R "state_file\|_STATE_FILE\|qualification_epoch_id\|qualification_started_at\|qualification_eligible\|qualification_opened_at\|qualification_trade_ids_seen\|_try_increment_qualification\|check_real_readiness\|PAPER_ADAPTIVE_STARVATION\|qual_recent" -n \
  src/services tests scripts 2>/dev/null | head -1200

grep -R "rolling20_pf.*<= *1\.00\|qual.*<= *1\.00\|operator_unlock" -n \
  src/services/paper_adaptive_learning.py tests | head -300
```

Required evidence:

```text
- tests create PaperAdaptiveLearning(state_file=<temporary file>) or use equivalent fixture;
- qualification includes only position opened in active epoch;
- WIN / LOSS / FLAT valid post-epoch closes count;
- duplicate trade_id counts once;
- D_NEG/quarantined/shadow/TIMEOUT_NO_PRICE do not count;
- readiness gates use qualification-only evidence;
- recent qualification PF exactly 1.00 blocks readiness;
- operator_unlock defaults False.
```

If this proof fails, apply only the minimal source/test correction before running tests.

---

# Phase 5 — Run tests in repair clone only

Because this is an isolated clone, no production service state can be overwritten. Nonetheless prove local fixture isolation.

If tests need Python environment, create/use a local venv in repair clone; do not run against production state directory.

```bash
cd "$REPAIR"

# Use the repository's normal supported environment setup if venv is absent.
# Example only if dependencies already available:
python3 -m pytest -q tests/test_p11ap_o1a_completion.py 2>&1 | tee /tmp/o1a1c_target_o1a.txt
```

If repo-local pytest invocation is available, run the full required suite:

```bash
python3 -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_o1a1c_fullsuite_repair_clone.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_o1a1c_fullsuite_repair_clone.txt || true
tail -45 /tmp/p11ap_o1a1c_fullsuite_repair_clone.txt
```

If the clone lacks dependencies, do **not** fall back to `/opt/CryptoMaster_srv` tests. Install the same requirements in a venv inside `$REPAIR`, or report the dependency blocker.

Acceptance:

```text
>=934 passed
0 failures
0 errors
0 warnings
```

Also confirm tests did not recreate tracked forbidden paths:

```bash
git status --short
git ls-files | grep -E \
"server_local_backups|data/paper_open_positions.json|data/research|logs_extracted_tmp|\.claude/worktrees" \
  && { echo "ERROR: forbidden paths tracked after tests"; exit 1; } || true
```

Untracked temporary state created in the repair clone is acceptable only if ignored and not staged.

---

# Phase 6 — Commit cleanup on main from repair clone

Stage:
- deletion from Git index of forbidden artifact paths;
- `.gitignore`;
- any strictly necessary O1A1B source/test correction proven in Phase 4.

```bash
cd "$REPAIR"

git status --short
git diff --name-status
git diff --stat

git add .gitignore
git add -u

git diff --cached --name-status
git diff --cached --stat

git commit -m "P1.1AP-O1A1C: Remove runtime artifacts and secure adaptive deployment"
git push origin main
```

Do not stage any ignored/untracked runtime state file.

After push:

```bash
git rev-parse --short HEAD
git ls-tree -r --name-only HEAD | grep -E \
"server_local_backups|data/paper_open_positions.json|data/research|logs_extracted_tmp|\.claude/worktrees" \
  && { echo "ERROR: forbidden paths remain on remote HEAD"; exit 1; } || true
```

---

# Phase 7 — Do NOT immediately pull production; prepare controlled deploy/state reconciliation

After remote is clean, production still has:
```text
HEAD=f49e493
running service with potentially cleaner in-memory PAPER state
polluted on-disk adaptive state
live/open positions possibly present
```

Before any production update:
1. capture open positions;
2. capture full current PID journal;
3. create a dry-run reconciliation plan/script.

On production read-only:

```bash
cd /opt/CryptoMaster_srv
PID=$(systemctl show cryptomaster -p MainPID --value)
TS=$(date -u +%Y%m%dT%H%M%SZ)
PREDEPLOY="/root/cryptomaster_o1a1c_predeploy_$TS"
mkdir -p "$PREDEPLOY"

sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat > "$PREDEPLOY/current_pid_journal.txt"
cp -a data/paper_open_positions.json "$PREDEPLOY/paper_open_positions.json" 2>/dev/null || true
cp -a server_local_backups/paper_adaptive_learning_state.json "$PREDEPLOY/polluted_adaptive_state.json" 2>/dev/null || true

./venv/bin/python - <<'PY' | tee "$PREDEPLOY/open_positions_summary.txt"
import json
from pathlib import Path
p=Path("data/paper_open_positions.json")
d=json.loads(p.read_text()) if p.exists() else []
pos=d if isinstance(d,list) else d.get("positions", d.get("open_positions", []))
if isinstance(pos,dict): pos=list(pos.values())
print("open_positions=", len(pos))
for x in pos:
    print(x.get("trade_id") or x.get("id"), x.get("symbol"), x.get("side"),
          x.get("learning_source"), x.get("training_bucket") or x.get("bucket"))
PY
```

Do not restart while open positions exist unless the corrected loader/restore path and state reconciliation are explicitly approved.

## Reconciliation requirement

Qualification state from O1A is invalid and may be reset to a fresh O1A1C epoch:
```text
qualification_n=0
qualification_window=[]
qualification_trade_ids_seen=[]
operator_unlock=False
```

Ordinary adaptive rolling history is contaminated/uncertain because O1A tests altered the persisted state. Do not silently retain it as trustworthy, and do not erase it blindly.

Create a dry-run-only reconciliation report based on:
```text
- current PID's real PAPER_CANONICAL_LEARNING_UPDATE journal lines;
- earlier verified production PID journal backups if available;
- contaminated disk state backup.
```

Report whether ordinary rolling history can be reconstructed exactly. Apply nothing until explicitly approved.

---

# Required final report

```text
PRODUCTION ACTIVE HEAD/PID:
PRODUCTION DO-NOT-RESTART STATUS:
REMOTE FORBIDDEN TRACKED PATHS CONFIRMED:
LEGITIMATE O1A1/O1A1B CODE RETAINED:
CLEANUP COMMIT HASH/PUSH:
REMOTE HEAD FORBIDDEN PATHS AFTER CLEANUP:
STRICT READINESS PF==1.00 PROOF:
REPAIR-CLONE FULL SUITE:
PRODUCTION INCIDENT BACKUP PATH:
CURRENT OPEN POSITIONS:
ADAPTIVE DISK STATE CONTAMINATION STATUS:
QUALIFICATION RESET PLAN:
ORDINARY ROLLING RECONSTRUCTION STATUS:
CONTROLLED DEPLOY NEXT STEP:
```
