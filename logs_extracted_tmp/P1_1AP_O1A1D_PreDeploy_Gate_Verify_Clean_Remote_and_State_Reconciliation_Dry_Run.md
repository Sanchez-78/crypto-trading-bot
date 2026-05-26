# Claude Code — P1.1AP-O1A1D PRE-DEPLOY GATE
## Verify Clean Remote, Resolve Test-Count Difference, and Build Adaptive-State Reconciliation Dry Run
## NO production pull/restart/apply in this task

## Current known state

Production checkout and service:
```text
/opt/CryptoMaster_srv local HEAD = f49e493 P1.1AP-O1A
service PID = 1436017 (PAPER-only)
disk adaptive state was contaminated by pytest on f49e493
DO NOT restart service yet
```

Previously proven remote incident:
```text
origin/main at 6c52cc0 tracked forbidden runtime/artifact files:
- data/paper_open_positions.json
- server_local_backups/paper_adaptive_learning_state.json
- server_local_backups/o1a1_incident_*
- data/research/*
- logs_extracted_tmp/*
- .claude/worktrees/*
```

Reported cleanup:
```text
97e6777 P1.1AP-O1A1C: cleanup commit pushed to main
241 forbidden artifacts removed from Git index
.gitignore updated
legitimate O1A1/O1A1B source/test changes preserved
repair-clone full suite: 926 passed
```

Important discrepancy:
```text
Defective O1A server checkout previously collected: 924 passed + 10 failed = 934 tests
Clean repair clone reports: 926 passed
```

This can be legitimate if removed `.claude/worktrees` or artifact trees had duplicate collected tests, but it must be proven before production deployment.

## Hard prohibitions

During this task:
```text
DO NOT git pull in /opt/CryptoMaster_srv
DO NOT modify production tracked files
DO NOT run pytest in /opt/CryptoMaster_srv
DO NOT restart/stop cryptomaster
DO NOT write/replace production adaptive state
DO NOT apply reconciliation
DO NOT enable real trading
```

Use only:
- read-only commands on production;
- the existing clean repair clone, or create a fresh second clean clone under `/root`;
- report/dry-run outputs under `/root`, never tracked by Git.

---

# Phase 1 — Verify remote HEAD is truly clean from production (read-only)

On production:

```bash
cd /opt/CryptoMaster_srv
TS=$(date -u +%Y%m%dT%H%M%SZ)
GATE="/root/cryptomaster_o1a1d_predeploy_gate_$TS"
mkdir -p "$GATE"

git rev-parse --short HEAD | tee "$GATE/prod_local_head.txt"
git status --short | tee "$GATE/prod_git_status.txt"

git fetch origin main
git rev-parse --short origin/main | tee "$GATE/remote_head.txt"
git log --oneline HEAD..origin/main | tee "$GATE/pending_commits.txt"
git diff --name-status HEAD..origin/main | tee "$GATE/prod_to_remote_diff_names.txt"

git ls-tree -r --name-only origin/main | grep -E \
"(^server_local_backups/|^data/paper_open_positions\.json$|^data/research/|^logs_extracted_tmp/|^\.claude/worktrees/)" \
  | tee "$GATE/forbidden_paths_remaining_on_remote.txt" || true

git --no-pager show --stat --oneline origin/main | tee "$GATE/remote_head_stat.txt"

echo "GATE=$GATE"
```

Required before proceeding:
```text
origin/main == 97e6777 (or a later explicitly reviewed cleanup commit)
forbidden_paths_remaining_on_remote.txt is empty
```

If forbidden paths remain, STOP and report. Do not prepare deployment.

---

# Phase 2 — Verify source/test scope retained in remote cleanup

Use a fresh clone outside production:

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
VERIFY="/root/CryptoMaster_o1a1d_verify_$TS"
git clone --branch main https://github.com/Sanchez-78/crypto-trading-bot.git "$VERIFY"
cd "$VERIFY"

git rev-parse --short HEAD
git log --oneline -12

git --no-pager diff --name-status f49e493..HEAD -- \
  src/services tests .gitignore scripts | tee "$GATE/legitimate_scope_after_cleanup.txt"

git --no-pager diff --stat f49e493..HEAD -- \
  src/services tests .gitignore scripts | tee "$GATE/legitimate_scope_stat_after_cleanup.txt"

grep -R "state_file\|qualification_epoch_id\|qualification_started_at\|qualification_eligible\|qualification_opened_at\|qualification_trade_ids_seen\|PAPER_ADAPTIVE_STARVATION\|check_real_readiness" -n \
  src/services tests scripts 2>/dev/null | tee "$GATE/o1a1_source_evidence.txt"

grep -R "rolling20_pf.*<= *1\.00\|qual.*<= *1\.00\|operator_unlock" -n \
  src/services/paper_adaptive_learning.py tests | tee "$GATE/strict_readiness_evidence.txt"
```

Required proof:
```text
- test state_file isolation remains in code;
- post-epoch qualification open provenance remains in code;
- FLAT inclusion and dedupe remain;
- strict recent PF <= 1.00 readiness gate remains;
- starvation telemetry remains;
- no economy/live-real threshold changes were added.
```

---

# Phase 3 — Resolve 934-versus-926 test count before deploy

In the clean verification clone, use a local venv/dependencies if needed. Never fall back to production checkout.

Run:

```bash
cd "$VERIFY"

python3 -m pytest --collect-only -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research \
  > "$GATE/collect_clean_remote.txt" 2>&1 || true

tail -30 "$GATE/collect_clean_remote.txt"
```

Also determine whether deleted artifact trees contained pytest-discoverable files in the previous remote commit:

```bash
git ls-tree -r --name-only 6c52cc0 | grep -E \
"(^\.claude/worktrees/|^logs_extracted_tmp/|^data/research/|^server_local_backups/).*(test_.*\.py|.*_test\.py)$" \
  | tee "$GATE/removed_artifact_test_files.txt" || true
```

Run the exact server-safe suite in the clean clone:

```bash
python3 -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee "$GATE/fullsuite_clean_remote.txt"

grep -E "^FAILED |^ERROR " "$GATE/fullsuite_clean_remote.txt" || true
tail -45 "$GATE/fullsuite_clean_remote.txt"
```

Decision:
```text
PASS if 926 passed, 0 failed/errors/warnings AND the eight-test difference is explained
by deletion of accidental pytest-discoverable artifacts or other documented collection change.

STOP if failures/warnings exist or the test-count difference remains unexplained.
```

Do not invent a requirement of 934 if the removed paths prove duplicate/artifact tests were being collected. Record the evidence.

---

# Phase 4 — Production state forensics and reconstruction DRY RUN only

The running process may hold more trustworthy in-memory learning than the polluted disk file. Capture its journal while it continues PAPER operation.

On production read-only:

```bash
cd /opt/CryptoMaster_srv
PID=$(systemctl show cryptomaster -p MainPID --value)
echo "$PID" | tee "$GATE/prod_pid.txt"
sudo systemctl status cryptomaster --no-pager -l > "$GATE/prod_service_status.txt"
sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat > "$GATE/prod_pid_journal.txt"

cp -a server_local_backups/paper_adaptive_learning_state.json \
  "$GATE/polluted_disk_state_before_reconciliation.json" 2>/dev/null || true
cp -a data/paper_open_positions.json \
  "$GATE/open_positions_before_deploy.json" 2>/dev/null || true

./venv/bin/python - <<'PY' | tee "$GATE/open_positions_summary.txt"
import json
from pathlib import Path
p=Path("data/paper_open_positions.json")
d=json.loads(p.read_text()) if p.exists() else []
positions=d if isinstance(d,list) else d.get("positions", d.get("open_positions", []))
if isinstance(positions,dict): positions=list(positions.values())
print("open_positions=", len(positions))
for x in positions:
    print(
        x.get("trade_id") or x.get("id"),
        x.get("symbol"), x.get("side"),
        x.get("learning_source"),
        x.get("training_bucket") or x.get("bucket"),
        x.get("entry_ts") or x.get("entry_time")
    )
PY

grep "PAPER_CANONICAL_LEARNING_UPDATE" "$GATE/prod_pid_journal.txt" \
  | tee "$GATE/real_canonical_updates_current_pid.txt"
grep "PAPER_QUALIFICATION_UPDATE" "$GATE/prod_pid_journal.txt" \
  | tee "$GATE/o1a_invalid_qualification_updates_current_pid.txt"
grep "PAPER_LEARNING_SHADOW_SKIP" "$GATE/prod_pid_journal.txt" \
  | tee "$GATE/dneg_shadow_skip_current_pid.txt"
```

Prepare a **dry-run report only**:

```text
A. Count real PAPER_CANONICAL_LEARNING_UPDATE rows available from current PID.
B. Count invalid O1A qualification rows (all qualification from f49e493 is invalid provenance).
C. Determine whether ordinary adaptive rolling history can be reconstructed exactly
   from available real journal lines plus earlier incident journal backups.
D. Qualification deployment plan must reset to:
   qualification_n=0
   qualification_window=[]
   qualification_trade_ids_seen=[]
   operator_unlock=False
   new qualification epoch on corrected code.
E. Ordinary rolling state:
   - reconstruct only if exact evidence exists;
   - otherwise mark untrusted and propose operator choice before overwrite.
```

Do not apply any state change in this task.

---

# Phase 5 — Return gate report; no production deploy yet

Return:

```text
REMOTE CLEAN HEAD:
REMOTE FORBIDDEN PATH CHECK:
LEGITIMATE O1A1/O1A1B SOURCE RETAINED:
STRICT READINESS GATE RETAINED:
CLEAN-CLONE FULL SUITE:
926 vs 934 EXPLANATION:
PRODUCTION PID/HEAD STILL RUNNING:
OPEN POSITIONS:
DISK ADAPTIVE STATE STATUS:
REAL JOURNAL UPDATES AVAILABLE FOR RECONSTRUCTION:
QUALIFICATION RESET DRY-RUN PLAN:
ORDINARY ROLLING RECONSTRUCTION: EXACT | INCOMPLETE | IMPOSSIBLE FROM AVAILABLE LOGS
DEPLOYMENT RECOMMENDATION: APPROVE_CONTROLLED_DEPLOY | HOLD_FOR_MORE_EVIDENCE
NO PRODUCTION PULL/RESTART/APPLY PERFORMED:
GATE EVIDENCE DIRECTORY:
```

Only after I review that gate report may you receive approval to:
- safely preserve/replace local runtime files;
- update the production checkout to clean remote;
- apply qualification reset/reconstructed state;
- restart the PAPER service.
