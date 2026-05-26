# Claude Code — P1.1AP-O1A1B Hard Verification + Safety Correction

## Objective

O1A1 reports the right corrective direction, but it is **not accepted** until test isolation, persisted-state integrity, qualification provenance, and the readiness boundary are directly proven.

Expected HEAD:
```text
3283ba1 P1.1AP-O1A1
previous defective O1A: f49e493
```

Do not tune EV/ECON_BAD/cost-edge/TP/SL/timeout, do not modify live/real execution, do not allow negative-EV canonical learning, do not change D_NEG shadow isolation.

## Critical issue requiring correction

O1A1 reports:
```text
Rolling20 PF gate adjusted: < 1.00 (was <= 1.00) to allow breakeven
```

This is an unauthorized easing of REAL readiness. Restore the strict boundary:
```python
qualification_recent20_pf <= 1.00  # remains not eligible
```

Add a direct test: with `qualification_n >= 100`, `operator_unlock=True`, all other gates passing, and recent qualification PF exactly `1.00`, readiness remains `eligible=False`.

## Phase 0 — Preserve evidence before tests

```bash
cd /opt/CryptoMaster_srv
TS=$(date -u +%Y%m%dT%H%M%SZ)
AUDIT="server_local_backups/o1a1b_audit_$TS"
mkdir -p "$AUDIT"

git rev-parse --short HEAD | tee "$AUDIT/head.txt"
git status --short | tee "$AUDIT/git_status.txt"
git log --oneline -12 | tee "$AUDIT/git_log.txt"
git --no-pager diff --name-status f49e493..HEAD | tee "$AUDIT/diff_names.txt"
git --no-pager diff --stat f49e493..HEAD | tee "$AUDIT/diff_stat.txt"

cp -a server_local_backups/paper_adaptive_learning_state.json "$AUDIT/paper_adaptive_learning_state.before_validation.json" 2>/dev/null || true
cp -a data/paper_open_positions.json "$AUDIT/paper_open_positions.before_validation.json" 2>/dev/null || true
sha256sum server_local_backups/paper_adaptive_learning_state.json 2>/dev/null | tee "$AUDIT/state_hash_before_tests.txt" || true

PID=$(systemctl show cryptomaster -p MainPID --value)
echo "$PID" | tee "$AUDIT/pid.txt"
sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat > "$AUDIT/journal_current_pid.log"
echo "AUDIT=$AUDIT"
```

Do not run pytest before confirming test state isolation exists in source.

## Phase 1 — Inspect O1A1 implementation

```bash
grep -R "state_file\|_STATE_FILE\|qualification_epoch_id\|qualification_started_at\|qualification_eligible\|qualification_opened_at\|qualification_trade_ids_seen\|_try_increment_qualification\|check_real_readiness\|PAPER_ADAPTIVE_STARVATION\|qual_recent" -n \
  src/services tests scripts 2>/dev/null | head -1000

git --no-pager show --stat --oneline HEAD
git --no-pager diff --name-status f49e493..HEAD
```

Prove:
1. `PaperAdaptiveLearning(state_file=...)` or equivalent is used by every adaptive-learning test.
2. Singleton/global sampler state is reset between tests.
3. Qualification requires position-open provenance in the active epoch:
   ```text
   qualification_eligible=True
   qualification_epoch_id == active epoch
   qualification_opened_at >= qualification_started_at
   ```
4. `WIN`, `LOSS`, and economically valid `FLAT` closes qualify; D_NEG/quarantine/shadow/TIMEOUT_NO_PRICE do not.
5. Duplicate `trade_id` increments qualification only once.
6. All REAL readiness gates, including recent PF/expectancy, symbol diversity and concentration, read `qualification_window` only.

If any proof fails, implement only the missing correctness fix in allowed source/test files.

## Phase 2 — Verify “production state cleaned and fresh”

O1A tests previously wrote fabricated records to the real state file. Do not accept a cleanup claim without proof.

```bash
find server_local_backups -maxdepth 4 -type f \
  \( -iname '*paper_adaptive_learning_state*' -o -path '*o1a*' \) \
  -printf '%TY-%Tm-%Td %TH:%TM:%TS %p\n' | sort | tail -120
```

Summarize current and relevant backup states:
```bash
./venv/bin/python - <<'PY'
import json, glob, os
paths = sorted(set(glob.glob("server_local_backups/**/*paper_adaptive_learning_state*.json", recursive=True)))
for p in paths[-20:]:
    try:
        d=json.load(open(p))
        text=json.dumps(d)
        print("FILE", p)
        print(" lifetime_n=", d.get("lifetime_n"), "rolling100=", len(d.get("rolling100", [])),
              "qualification_n=", d.get("qualification_n"), "qual_window=", len(d.get("qualification_window", [])),
              "unlock=", d.get("operator_unlock"))
        print(" obvious_test_ids=", any(x in text for x in ["eligible_test","recovery_test",'\"t0\"','\"t1\"']))
    except Exception as e:
        print("FILE", p, "ERROR", e)
PY
```

Rules:
- Invalid O1A qualification evidence may be reset to a new O1A1 epoch with `qualification_n=0`, empty qualification window/seen IDs and `operator_unlock=False`.
- Ordinary rolling/lifetime/segment policy history must not be erased unless reconstructed from verified production journals or explicitly reported as uncertain/data loss.
- Any apply reconciliation script must default dry-run, make a backup, and never touch Firebase.

## Phase 3 — Run tests only after isolation is confirmed

```bash
REAL_STATE=server_local_backups/paper_adaptive_learning_state.json
sha256sum "$REAL_STATE" 2>/dev/null | tee /tmp/o1a1b_hash_before_tests.txt || true

./venv/bin/python -m pytest -q tests/test_p11ap_o1a_completion.py
sha256sum "$REAL_STATE" 2>/dev/null | tee /tmp/o1a1b_hash_after_o1a.txt || true
diff -u /tmp/o1a1b_hash_before_tests.txt /tmp/o1a1b_hash_after_o1a.txt

./venv/bin/python -m pytest -q \
  tests/test_p11ap_o1a_completion.py \
  tests/test_paper_adaptive_learning.py \
  tests/test_p11ap_n2_recovery_admission.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_v10_13u_patches.py
sha256sum "$REAL_STATE" 2>/dev/null | tee /tmp/o1a1b_hash_after_targeted.txt || true
diff -u /tmp/o1a1b_hash_before_tests.txt /tmp/o1a1b_hash_after_targeted.txt

./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_o1a1b_fullsuite.txt
sha256sum "$REAL_STATE" 2>/dev/null | tee /tmp/o1a1b_hash_after_fullsuite.txt || true
diff -u /tmp/o1a1b_hash_before_tests.txt /tmp/o1a1b_hash_after_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_o1a1b_fullsuite.txt || true
tail -40 /tmp/p11ap_o1a1b_fullsuite.txt
```

Acceptance:
```text
all O1A/O1A1 tests pass
full server-safe suite >=934 passed, 0 failures, 0 errors, 0 warnings
real adaptive state hash unchanged by pytest
```

## Phase 4 — Starvation telemetry proof

Confirm emitted counters reflect actual PAPER rejection/admission flow:
```text
negative-only PAPER window:
  negative_ev_rejects>0 reason=no_positive_ev_candidates

EV-positive recovery window:
  positive_candidates>0 policy_reads>0/admitted_recovery>0
  reason=learning_active or awaiting_samples
```

Fix logging scope only if it still emits `negative_ev_rejects=0` next to observed negative PAPER rejects. Do not change routing.

## Commit if correction needed

Do not stage runtime/backup files:
```bash
git status --short
git diff --name-status
git diff --stat

git add <allowed source/test/script files only>
git commit -m "P1.1AP-O1A1B: Restore readiness guard and prove adaptive state isolation"
git push origin main
```

## Post-deploy validation

After checking `open_positions`, restart/deploy only clean tested code. Then:

```bash
PID=$(systemctl show cryptomaster -p MainPID --value)
sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat | grep -E \
"PAPER_QUALIFICATION_EPOCH_STARTED|PAPER_QUALIFICATION_SKIP|PAPER_QUALIFICATION_UPDATE|PAPER_ADAPTIVE_POLICY_READ|PAPER_POLICY_ADAPTATION|PAPER_ADAPTIVE_STARVATION|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL|REAL_READINESS_CHECK|REAL_READY|Traceback|UnboundLocalError"
```

Required in production:
```text
qualification epoch is valid/reset with operator_unlock=False
pre-epoch/unproven close does not increment qualification
new post-epoch WIN/LOSS/FLAT eligible close increments exactly once
D_NEG close does not increment or canonical-learn
REAL_READINESS_CHECK stays eligible=False until 100 qualified closes + strict gates + operator unlock
```

## Return report

```text
O1A1 COMMIT/SCOPE:
READINESS RELAXATION FOUND/FIXED:
TEST ISOLATION PROOF:
REAL STATE HASH BEFORE/AFTER TESTS:
STATE BACKUP/RECONCILIATION EVIDENCE:
ORDINARY ADAPTIVE HISTORY PRESERVED OR UNCERTAIN:
QUALIFICATION EPOCH STATUS:
STARVATION TELEMETRY STATUS:
TARGETED TEST RESULTS:
FULL SUITE:
COMMIT/PUSH IF FIXED:
POST-DEPLOY QUALIFICATION EVIDENCE:
D_NEG NON-REGRESSION:
REAL_READY STATUS:
```
