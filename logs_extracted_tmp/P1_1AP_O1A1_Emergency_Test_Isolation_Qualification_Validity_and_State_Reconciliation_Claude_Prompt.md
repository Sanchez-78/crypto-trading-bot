# CLAUDE CODE — P1.1AP-O1A1 EMERGENCY CORRECTION
## Isolate Tests From Production State, Repair Qualification Validity, and Reconcile Only Proven Contamination

## Status: O1A is deployed but NOT accepted

Deployed commit:

```text
f49e493 P1.1AP-O1A: Add paper policy evidence and readiness qualification provenance
previous accepted functional O1: a6ab55f
```

Current production service is PAPER-only and should keep running unless an actual crash occurs. Do **not** enable real trading. `operator_unlock=False` remains mandatory.

Do not roll back O1's working PAPER policy read unless unavoidable. Runtime proves it opens and learns `paper_adaptive_recovery` samples.

This patch must first prevent further state corruption, then repair correctness, then reconcile any already contaminated adaptive/qualification persisted state using only provable evidence.

---

# Confirmed evidence

## O1A commit scope

```text
M src/services/paper_adaptive_learning.py
M src/services/paper_training_sampler.py
A tests/test_p11ap_o1a_completion.py
M tests/test_paper_adaptive_learning.py

4 files changed, 846 insertions(+), 41 deletions(-)
```

## O1A test failure is real

Collected:

```text
22 tests collected in tests/test_p11ap_o1a_completion.py
```

Full server-safe suite result:

```text
10 failed, 924 passed in 4.92s
```

Failed tests:

```text
test_3_ev_positive_recovery_candidate_invokes_policy_read_and_returns_metadata
test_4_collect_bootstrap_for_segment_n_less_than_20_remains_under_caps
test_5_losing_segment_with_n_gte_20_pf_lt_0_80_causes_bounded_downweight
test_10_live_real_mode_does_not_use_apply_paper_adaptive_policy
test_11_recovery_lifecycle_preserves_paper_adaptive_recovery_through_close
test_12_same_ev_positive_candidate_receives_different_paper_size_after_learned_segment_changes
test_17_new_eligible_adaptive_paper_close_increments_qualification_n_exactly_once
test_20_qualification_n_gte_100_with_passing_metrics_but_operator_unlock_false_remains_blocked
test_21_qualification_n_gte_100_with_passing_metrics_and_operator_unlock_true_may_return_real_ready
test_22_state_persistence_and_reload_retain_qualification_evidence_safely
```

## Critical test-state contamination evidence

`PaperAdaptiveLearning()` loads and saves fixed production path:

```python
_STATE_FILE = "server_local_backups/paper_adaptive_learning_state.json"
```

The new tests instantiate `PaperAdaptiveLearning()` and call `record_close()`, which persists fabricated test trades to that live path.

Observed failure values prove cumulative shared state writes:

```text
qualification_n == 136 instead of 1
qualification_n == 551 instead of 1
qualification_n == 677 instead of 100
qualification_n == 827 instead of 50
```

Conclusion:

```text
Running O1A tests on the production checkout contaminated or may have contaminated
paper_adaptive_learning_state.json, including rolling windows, lifetime counters,
segment weights and qualification state.
```

Do not run any more tests before installing test-state isolation.

## Production runtime proves O1 functionality must be retained

Current PID:

```text
1436017
```

New O1A runtime shows:

```text
[PAPER_QUALIFICATION_EPOCH_STARTED]
reason=provenance_migration_existing_history_not_counted
existing_rolling100_n=100 qualification_n=0

[PAPER_ADAPTIVE_POLICY_READ]
symbol=XRPUSDT regime=BULL_TREND side=SELL ...
action=reading_policy

[PAPER_POLICY_ADAPTATION]
segment=XRPUSDT:BULL_TREND:SELL action=collect_bootstrap candidate_ev=0.0300 mode=PAPER

[PAPER_TRAIN_QUALITY_ENTRY]
trade_id=paper_1cdbc52e830b
source=paper_adaptive_recovery
ev=0.0300 expected_move_src=atr_abs_price_normalized cost_edge_ok=False
```

Do not undo this PAPER adaptive read/admission path.

Negative EV remains rejected:

```text
decision=REJECT_NEGATIVE_EV ev<0
[PAPER_EXPLORE_SKIP] ... original_decision=REJECT_NEGATIVE_EV
```

D_NEG remains shadow-only in observed close:

```text
[PAPER_LEARNING_SHADOW_SKIP]
trade_id=paper_e76a6f45bb20
bucket=D_NEG_EV_CONTROL
reason=d_neg_ev_control_shadow_only
```

## Confirmed O1A qualification correctness bug

Source currently claims qualification closes must be after epoch, but does not enforce it:

```text
paper_adaptive_learning.py:301-360 _try_increment_qualification()
```

Actual checks present:
- excludes D_NEG
- excludes quarantine
- excludes TIMEOUT_NO_PRICE
- excludes shadow
- requires trade_id/symbol/non-FLAT

Missing:
- no `entry_ts` or epoch-id comparison against `qualification_started_at`
- no proof the position was opened after the qualification epoch
- no dedupe by `trade_id`

Production proof of invalid credit:

```text
[PAPER_QUALIFICATION_EPOCH_STARTED] ... qualification_n=0
...
[PAPER_CANONICAL_LEARNING_UPDATE]
trade_id=paper_0d3e2ef86604
learning_source=paper_adaptive_recovery
...
[PAPER_QUALIFICATION_UPDATE]
trade_id=paper_0d3e2ef86604 qualification_n=1
```

There is no post-epoch entry shown for `paper_0d3e2ef86604`; it was an already-open or unproven-origin close. It must not receive qualification credit.

## Confirmed qualification selection bias

Current code excludes:

```python
if ... or outcome == "FLAT":
    return
```

But `FLAT` closes are real economic outcomes with fee/slippage impact, e.g.:

```text
paper_1cdbc52e830b outcome=FLAT net_pnl_pct=-0.0402
paper_fd248c536c0f outcome=FLAT net_pnl_pct=+0.0037
```

They updated canonical adaptive metrics but did not emit `PAPER_QUALIFICATION_UPDATE`.

This biases qualification metrics and recreates the prior misleading decisive-only performance problem. Eligible `WIN`, `LOSS`, and `FLAT` outcomes must all count if valid and post-epoch.

## Confirmed readiness scope bug

Current `check_real_readiness()`:
- calculates PF/expectancy from `qualification_window`;
- but calculates `rolling20_pf`, symbols and max segment share from legacy `rolling20/rolling100`;
- `qualification_window` entries store only `(pnl, outcome, symbol, ts)`, losing regime/side segment identity.

Therefore old/pre-integration adaptive history can still satisfy readiness gates, contrary to qualification provenance.

## Starvation telemetry not yet truthful in runtime

Current PID contains:

```text
[PAPER_EXPLORE_SKIP] ... original_decision=REJECT_NEGATIVE_EV
[PAPER_ADAPTIVE_STARVATION]
positive_candidates=0 negative_ev_rejects=0 ... reason=awaiting_samples
```

Telemetry does not reflect observed negative-EV drought at emission time. Determine whether this is due to log ordering/window initialization or because it only observes a narrower sampler route. Fix semantics/log scope so emitted reason is truthful; do not modify admission.

---

# Phase 0 — Immediately preserve forensic evidence (read-only / backup)

Before editing code or running pytest:

```bash
cd /opt/CryptoMaster_srv
TS=$(date -u +%Y%m%dT%H%M%SZ)
INCIDENT="server_local_backups/o1a1_incident_$TS"
mkdir -p "$INCIDENT"

git rev-parse --short HEAD | tee "$INCIDENT/head.txt"
git status --short | tee "$INCIDENT/git_status.txt"

cp -a server_local_backups/paper_adaptive_learning_state.json "$INCIDENT/paper_adaptive_learning_state.before_fix.json" 2>/dev/null || true
cp -a data/paper_open_positions.json "$INCIDENT/paper_open_positions.before_fix.json" 2>/dev/null || true

PID=$(systemctl show cryptomaster -p MainPID --value)
echo "$PID" | tee "$INCIDENT/pid.txt"
sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat > "$INCIDENT/journal_current_pid.log"

./venv/bin/python - <<'PY' | tee "$INCIDENT/adaptive_state_summary.txt"
import json
from pathlib import Path
p=Path("server_local_backups/paper_adaptive_learning_state.json")
if not p.exists():
    print("state_file_missing")
    raise SystemExit(0)
d=json.loads(p.read_text())
for k in ("lifetime_n","lifetime_pf","lifetime_expectancy","lifecycle",
          "qualification_schema_version","qualification_started_at",
          "qualification_n","operator_unlock"):
    print(k, "=", d.get(k))
for k in ("rolling20","rolling50","rolling100","qualification_window"):
    print(k, "_len=", len(d.get(k, [])))
print("segment_weight_count=", len(d.get("segment_weights", {})))
print("segment_weights=", d.get("segment_weights", {}))
PY

echo "INCIDENT_BACKUP=$INCIDENT"
```

Do not run pytest before test-state isolation has been coded.

Do not stop the PAPER service solely for this issue. Real readiness is blocked by `operator_unlock=False`; the urgent risk is metric pollution, not real-money execution.

---

# Phase 1 — Fix test isolation FIRST

## Required implementation

Tests must never read or write:

```text
server_local_backups/paper_adaptive_learning_state.json
```

Implement dependency injection or monkeypatch-safe state path. Preferred production-safe approach:

```python
class PaperAdaptiveLearning:
    def __init__(self, state_file: Optional[str] = None):
        self._state_file = state_file or _STATE_FILE
```

and use `self._state_file` in `_load_state()` / `_save_state()`.

All tests for adaptive learning must construct learner with a temporary state file:

```python
learner = PaperAdaptiveLearning(state_file=str(tmp_path / "adaptive_state.json"))
```

or use an autouse fixture that patches `_STATE_FILE` / resets `_learner` / resets module states before every test.

Also isolate:
- module singleton `_learner`;
- `_ADAPTIVE_STARVATION_STATE`;
- sampler rate/cap/probe global state when `maybe_open_training_sample()` is tested.

## Required tests

Add a test proving:

```text
running record_close() in a test learner does not modify a sentinel production-path file.
```

Fix the invalid test import:

```text
get_rde_instance
```

must not be imported if it does not exist. Prove live/real isolation via the actual callable/mode guard or source-level assertion already used in established tests.

---

# Phase 2 — Fix qualification eligibility and state representation

## A. Require post-epoch opened trade provenance

A close counts for qualification only if it was opened in the active qualification epoch.

Preferred robust design:

When opening a new eligible canonical PAPER position after O1A1:

```text
qualification_schema_version=1
qualification_epoch_id=<persisted epoch id>
qualification_opened_at=<entry/open timestamp>
qualification_eligible=True
```

Store these fields on the opened position/closed trade through the existing metadata handoff.

The adaptive learner accepts qualification only when:

```python
trade.get("qualification_eligible") is True
trade.get("qualification_epoch_id") == self.qualification_epoch_id
trade.get("qualification_opened_at", 0) >= self.qualification_started_at
```

Alternative timestamp-only protection is acceptable only if entry time is reliably persisted and tested over restart.

Old open positions lacking this metadata must still update ordinary adaptive rolling metrics if already eligible for canonical learning, but must **not** increment qualification.

Add log:

```text
[PAPER_QUALIFICATION_SKIP]
trade_id=...
reason=pre_epoch_or_unproven_open|d_neg|quarantined|shadow_only|invalid_trade
```

Do not spam; this is on close only.

## B. Include all valid economic outcomes

Remove `outcome == "FLAT"` exclusion.

Qualification must count valid:

```text
WIN
LOSS
FLAT
```

because `FLAT` may include real negative fee/slippage outcomes.

Reject only invalid/missing outcomes or existing excluded categories.

## C. Deduplicate qualification closes

Persist:

```text
qualification_trade_ids_seen
```

bounded or aligned to the qualification window/epoch, and prevent the same `trade_id` from incrementing `qualification_n` twice.

Test duplicate close/update call increments once only.

## D. Store full segment identity in qualification window

Use entries sufficient for readiness metrics, such as:

```python
(net_pnl_pct, outcome, segment_key, ts, trade_id)
```

where:

```text
segment_key = symbol:regime:side
```

If backward-compatible loading is needed, qualification is a new epoch and can safely migrate/reset its window only; do not reset regular adaptive rolling history without evidence.

---

# Phase 3 — Fix readiness to use qualification evidence only

`check_real_readiness()` must not use old rolling windows to satisfy real readiness gates.

All real-readiness economic and diversification gates must be computed from:

```text
qualification_window only
```

Including:
- qualification PF;
- qualification expectancy;
- qualification net PnL;
- recent qualification-20 PF/expectancy;
- qualification symbol count;
- qualification segment concentration;
- any drawdown/stability calculation implemented.

Legacy `rolling20/50/100` remains valid only for PAPER policy guidance and logging, not REAL_READY.

Required readiness rules:

```text
qualification_n < 100 → eligible=False reason=insufficient_post_integration_samples
operator_unlock=False → eligible=False reason=operator_unlock_required
qualification metrics fail → eligible=False with truthful reason
only qualification_n>=100 + passing qualification-only gates + operator_unlock=True
    may return eligible=True in unit test
```

Production operator unlock must remain False.

---

# Phase 4 — Fix starvation telemetry observability only

Do not affect routing.

Make emitted counters correspond to the actual PAPER candidate/reject route being described. Choose one:

1. Count `REJECT_NEGATIVE_EV` at the actual shared PAPER routing call that handles the observed skip; or
2. Rename/scope the log clearly to sampler-only and avoid claiming no-positive-supply for unobserved events.

Preferred: observe the actual PAPER rejection flow with a minimal function call that increments telemetry counters without opening trades.

Required behavior:

```text
negative-only observed PAPER window:
[PAPER_ADAPTIVE_STARVATION] ... negative_ev_rejects>0 reason=no_positive_ev_candidates

positive EV adaptive admission window:
[PAPER_ADAPTIVE_STARVATION] ... positive_candidates>0 policy_reads>0/admitted_recovery>0 reason=learning_active|awaiting_samples
```

`canonical_closes` must be updated from actual eligible canonical learning update path, or removed from the log if it is not truthful.

---

# Phase 5 — Reconcile already contaminated state safely

Tests have likely written fabricated results to the persisted adaptive state.

Do not blindly preserve contaminated:
- rolling windows;
- lifetime metrics;
- segment weights;
- qualification_n/window.

Do not blindly erase real adaptive outcomes either.

## Required forensic reconciliation

Using the Phase 0 backup plus production journals:
1. Determine whether the on-disk state contains test-written fabricated entries after test execution.
2. Determine whether the running service subsequently overwrote it with in-memory real state.
3. Extract real `[PAPER_CANONICAL_LEARNING_UPDATE]` lines from relevant production PIDs since N/N2C/O1/O1A as evidence.
4. If exact reconstruction of normal adaptive rolling windows is not possible, report before changing them; do not guess.
5. Qualification state may be safely reset to a new O1A1 epoch because O1A qualification was invalid from inception:
   ```text
   qualification_n=0
   qualification_window=[]
   qualification_trade_ids_seen=[]
   operator_unlock=False
   new qualification_started_at / qualification_epoch_id
   ```
6. Preserve ordinary adaptive rolling state only if verified clean or reconstructed from production evidence.

Provide a one-time reconciliation script only if necessary, default dry-run with explicit `--apply` required. It must operate only on `server_local_backups/paper_adaptive_learning_state.json`, create its own backup, and never affect Firebase/trade history.

---

# Files permitted

Allowed:

```text
src/services/paper_adaptive_learning.py
src/services/paper_training_sampler.py
src/services/paper_trade_executor.py only if open-position qualification metadata propagation is required
src/services/realtime_decision_engine.py only if existing open metadata handoff occurs there and only PAPER metadata is added
tests/test_p11ap_o1a_completion.py
tests/test_paper_adaptive_learning.py
tests/test_p11ap_n2_recovery_admission.py only if metadata assertions are needed
scripts/p11ap_o1a1_reconcile_adaptive_state.py only if dry-run/apply reconciliation is proven necessary
```

Forbidden:

```text
Firebase reads/writes/contracts
Android/dashboard contract changes
EV/ECON_BAD/cost-edge threshold changes
TP/SL/timeout changes
negative-EV canonical admission
D_NEG canonical learning
live/real execution changes
automatic operator_unlock
data/research or runtime artifacts in git
```

---

# Safe test order

Do NOT run tests until state isolation code and fixtures are in place.

After implementing isolation, first protect/verify the real state file hash:

```bash
REAL_STATE=server_local_backups/paper_adaptive_learning_state.json
sha256sum "$REAL_STATE" 2>/dev/null | tee /tmp/o1a1_real_state_hash_before_tests.txt || true
```

Run only isolated O1A tests:

```bash
./venv/bin/python -m pytest -q tests/test_p11ap_o1a_completion.py
sha256sum "$REAL_STATE" 2>/dev/null | tee /tmp/o1a1_real_state_hash_after_o1a_tests.txt || true
diff -u /tmp/o1a1_real_state_hash_before_tests.txt /tmp/o1a1_real_state_hash_after_o1a_tests.txt
```

The real state hash must be unchanged.

Then targeted:

```bash
./venv/bin/python -m pytest -q \
  tests/test_p11ap_o1a_completion.py \
  tests/test_paper_adaptive_learning.py \
  tests/test_p11ap_n2_recovery_admission.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_v10_13u_patches.py

sha256sum "$REAL_STATE" 2>/dev/null | tee /tmp/o1a1_real_state_hash_after_targeted.txt || true
diff -u /tmp/o1a1_real_state_hash_before_tests.txt /tmp/o1a1_real_state_hash_after_targeted.txt
```

Then full server-safe suite:

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_o1a1_fullsuite.txt

sha256sum "$REAL_STATE" 2>/dev/null | tee /tmp/o1a1_real_state_hash_after_fullsuite.txt || true
diff -u /tmp/o1a1_real_state_hash_before_tests.txt /tmp/o1a1_real_state_hash_after_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_o1a1_fullsuite.txt || true
tail -40 /tmp/p11ap_o1a1_fullsuite.txt
```

Acceptance:

```text
all 22 O1A/O1A1 tests pass
full server-safe suite: >=934 passed, 0 failures, 0 errors, 0 warnings
real persisted adaptive state hash unchanged by every test run
```

Why baseline `>=934`: current full suite collected `924 passed + 10 failed = 934 total` after O1A.

---

# Commit / deploy / runtime acceptance

Before commit:

```bash
git status --short
git diff --name-status
git diff --stat
```

Do not stage runtime files, backup directories, `.env*`, `data/*`, logs, `venv`, or incident backup.

Commit only allowed source/tests/scripts:

```bash
git add <allowed files only>
git commit -m "P1.1AP-O1A1: Isolate adaptive tests and validate qualification epoch"
git push origin main
```

Service is PAPER-only. Restart only after:
- tests are clean;
- state reconciliation decision has been reported;
- open paper positions are checked.

Post-deploy accept only when:

```text
[PAPER_QUALIFICATION_EPOCH_STARTED] qualification_n=0
old/pre-epoch restored close → PAPER_QUALIFICATION_SKIP reason=pre_epoch_or_unproven_open
new post-epoch eligible WIN/LOSS/FLAT close → PAPER_QUALIFICATION_UPDATE qualification_n increments by 1
D_NEG close → PAPER_LEARNING_SHADOW_SKIP and no PAPER_QUALIFICATION_UPDATE
[PAPER_ADAPTIVE_STARVATION] negative_ev_rejects>0 reason=no_positive_ev_candidates during negative drought
[REAL_READINESS_CHECK] eligible=False qualification_n<100 operator_unlock=False
```

---

# Return report

```text
O1A DEPLOYED FAILURE SUMMARY:
TEST STATE CONTAMINATION PROOF:
PRODUCTION STATE BACKUP PATH:
STATE RECONCILIATION VERDICT / ACTION:
QUALIFICATION PRE-EPOCH BUG FIX:
FLAT OUTCOME QUALIFICATION FIX:
QUALIFICATION-ONLY READINESS FIX:
STARVATION TELEMETRY FIX:
FILES CHANGED:
REAL STATE HASH BEFORE/AFTER TESTS:
O1A/O1A1 TEST RESULTS:
FULL SUITE RESULTS:
COMMIT/PUSH:
POST-DEPLOY QUALIFICATION EVIDENCE:
D_NEG NON-REGRESSION:
REAL_READY STATUS:
```
