# Claude Code — P1.1AP-O1A1G: Eliminate Remaining Full-Suite Runtime-State Writes

## Incident status

O1A1F has been pushed and production source is now at:

```text
HEAD=791d16c P1.1AP-O1A1F: Fully isolate PAPER adaptive tests from runtime state
origin/main=791d16c
forbidden tracked paths: none
service: MUST REMAIN STOPPED
```

O1A1F successfully fixed the directly targeted O1A test file:

```text
tests/test_p11ap_o1a_completion.py run 1: 23 passed
tests/test_p11ap_o1a_completion.py run 2: 23 passed
server_local_backups/paper_adaptive_learning_state.json: not created
data/paper_open_positions.json hash: unchanged
```

However, the full server-safe suite on the same code proves there are **additional writer tests outside `test_p11ap_o1a_completion.py`**:

```text
full suite: 935 passed in 4.76s
FAIL: full suite created server_local_backups/paper_adaptive_learning_state.json
FAIL: full suite changed data/paper_open_positions.json

paper positions hash before suite:
  44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a

paper positions hash after suite:
  923c63ce4e5a4d8c4c30da685da61a3f74674b2f6eb39ec27fa9b9d0f560c87d
```

Therefore:

```text
Functional pytest assertions pass, but full-suite test isolation is still incomplete.
Production service must not restart until all full-suite runtime-state writes are isolated.
```

Do not change economics or learning behavior to solve a test contamination problem.

---

# Hard constraints

On production `/opt/CryptoMaster_srv`:

```text
DO NOT start cryptomaster.
DO NOT run pytest again.
DO NOT use runtime files produced by the failed full-suite run.
DO NOT overwrite incident backups.
```

All investigation, code changes and testing must occur in a clean clone outside production.

Never modify:

```text
EV/ECON_BAD/cost-edge thresholds
TP/SL/timeout geometry
PAPER adaptive policy economics
D_NEG shadow-only isolation
qualification readiness gates (`recent PF <= 1.00` must still block)
operator_unlock default False
live/real trading path
Firebase/Android contracts
```

Allowed goal only:

```text
Tests must not create or mutate production-relative runtime files.
```

---

# Phase 0 — Preserve production failure evidence and restore stopped clean baseline

On production, read-only/move-only while service remains stopped:

```bash
cd /opt/CryptoMaster_srv
export DEPLOY="/root/cryptomaster_o1a1e_deploy_20260525T122318Z"
FAIL="$DEPLOY/fullsuite_side_effect_after_o1a1f"
mkdir -p "$FAIL"

sudo systemctl status cryptomaster --no-pager -l | tee "$FAIL/service.must_remain_stopped.txt"
git rev-parse --short HEAD | tee "$FAIL/head.txt"
git status --short | tee "$FAIL/git_status.txt"

cp -a data/paper_open_positions.json "$FAIL/paper_open_positions.created_by_fullsuite.json" 2>/dev/null || true
cp -a server_local_backups/paper_adaptive_learning_state.json "$FAIL/adaptive_state.created_by_fullsuite.json" 2>/dev/null || true
cp -a "$DEPLOY/fullsuite.o1a1f.production_checkout.txt" "$FAIL/fullsuite_935pass_but_side_effect.txt" 2>/dev/null || true

sha256sum data/paper_open_positions.json 2>/dev/null | tee "$FAIL/paper_positions_hash.side_effect.txt" || true
sha256sum server_local_backups/paper_adaptive_learning_state.json 2>/dev/null | tee "$FAIL/adaptive_state_hash.side_effect.txt" || true

# Preserve side effects, then restore the intended stopped pre-start baseline.
mkdir -p "$FAIL/moved_side_effect_runtime"
mv data/paper_open_positions.json "$FAIL/moved_side_effect_runtime/paper_open_positions.json" 2>/dev/null || true
mv server_local_backups/paper_adaptive_learning_state.json "$FAIL/moved_side_effect_runtime/paper_adaptive_learning_state.json" 2>/dev/null || true

mkdir -p data server_local_backups
cp -a "$DEPLOY/paper_open_positions.empty.after_stop.json" data/paper_open_positions.json
rm -f server_local_backups/paper_adaptive_learning_state.json

sha256sum data/paper_open_positions.json | tee "$FAIL/paper_positions_hash.restored_empty.txt"
test ! -e server_local_backups/paper_adaptive_learning_state.json \
  && echo "adaptive_state_restored_baseline=ABSENT" | tee "$FAIL/adaptive_state.restored_baseline.txt"

# DO NOT RUN TESTS HERE. DO NOT START SERVICE.
```

Expected:

```text
service inactive/dead
paper positions restored hash = 44136fa...
adaptive state ABSENT
```

---

# Phase 1 — Create a new clean clone at O1A1F

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
FIX="/root/CryptoMaster_o1a1g_fix_$TS"
git clone --branch main https://github.com/Sanchez-78/crypto-trading-bot.git "$FIX"
cd "$FIX"

git rev-parse --short HEAD
git log --oneline -8
git ls-tree -r --name-only HEAD | grep -E \
"(^server_local_backups/|^data/paper_open_positions\.json$|^data/research/|^logs_extracted_tmp/|^\.claude/worktrees/)" \
  && { echo "STOP: forbidden path returned to remote"; exit 1; } || true
```

Expected:

```text
HEAD=791d16c
```

Use/create a clone-local Python environment only. Never test in production checkout.

---

# Phase 2 — Find exact remaining writer test modules

## A. Static scan

```bash
cd "$FIX"

grep -R "paper_adaptive_learning_state\.json\|paper_open_positions\.json\|_STATE_FILE\|_STATE_PATH\|PaperAdaptiveLearning()\|PaperAdaptiveLearning(\|open_paper_position\|save.*paper\|_save_state\|write_text\|json.dump" -n \
  tests VERIFICATION_* src/services 2>/dev/null \
  | tee /tmp/o1a1g_static_runtime_writer_scan.txt
```

## B. Per-test-file side-effect detector

Run every collected test file separately in the clean clone, resetting sentinels before each module. This identifies modules that create adaptive state or mutate paper positions.

```bash
cd "$FIX"
cat > /tmp/o1a1g_find_runtime_writer_modules.sh <<'SH'
#!/usr/bin/env bash
set -u
ROOT="$PWD"
REPORT=/tmp/o1a1g_runtime_writer_modules.txt
: > "$REPORT"

python3 -m pytest --collect-only -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>/dev/null \
  | sed -n 's/^\([^: ][^:]*\.py\)::.*$/\1/p' \
  | sort -u > /tmp/o1a1g_collected_test_files.txt

while IFS= read -r T; do
  [ -z "$T" ] && continue
  cd "$ROOT" || exit 1
  rm -rf server_local_backups
  mkdir -p data
  printf '{}\n' > data/paper_open_positions.json
  BEFORE=$(sha256sum data/paper_open_positions.json | awk '{print $1}')

  python3 -m pytest -q "$T" >/tmp/o1a1g_one_module.out 2>&1
  RC=$?

  AFTER=$(sha256sum data/paper_open_positions.json 2>/dev/null | awk '{print $1}')
  ADAPTIVE="no"
  [ -e server_local_backups/paper_adaptive_learning_state.json ] && ADAPTIVE="YES"
  POS_CHANGED="no"
  [ "$BEFORE" != "$AFTER" ] && POS_CHANGED="YES"

  if [ "$ADAPTIVE" = "YES" ] || [ "$POS_CHANGED" = "YES" ]; then
    echo "WRITER module=$T rc=$RC adaptive_created=$ADAPTIVE positions_changed=$POS_CHANGED" | tee -a "$REPORT"
    cp /tmp/o1a1g_one_module.out "/tmp/o1a1g_$(echo "$T" | tr '/.' '__').out"
  fi
done < /tmp/o1a1g_collected_test_files.txt

cat "$REPORT"
SH
chmod +x /tmp/o1a1g_find_runtime_writer_modules.sh
/tmp/o1a1g_find_runtime_writer_modules.sh
```

## C. If no module reproduces alone, detect order interaction

If the full suite mutates files but no individual file does, run groups/bisect until writer sequence is identified. Do not patch blindly.

Report:

```text
EXACT WRITER MODULES:
EXACT RUNTIME PATHS WRITTEN:
IS WRITE MODULE-LOCAL OR ORDER-DEPENDENT:
```

---

# Phase 3 — Fix isolation globally and minimally

The correct fix is likely a shared `tests/conftest.py` autouse fixture or existing global fixture extension, not one-by-one ad hoc patches.

Required fixture behavior for the whole server-safe suite:

```text
- redirect adaptive learner state path to tmp_path per test;
- redirect paper open positions persistence path to tmp_path per test;
- reset module singleton `_learner` before and after each test;
- reset `_ADAPTIVE_STARVATION_STATE` and mutable sampler/open-position globals;
- never create or alter repository-relative runtime state files.
```

If modules store paths as constants, monkeypatch the exact constants used by writers. If dependency injection is unavailable for paper position state, add only minimal testability injection to the persistence service without changing production default behavior.

## Explicit full-suite guard test

Add a regression/sentinel test or fixture assertion that fails if any test attempts to touch repository-relative:

```text
server_local_backups/paper_adaptive_learning_state.json
data/paper_open_positions.json
```

Prefer fixture isolation plus an end-of-session guard if feasible.

Do not fix passing tests by deleting them or weakening assertions. Keep the collected legitimate total `>=935`.

---

# Phase 4 — Validate in clean clone only

Prepare baseline:

```bash
cd "$FIX"
rm -rf server_local_backups data/paper_open_positions.json 2>/dev/null || true
mkdir -p data
printf '{}\n' > data/paper_open_positions.json
BASE_HASH=$(sha256sum data/paper_open_positions.json | awk '{print $1}')
echo "$BASE_HASH" | tee /tmp/o1a1g_positions_hash_before.txt
```

Run targeted O1A1F test twice:

```bash
python3 -m pytest -q tests/test_p11ap_o1a_completion.py | tee /tmp/o1a1g_o1a_run1.txt
python3 -m pytest -q tests/test_p11ap_o1a_completion.py | tee /tmp/o1a1g_o1a_run2.txt
```

Then full suite twice:

```bash
python3 -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research | tee /tmp/o1a1g_fullsuite_run1.txt

python3 -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research | tee /tmp/o1a1g_fullsuite_run2.txt

test ! -e server_local_backups/paper_adaptive_learning_state.json \
  || { echo "FAIL: full suite created adaptive runtime state"; exit 1; }

AFTER_HASH=$(sha256sum data/paper_open_positions.json | awk '{print $1}')
test "$BASE_HASH" = "$AFTER_HASH" \
  || { echo "FAIL: full suite changed paper positions"; exit 1; }

tail -20 /tmp/o1a1g_fullsuite_run1.txt
tail -20 /tmp/o1a1g_fullsuite_run2.txt
```

Acceptance:

```text
targeted test file passes twice
full server-safe suite passes twice
>=935 passed on each full run
0 failures, 0 errors, 0 warnings
no adaptive runtime state file created
paper positions sentinel hash unchanged
```

---

# Phase 5 — Commit and push

Allowed changes only:

```text
tests/conftest.py or existing shared fixture file
identified writer test files
minimal production testability dependency-injection only if unavoidable
```

Forbidden:

```text
economic/runtime policy behavior
state files
backups/research/logs
thresholds
D_NEG/live/real changes
```

```bash
cd "$FIX"
git status --short
git diff --name-status
git diff --stat

git add <allowed files only>
git commit -m "P1.1AP-O1A1G: Isolate full PAPER test suite from runtime files"
git push origin main

git rev-parse --short HEAD
git ls-tree -r --name-only HEAD | grep -E \
"(^server_local_backups/|^data/paper_open_positions\.json$|^data/research/|^logs_extracted_tmp/|^\.claude/worktrees/)" \
  && { echo "STOP: forbidden tracked artifact reintroduced"; exit 1; } || true
```

---

# Phase 6 — Production redeploy after approval only

Do not perform in this task unless explicitly approved after reporting clean-clone proof.

Production is already at `791d16c` and service is stopped. Its active runtime baseline must remain:

```text
data/paper_open_positions.json = known empty hash 44136fa...
server_local_backups/paper_adaptive_learning_state.json = ABSENT
METHOD=RESET_ACTIVE_ADAPTIVE_STATE_EMPTY
```

After approved pull of O1A1G:
- run full suite once on stopped production checkout;
- verify no adaptive state is created;
- verify empty paper positions hash unchanged;
- only then start PAPER service.

## Final report

```text
PRODUCTION SERVICE REMAINS STOPPED:
PRODUCTION CLEAN RUNTIME BASELINE HASH:
EXACT REMAINING WRITER TEST MODULES:
ROOT CAUSE OF FULL-SUITE SIDE EFFECT:
FILES CHANGED:
RUNTIME LOGIC UNCHANGED:
CLEAN-CLONE TARGETED RUN1/RUN2:
CLEAN-CLONE FULL SUITE RUN1/RUN2:
NO RUNTIME FILE SIDE EFFECT PROOF:
COMMIT/PUSH:
REMOTE FORBIDDEN PATH CHECK:
CONTROLLED PRODUCTION START STILL PENDING:
```
