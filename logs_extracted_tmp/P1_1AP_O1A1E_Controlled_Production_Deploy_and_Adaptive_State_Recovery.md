# Claude Code — P1.1AP-O1A1E CONTROLLED PRODUCTION DEPLOY + STATE RECOVERY
## Deploy clean remote code only after selecting a truthful adaptive-state baseline

## Approval scope

O1A1C pre-deploy gate reportedly passed:

```text
remote HEAD: 97e6777
remote forbidden tracked paths: NONE
clean-clone full suite: 926 passed
934 vs 926 resolved: 8 tests were accidental artifact-tree collections removed by cleanup
legitimate O1A1/O1A1B fixes preserved
```

This task authorizes a **controlled PAPER-only deployment** only after state reconstruction feasibility is determined.

Production still runs:
```text
local HEAD=f49e493 (defective O1A)
service PID=1436017
do not restart until state baseline is prepared
```

The on-disk `server_local_backups/paper_adaptive_learning_state.json` is contaminated by pytest run under f49e493 and must not be loaded after restart.

## Critical state decision rule

Qualification state is invalid from O1A and must always start fresh under corrected code:

```text
qualification_n=0
qualification_window=[]
qualification_trade_ids_seen=[]
operator_unlock=False
new qualification epoch initialized by corrected code
```

Ordinary adaptive rolling/lifetime/segment state:

```text
1. Attempt exact reconstruction from real production `[PAPER_CANONICAL_LEARNING_UPDATE]` journal rows.
2. If at least the last 100 real eligible canonical adaptive updates can be parsed exactly and deduplicated:
   reconstruct rolling20/50/100 and related ordinary metrics from those verified rows only.
3. If exact reconstruction is incomplete, unsafe, or fewer than required rows are available:
   do NOT preserve contaminated ordinary state.
   Reset ordinary adaptive policy state to empty under corrected code:
      rolling20/50/100=[]
      lifetime_n=0 / fresh PAPER learning baseline
      segment_weights={}
      lifecycle=PAPER_COLLECTING
   Keep a backup/report of discarded contaminated state.
```

This is not erasing verified historical database evidence. It is selecting a trustworthy active learner baseline after confirmed test contamination. The historical dashboard/canonical audit state remains separate and untouched.

Do not reconstruct from the contaminated JSON file except to document it; use journal evidence only.

## Never change

```text
EV / ECON_BAD / cost-edge numeric thresholds
TP/SL/timeout geometry
D_NEG shadow-only isolation
live/real order execution
operator_unlock=False
Firebase or Android contracts
```

---

# Phase 0 — Read-only final evidence capture while service remains running

```bash
cd /opt/CryptoMaster_srv
TS=$(date -u +%Y%m%dT%H%M%SZ)
DEPLOY="/root/cryptomaster_o1a1e_deploy_$TS"
mkdir -p "$DEPLOY"

git rev-parse --short HEAD | tee "$DEPLOY/prod_head_before.txt"
git status --short | tee "$DEPLOY/prod_status_before.txt"
git fetch origin main
git rev-parse --short origin/main | tee "$DEPLOY/remote_head.txt"

git ls-tree -r --name-only origin/main | grep -E \
"(^server_local_backups/|^data/paper_open_positions\.json$|^data/research/|^logs_extracted_tmp/|^\.claude/worktrees/)" \
  | tee "$DEPLOY/remote_forbidden_check.txt" || true

if [ -s "$DEPLOY/remote_forbidden_check.txt" ]; then
  echo "STOP: remote still contains forbidden runtime artifacts"
  exit 1
fi

PID=$(systemctl show cryptomaster -p MainPID --value)
echo "$PID" | tee "$DEPLOY/pid_before.txt"
sudo systemctl status cryptomaster --no-pager -l > "$DEPLOY/service_before.txt"
sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat > "$DEPLOY/current_pid_journal.txt"

cp -a data/paper_open_positions.json "$DEPLOY/paper_open_positions.before.json" 2>/dev/null || true
cp -a server_local_backups/paper_adaptive_learning_state.json "$DEPLOY/adaptive_state.contaminated.before.json" 2>/dev/null || true

sha256sum data/paper_open_positions.json 2>/dev/null | tee "$DEPLOY/open_positions_hash.before.txt" || true
sha256sum server_local_backups/paper_adaptive_learning_state.json 2>/dev/null | tee "$DEPLOY/adaptive_state_hash.before.txt" || true

echo "DEPLOY=$DEPLOY"
```

Required:
```text
origin/main == 97e6777 or later explicitly reviewed clean commit
remote_forbidden_check.txt empty
```

---

# Phase 1 — Stop gate: do not deploy over open paper positions

```bash
cd /opt/CryptoMaster_srv
DEPLOY=$(ls -dt /root/cryptomaster_o1a1e_deploy_* | head -1)

./venv/bin/python - <<'PY' | tee "$DEPLOY/open_positions_summary.txt"
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
```

If `open_positions > 0`:
```text
STOP. Do not pull, do not stop/restart, do not apply state. Report open positions and wait for natural paper closes.
```

If `open_positions == 0`, proceed.

---

# Phase 2 — Journal-only ordinary adaptive reconstruction assessment

Parse actual real canonical adaptive update logs from all available captured production journals and current PID. Search `/root` incident folders and current journal, not contaminated JSON.

Create a read-only assessment script outside Git:

```bash
cat > "$DEPLOY/reconstruct_adaptive_dry_run.py" <<'PY'
import glob, re, json
from pathlib import Path

files = sorted(set(
    glob.glob("/root/**/journal*.txt", recursive=True)
    + glob.glob("/root/**/current_pid_journal.txt", recursive=True)
    + glob.glob("/root/**/prod_pid_journal.txt", recursive=True)
))
pat = re.compile(
    r"\[PAPER_CANONICAL_LEARNING_UPDATE\].*?"
    r"trade_id=(?P<trade_id>\S+).*?"
    r"symbol=(?P<symbol>\S+).*?"
    r"side=(?P<side>\S+).*?"
    r"regime=(?P<regime>\S+).*?"
    r"learning_source=(?P<source>\S+).*?"
    r"outcome=(?P<outcome>\S+).*?"
    r"net_pnl_pct=(?P<pnl>-?\d+(?:\.\d+)?)"
)
rows = {}
sources = {}
for fn in files:
    try:
        for line in Path(fn).read_text(errors="replace").splitlines():
            if "PAPER_CANONICAL_LEARNING_UPDATE" not in line:
                continue
            m = pat.search(line)
            if not m:
                continue
            d = m.groupdict()
            tid = d["trade_id"]
            if d["source"] == "d_neg_ev_control_shadow_only":
                continue
            d["net_pnl_pct"] = float(d.pop("pnl"))
            d["segment_key"] = f'{d["symbol"]}:{d["regime"]}:{d["side"]}'
            rows[tid] = d
            sources.setdefault(tid, []).append(fn)
    except Exception:
        pass

ordered = list(rows.values())
print("journal_files_scanned=", len(files))
print("dedup_real_canonical_updates=", len(ordered))
print("enough_for_exact_rolling100=", len(ordered) >= 100)
for r in ordered[-20:]:
    print(json.dumps(r, sort_keys=True))
Path("__OUT_JSON__").write_text(json.dumps({
    "journal_files_scanned": files,
    "rows": ordered,
    "row_sources": sources,
    "enough_for_exact_rolling100": len(ordered) >= 100,
}, indent=2))
PY

sed -i "s|__OUT_JSON__|$DEPLOY/reconstruction_rows.json|" "$DEPLOY/reconstruct_adaptive_dry_run.py"
python3 "$DEPLOY/reconstruct_adaptive_dry_run.py" | tee "$DEPLOY/reconstruction_assessment.txt"
```

Decision:
```text
If dedup_real_canonical_updates >= 100 and required row fields are complete:
  METHOD=RECONSTRUCT_FROM_JOURNALS
Else:
  METHOD=RESET_ACTIVE_ADAPTIVE_STATE_EMPTY
```

Write decision:

```bash
if grep -q "enough_for_exact_rolling100= True" "$DEPLOY/reconstruction_assessment.txt"; then
  echo "METHOD=RECONSTRUCT_FROM_JOURNALS" | tee "$DEPLOY/state_method.txt"
else
  echo "METHOD=RESET_ACTIVE_ADAPTIVE_STATE_EMPTY" | tee "$DEPLOY/state_method.txt"
fi
```

Do not apply yet. Report the method and update count. Deployment continues only after this method is explicitly recorded in the run output.

---

# Phase 3 — Prepare clean local checkout without overwriting runtime state

Because local checkout has runtime changes and previously blocked pulls, do not use a blind pull.

Backup and remove only Git merge blockers **after open_positions=0**:

```bash
cd /opt/CryptoMaster_srv
DEPLOY=$(ls -dt /root/cryptomaster_o1a1e_deploy_* | head -1)

cp -a data/paper_open_positions.json "$DEPLOY/paper_open_positions.final_before_update.json"
cp -a server_local_backups/paper_adaptive_learning_state.json "$DEPLOY/adaptive_state.final_before_update.json"

git fetch origin main

# Keep local runtime files outside repo; do not delete backups.
mkdir -p "$DEPLOY/local_runtime_removed_from_checkout"
mv data/paper_open_positions.json "$DEPLOY/local_runtime_removed_from_checkout/paper_open_positions.json" 2>/dev/null || true
mv server_local_backups/paper_adaptive_learning_state.json "$DEPLOY/local_runtime_removed_from_checkout/paper_adaptive_learning_state.json" 2>/dev/null || true

# Since remote no longer tracks these paths, fast-forward source checkout safely.
git pull --ff-only origin main
git rev-parse --short HEAD | tee "$DEPLOY/prod_head_after_pull.txt"

# Recreate runtime directories/files only from controlled state generation in next phase.
mkdir -p data server_local_backups
```

If pull is not a fast-forward or any tracked conflict appears, STOP and restore runtime files from `$DEPLOY/local_runtime_removed_from_checkout/` without restarting.

---

# Phase 4 — Build trustworthy active adaptive state file under corrected code

Do not copy the contaminated state back.

## Option A: exact journal reconstruction if METHOD=RECONSTRUCT_FROM_JOURNALS

Implement/use a one-off local script under `$DEPLOY`, not committed, that creates a new state matching the corrected O1A1B schema using only deduplicated real journal rows:
- ordinary rolling20/50/100 from last real canonical updates;
- lifetime metrics either from the available reconstructed evidence only, explicitly marked as reconstructed scope, or reset to reconstructed row count;
- segment weights rebuilt only from real rows under current policy, or reset to `{}` if deterministic rebuild is unavailable;
- qualification reset fresh: `qualification_n=0`, empty window/seen IDs, `operator_unlock=False`.

The output must be written first to:
```text
$DEPLOY/adaptive_state.reconstructed.candidate.json
```
and summarized before copying into:
```text
server_local_backups/paper_adaptive_learning_state.json
```

## Option B: reset active adaptive state if METHOD=RESET_ACTIVE_ADAPTIVE_STATE_EMPTY

Create no synthetic history. Allow corrected code to initialize fresh state after restart, with:
```text
rolling20=[]
rolling50=[]
rolling100=[]
segment_weights={}
lifecycle=PAPER_COLLECTING
qualification_n=0
qualification_window=[]
qualification_trade_ids_seen=[]
operator_unlock=False
```

Preserve contaminated state only in `$DEPLOY` backup.

## Position state

Since deployment is allowed only with `open_positions=0`, restore an empty paper positions file in the expected existing format. Use the previously captured file if it is already valid and empty; do not introduce schema guesses.

```bash
python3 - <<'PY'
import json
from pathlib import Path
src = sorted(Path("/root").glob("cryptomaster_o1a1e_deploy_*/paper_open_positions.final_before_update.json"))[-1]
d=json.loads(src.read_text())
positions=d if isinstance(d,list) else d.get("positions", d.get("open_positions", []))
if isinstance(positions,dict): positions=list(positions.values())
assert len(positions)==0, "Not empty; stop"
Path("/opt/CryptoMaster_srv/data/paper_open_positions.json").write_text(json.dumps(d, indent=2))
print("restored_empty_positions_from=", src)
PY
```

---

# Phase 5 — Test corrected production checkout safely before service restart

Remote should now include test isolation, so testing must not alter the newly created active state. Verify by hash.

```bash
cd /opt/CryptoMaster_srv
DEPLOY=$(ls -dt /root/cryptomaster_o1a1e_deploy_* | head -1)
REAL_STATE=server_local_backups/paper_adaptive_learning_state.json

sha256sum "$REAL_STATE" 2>/dev/null | tee "$DEPLOY/state_hash.before_tests_corrected_code.txt" || true

./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee "$DEPLOY/fullsuite_corrected_production_checkout.txt"

sha256sum "$REAL_STATE" 2>/dev/null | tee "$DEPLOY/state_hash.after_tests_corrected_code.txt" || true
diff -u "$DEPLOY/state_hash.before_tests_corrected_code.txt" "$DEPLOY/state_hash.after_tests_corrected_code.txt"

grep -E "^FAILED |^ERROR " "$DEPLOY/fullsuite_corrected_production_checkout.txt" || true
tail -40 "$DEPLOY/fullsuite_corrected_production_checkout.txt"
```

Acceptance:
```text
926 passed, 0 failures, 0 errors, 0 warnings
adaptive state hash unchanged during tests
```

If test fails or hash changes, do not restart. Restore/hold and report.

---

# Phase 6 — Restart PAPER service only after all gates pass

```bash
cd /opt/CryptoMaster_srv
DEPLOY=$(ls -dt /root/cryptomaster_o1a1e_deploy_* | head -1)

sudo systemctl restart cryptomaster
sleep 5

PID=$(systemctl show cryptomaster -p MainPID --value)
echo "$PID" | tee "$DEPLOY/pid_after_restart.txt"
sudo systemctl status cryptomaster --no-pager -l | tee "$DEPLOY/service_after_restart.txt"

sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat | grep -E \
"PAPER_QUALIFICATION_EPOCH_STARTED|PAPER_QUALIFICATION_SKIP|PAPER_QUALIFICATION_UPDATE|PAPER_ADAPTIVE_POLICY_READ|PAPER_POLICY_ADAPTATION|PAPER_ADAPTIVE_STARVATION|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL|REAL_READINESS_CHECK|REAL_READY|Firebase initialized|Model state restored|Traceback|UnboundLocalError" \
  | tee "$DEPLOY/runtime_acceptance_initial.txt"
```

Required initially:
```text
HEAD=97e6777 clean code
service active
no Traceback / UnboundLocalError
operator_unlock remains False
REAL_READY not activated
qualification epoch starts fresh at n=0, or loads fresh reset state
```

Continue monitoring until:
```text
one new eligible paper_adaptive_recovery WIN/LOSS/FLAT close
→ PAPER_QUALIFICATION_UPDATE qualification_n=1

one new D_NEG close if it occurs
→ PAPER_LEARNING_SHADOW_SKIP
→ no PAPER_QUALIFICATION_UPDATE / canonical update for that D_NEG trade
```

---

# Required final report

```text
REMOTE CLEAN HEAD VERIFIED:
PRODUCTION BACKUP DIRECTORY:
OPEN POSITIONS BEFORE UPDATE:
JOURNAL RECONSTRUCTION ROW COUNT:
STATE METHOD CHOSEN: RECONSTRUCT_FROM_JOURNALS | RESET_ACTIVE_ADAPTIVE_STATE_EMPTY
CONTAMINATED STATE PRESERVED AT:
PRODUCTION HEAD AFTER CONTROLLED PULL:
ACTIVE STATE CANDIDATE SUMMARY:
CORRECTED-CODE FULL SUITE:
ACTIVE STATE HASH UNCHANGED BY TESTS:
SERVICE RESTARTED ONLY AFTER GATES:
NEW PID:
POST-RESTART QUALIFICATION EPOCH/N:
POST-RESTART PAPER POLICY READ:
POST-RESTART FIRST ELIGIBLE QUALIFICATION UPDATE:
D_NEG NON-REGRESSION:
REAL_READY STATUS:
```
