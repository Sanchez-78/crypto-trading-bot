# P1.1AP-O1A1F — Emergency: fully isolate PAPER adaptive tests before restart

## Incident

Production was pulled to `97e6777`, but mandatory pre-start tests failed and changed runtime files. The service was then started despite the explicit stop condition.

Confirmed:

```text
HEAD after pull: 97e6777
Before tests: adaptive state ABSENT
Before tests paper positions hash:
  44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a

Pre-start full suite:
  5 failed, 930 passed

After tests:
  adaptive state EXISTS — tests created runtime state
  paper positions hash changed to:
  006caab476d2f70286301fdf105019a03b34d5c86cf827c9768327563281f1c5
```

Invalid service start proof:

```text
PID=1446134
[PAPER_POSITION_QUARANTINED]
trade_id=paper_3a2428a90414 symbol=ADAUSDT
entry=1.23400000 exit=0.24485000 net_pnl_pct=-80.3380
```

This is test-fixture/runtime contamination. Nothing learned after PID `1446134` may be treated as valid acceptance evidence.

## Hard rules

On `/opt/CryptoMaster_srv`:

```text
STOP service immediately.
Do not run pytest again.
Do not restart until a clean fix is tested and deployed.
Do not alter EV/thresholds/TP-SL/cost-edge/ECON_BAD.
Do not alter D_NEG isolation or live/real behavior.
operator_unlock must remain False.
```

All coding and tests must happen in a separate clean clone under `/root`, never in the production checkout.

---

## Phase 0 — Emergency stop and evidence capture

```bash
cd /opt/CryptoMaster_srv
export DEPLOY="/root/cryptomaster_o1a1e_deploy_20260525T122318Z"
FAIL="$DEPLOY/failed_prestart_gate_pid_1446134"
mkdir -p "$FAIL"

sudo systemctl stop cryptomaster
sudo systemctl status cryptomaster --no-pager -l | tee "$FAIL/service.after_emergency_stop.txt"

git rev-parse --short HEAD | tee "$FAIL/head.txt"
git status --short | tee "$FAIL/git_status.txt"
sudo journalctl -u cryptomaster _PID=1446134 --no-pager -o cat > "$FAIL/journal_pid_1446134_invalid_runtime.txt"

cp -a data/paper_open_positions.json "$FAIL/paper_open_positions.invalid.json" 2>/dev/null || true
cp -a server_local_backups/paper_adaptive_learning_state.json "$FAIL/adaptive_state.invalid.json" 2>/dev/null || true
cp -a "$DEPLOY/fullsuite.corrected_code.txt" "$FAIL/fullsuite_5fail_930pass.txt" 2>/dev/null || true

sha256sum data/paper_open_positions.json 2>/dev/null | tee "$FAIL/paper_positions_hash.invalid.txt" || true
sha256sum server_local_backups/paper_adaptive_learning_state.json 2>/dev/null | tee "$FAIL/adaptive_state_hash.invalid.txt" || true
```

Leave service stopped.

---

## Phase 1 — Create a clean fix clone

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
FIX="/root/CryptoMaster_o1a1f_fix_$TS"
git clone --branch main https://github.com/Sanchez-78/crypto-trading-bot.git "$FIX"
cd "$FIX"
git rev-parse --short HEAD
git log --oneline -8
```

Expected starting HEAD:

```text
97e6777
```

Inspect contamination paths:

```bash
grep -R "PaperAdaptiveLearning()\|PaperAdaptiveLearning(\|state_file\|paper_open_positions\|open_paper_position\|maybe_open_training_sample\|_learner\|get_learner\|get_rde_instance\|record_close" -n   tests/test_p11ap_o1a_completion.py   tests/test_paper_adaptive_learning.py   tests/test_p11ap_n2_recovery_admission.py   src/services/paper_adaptive_learning.py   src/services/paper_training_sampler.py   src/services/paper_trade_executor.py | head -1000
```

## Required corrections

### A. Isolate every adaptive learner test

Failure traces prove that tests still contain default-path use such as:

```python
learner = PaperAdaptiveLearning()
```

Every adaptive test must use a temp state file, e.g.:

```python
learner = PaperAdaptiveLearning(state_file=str(tmp_path / "adaptive_state.json"))
```

Also patch/reset module singletons and mutable sampler globals per test:
- adaptive singleton `_learner`;
- starvation counters;
- sampler caps/rate/probe state.

No test may create or modify:

```text
server_local_backups/paper_adaptive_learning_state.json
```

### B. Isolate paper position persistence

Tests changed `data/paper_open_positions.json`. Any test exercising `open_paper_position()` or close/state save must monkeypatch its persistence path to `tmp_path`.

Add a sentinel regression test proving an existing `data/paper_open_positions.json` is unchanged after the tested lifecycle.

### C. Fix the five failed tests at the correct layer

```text
test_3:
  patch the learner/singleton actually read by maybe_open_training_sample;
  create a valid EV>0 recovery candidate satisfying existing gates.

test_5 and test_12:
  assert behavior where policy weights actually change; do not assume record_close()
  mutates segment_weight if the implementation applies weight during candidate policy read.

test_10:
  remove invalid `get_rde_instance` import;
  test live/real isolation through the actual mode guard/public path.

test_11:
  use isolated state and valid active-epoch provenance fields:
    qualification_eligible=True
    qualification_epoch_id=<current epoch>
    qualification_opened_at >= qualification_started_at
  assert exactly one qualification increment.
```

Do not weaken runtime logic merely to make tests pass.

### D. Preserve safety logic

Keep:

```text
qualification recent PF <= 1.00 → eligible=False
WIN/LOSS/FLAT post-epoch closes qualify
D_NEG/quarantine/shadow/TIMEOUT_NO_PRICE do not qualify
operator_unlock=False by default
```

---

## Phase 2 — Add explicit no-runtime-write tests

Add tests proving:

1. Adaptive learner tests never create/change `server_local_backups/paper_adaptive_learning_state.json`.
2. Paper lifecycle tests never create/change `data/paper_open_positions.json`.
3. Running `tests/test_p11ap_o1a_completion.py` twice is stable and state-isolated.
4. Each qualification case begins at `qualification_n=0`.
5. Valid post-epoch `FLAT` qualifies; D_NEG does not.

Allowed files:

```text
tests/test_p11ap_o1a_completion.py
tests/test_paper_adaptive_learning.py
tests/test_p11ap_n2_recovery_admission.py only if required
minimal source test-hook/dependency-injection correction only if no existing hook can isolate position state
```

Forbidden changes:

```text
runtime economics, thresholds, order paths, state data files, Firebase/Android contracts
```

---

## Phase 3 — Validate only in clean clone

```bash
cd "$FIX"
rm -rf server_local_backups data/paper_open_positions.json 2>/dev/null || true
mkdir -p data

python3 -m pytest -q tests/test_p11ap_o1a_completion.py 2>&1 | tee /tmp/o1a1f_o1a_run1.txt
python3 -m pytest -q tests/test_p11ap_o1a_completion.py 2>&1 | tee /tmp/o1a1f_o1a_run2.txt

test ! -e server_local_backups/paper_adaptive_learning_state.json   || { echo "FAIL: adaptive runtime state created by tests"; exit 1; }

test ! -e data/paper_open_positions.json   || { echo "FAIL: paper positions file created by tests"; exit 1; }

python3 -m pytest -q   --ignore=VERIFICATION_V10_13X   --ignore=venv   --ignore=server_local_backups   --ignore=data/archive   --ignore=data/research 2>&1 | tee /tmp/p11ap_o1a1f_fullsuite_clean_clone.txt

test ! -e server_local_backups/paper_adaptive_learning_state.json   || { echo "FAIL: adaptive runtime state created by full suite"; exit 1; }

test ! -e data/paper_open_positions.json   || { echo "FAIL: paper positions created by full suite"; exit 1; }

grep -E "^FAILED |^ERROR " /tmp/p11ap_o1a1f_fullsuite_clean_clone.txt || true
tail -45 /tmp/p11ap_o1a1f_fullsuite_clean_clone.txt
```

Acceptance:

```text
test_p11ap_o1a_completion.py passes twice
full server-safe suite >=935 passed, 0 failures, 0 errors, 0 warnings
no runtime adaptive/position file created by tests
```

---

## Phase 4 — Commit/push only the isolation fix

```bash
cd "$FIX"
git status --short
git diff --name-status
git diff --stat

git add <allowed test files and strictly necessary testability source files only>
git commit -m "P1.1AP-O1A1F: Fully isolate PAPER adaptive tests from runtime state"
git push origin main

git rev-parse --short HEAD
git ls-tree -r --name-only HEAD | grep -E "(^server_local_backups/|^data/paper_open_positions\.json$|^data/research/|^logs_extracted_tmp/|^\.claude/worktrees/)"   && { echo "ERROR: forbidden paths reintroduced"; exit 1; } || true
```

---

## Phase 5 — Controlled redeploy only after clean pass

Production remains stopped. Preserve invalid PID `1446134` evidence. Pull the new clean fix only after Phase 3/4 pass.

Before any restart, reinitialize:

```text
data/paper_open_positions.json = valid empty schema
server_local_backups/paper_adaptive_learning_state.json = ABSENT
METHOD=RESET_ACTIVE_ADAPTIVE_STATE_EMPTY
```

Run full suite on the corrected production checkout. It must not create either runtime file or modify empty positions. Only then start PAPER service and validate:

```text
fresh qualification epoch n=0
operator_unlock=False
REAL_READY not activated
new eligible recovery close increments qualification once
D_NEG remains shadow-only
```

## Report back

```text
PRODUCTION SERVICE STOPPED:
FAILED-GATE BACKUP PATH:
EXACT TESTS WRITING ADAPTIVE STATE:
EXACT TESTS WRITING PAPER POSITIONS:
TEST ISOLATION CHANGES:
RUNTIME LOGIC UNCHANGED:
CLEAN-CLONE O1A TEST FILE RUN1/RUN2:
CLEAN-CLONE FULL SUITE:
RUNTIME FILES ABSENT AFTER TESTS:
COMMIT/PUSH:
REMOTE FORBIDDEN PATH CHECK:
CONTROLLED REDEPLOY RESULT:
FRESH QUALIFICATION EPOCH:
D_NEG NON-REGRESSION:
REAL_READY STATUS:
```
