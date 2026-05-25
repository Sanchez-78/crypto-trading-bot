# Claude Code — P1.1AP-N2A: Preserve Recovery Trade Identity and Make Entry Telemetry Truthful

## Objective

P1.1AP-N2 has functionally restored PAPER learning flow. Do **not** change the admission economics, thresholds, caps, adaptive metrics, readiness gates, D_NEG isolation, TP/SL, or routing policy.

Apply only a narrow correctness/telemetry fix:

```text
1. A `paper_adaptive_recovery` admission must keep that learning_source on the actual opened position and on its close/update.
2. `[PAPER_LEARNING_ENTRY]` must mean an actual opened paper position and include `trade_id`.
3. A permitted-but-later-blocked/failed open must not be logged as a successful learning entry.
```

## Confirmed deployed baseline

```text
HEAD: 2e34d5a P1.1AP-N2: Wire adaptive paper recovery into rejected-candidate flow
Server-safe suite: 908 passed, 0 failures, 0 warnings
Current runtime PID evidence: 1320053
```

### Functional success to preserve

N2 now reaches the real drop path and emits positive PAPER recovery admissions:

```text
[PAPER_LEARNING_ENTRY] symbol=ADAUSDT side=BUY
 learning_source=paper_adaptive_recovery
 admission_reason=paper_learning_must_continue
 original_decision=REJECT_ECON_BAD_ENTRY
 ev=0.0300 expected_move_pct=0.0446
 expected_move_src=atr_abs_price_normalized cost_edge_ok=False

[PAPER_LEARNING_ENTRY] symbol=XRPUSDT side=BUY
 learning_source=paper_adaptive_recovery
 ev=0.0300 expected_move_pct=0.0005 cost_edge_ok=False
```

Corresponding likely paper closes appeared and adaptive metrics updated:

```text
[PAPER_EXIT] trade_id=paper_877b509cab1b symbol=XRPUSDT reason=TP
 bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN net_pnl_pct=0.0052 outcome=FLAT

[PAPER_CANONICAL_LEARNING_UPDATE] trade_id=paper_877b509cab1b symbol=XRPUSDT side=BUY
 learning_source=paper_training_sampler
 rolling20_n=20 rolling20_pf=2.072 rolling20_expectancy=0.404075

[PAPER_EXIT] trade_id=paper_b3039080693e symbol=ADAUSDT reason=TP
 bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN net_pnl_pct=0.0011 outcome=FLAT

[PAPER_CANONICAL_LEARNING_UPDATE] trade_id=paper_b3039080693e symbol=ADAUSDT side=BUY
 learning_source=paper_training_sampler
 rolling20_n=20 rolling20_pf=2.123 rolling20_expectancy=0.413130
```

The closes strongly correlate with the first recovery admissions by symbol/side and by subsequent `max_open_per_symbol` blocks, but the entry logs lack `trade_id` and the learning update lost `learning_source=paper_adaptive_recovery`. This makes proof/source attribution unreliable.

### Telemetry bug proven

N2 currently emits `[PAPER_LEARNING_ENTRY]` before confirming an actual opened position. Example:

```text
[PAPER_LEARNING_ENTRY] symbol=XRPUSDT side=SELL learning_source=paper_adaptive_recovery ...
[PAPER_ENTRY_BLOCKED] symbol=XRPUSDT reason=max_open_per_symbol open_symbol=1 bucket=C_WEAK_EV_TRAIN

[PAPER_LEARNING_ENTRY] symbol=ADAUSDT side=SELL learning_source=paper_adaptive_recovery ...
[PAPER_ENTRY_BLOCKED] symbol=ADAUSDT reason=max_open_per_symbol open_symbol=1 bucket=C_WEAK_EV_TRAIN
```

Therefore this log currently means “recovery admission allowed”, not “trade opened”.

### Safety to preserve

D_NEG exclusion has already been proven on N1/current behavior and must remain:

```text
D_NEG_EV_CONTROL → PAPER_LEARNING_SHADOW_SKIP → NO PAPER_CANONICAL_LEARNING_UPDATE
```

---

# Investigation before edit

Run:

```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git status --short
git log --oneline -8

nl -ba src/services/paper_training_sampler.py | sed -n '470,1040p'
nl -ba src/services/trade_executor.py | sed -n '1640,1760p'
nl -ba src/services/paper_trade_executor.py | sed -n '1450,1680p'
grep -R "PAPER_LEARNING_ENTRY\|paper_adaptive_recovery\|learning_source\|PAPER_ENTRY_BLOCKED\|PAPER_CANONICAL_LEARNING_UPDATE" -n src/services tests
```

Document:

```text
A. Where recovery eligibility is approved.
B. Where the actual paper trade_id is generated/open is successful.
C. Which metadata dict loses `learning_source=paper_adaptive_recovery`.
D. Whether entry logging currently occurs before trade_id exists.
```

## Required implementation

### 1. Separate admission permission from actual entry-open event

At the quality-gate/sampler location, if logging is needed, use a non-success marker:

```text
[PAPER_LEARNING_ADMISSION_ALLOWED]
symbol=... side=...
learning_source=paper_adaptive_recovery
admission_reason=paper_learning_must_continue
original_decision=REJECT_ECON_BAD_ENTRY
ev=... expected_move_pct=... expected_move_src=... cost_edge_ok=False
```

Or omit this pre-open log entirely.

The log name `[PAPER_LEARNING_ENTRY]` must only be emitted **after** the paper position has successfully opened and a real `trade_id` exists.

Actual successful log:

```text
[PAPER_LEARNING_ENTRY]
trade_id=paper_...
symbol=... side=...
learning_source=paper_adaptive_recovery
admission_reason=paper_learning_must_continue
original_decision=REJECT_ECON_BAD_ENTRY
reject_reason=weak_ev
ev=... expected_move_pct=... expected_move_src=... cost_edge_ok=False
```

If open fails or is blocked, emit only existing/accurate blocker logs such as:

```text
[PAPER_ENTRY_BLOCKED] ...
```

and never a success `[PAPER_LEARNING_ENTRY]`.

### 2. Persist recovery metadata on the opened position

For an actually opened adaptive-recovery trade, ensure the persisted open position contains:

```text
learning_source="paper_adaptive_recovery"
admission_reason="paper_learning_must_continue"
original_decision="REJECT_ECON_BAD_ENTRY"
original_reject_reason / reject_reason
cost_edge_ok=False
expected_move_pct
expected_move_src
required_move_pct where available
ev / score / regime where available
```

Preserve existing `bucket=C_WEAK_EV_TRAIN` and `training_bucket=C_WEAK_EV_TRAIN` if those are canonical learner buckets. This patch is metadata correctness only, not a bucket redesign.

### 3. Propagate metadata through close and adaptive update

For an opened recovery position, the eventual:

```text
[PAPER_EXIT]
[PAPER_CANONICAL_LEARNING_UPDATE]
```

must preserve:

```text
learning_source=paper_adaptive_recovery
```

Required adaptive update log:

```text
[PAPER_CANONICAL_LEARNING_UPDATE]
trade_id=paper_...
learning_source=paper_adaptive_recovery
...
rolling20_pf=... rolling20_expectancy=...
```

If `[PAPER_EXIT]` already supports `learning_source`, include it there as well. If changing its common log format would be unnecessarily risky, the adaptive update log is mandatory and sufficient.

### 4. No policy/economic changes

Do not alter:

```text
ECON_BAD threshold
cost-edge threshold
recovery eligibility rules
caps
paper position geometry
TP/SL/timeout
rolling metric formulas
REAL_READY gates
D_NEG exclusion
normal B/C routing
live/real behavior
```

## Required tests

Add or update tests to prove the real lifecycle.

1. Recovery quality gate may return `recovery_admission=True`, but it does **not** log `[PAPER_LEARNING_ENTRY]` before position creation.

2. Recovery candidate that is later blocked by `max_open_per_symbol`:
   ```text
   emits PAPER_ENTRY_BLOCKED
   emits no PAPER_LEARNING_ENTRY
   creates no position
   updates no adaptive metrics
   ```

3. Successful adaptive recovery open:
   ```text
   obtains actual trade_id
   emits PAPER_LEARNING_ENTRY with that trade_id
   persisted position has learning_source=paper_adaptive_recovery
   preserves cost/expected-move metadata
   ```

4. End-to-end successful recovery open → close:
   ```text
   PAPER_CANONICAL_LEARNING_UPDATE contains same trade_id
   learning_source=paper_adaptive_recovery
   adaptive rolling count increments exactly once
   ```

5. Ordinary `training_sampler` C_WEAK close remains:
   ```text
   learning_source=paper_training_sampler
   ```
   and is not falsely relabelled recovery.

6. D_NEG end-to-end remains:
   ```text
   PAPER_LEARNING_SHADOW_SKIP
   no PAPER_CANONICAL_LEARNING_UPDATE
   no adaptive state mutation
   ```

7. Existing N/N1/N2, I/I2, J/J2, K regression suites stay green.

## Scope

Allowed only if necessary:

```text
src/services/paper_training_sampler.py
src/services/trade_executor.py
src/services/paper_trade_executor.py
tests/test_p11ap_n2_recovery_admission.py
tests/test_paper_adaptive_learning.py
```

Do not modify:

```text
src/services/app_metrics_contract.py
src/services/firebase_client.py
data/research/*
phase2b_firebase_probe.py
runtime state/backups/logs
Android/Firebase contracts
```

## Validation

Run:

```bash
./venv/bin/python -m pytest -q \
  tests/test_p11ap_n2_recovery_admission.py \
  tests/test_paper_adaptive_learning.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_v10_13u_patches.py

./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_n2a_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_n2a_fullsuite.txt || true
tail -30 /tmp/p11ap_n2a_fullsuite.txt
```

Baseline:

```text
N2: 908 passed in 3.76s, 0 failures, 0 warnings
```

N2A must be:

```text
>=908 passed plus new tests, 0 failures, 0 warnings
```

## Commit / deployment

Only after scope and tests pass:

```bash
git status --short
git diff --name-status
git diff --stat

git add <only allowed source/test files>
git commit -m "P1.1AP-N2A: Preserve adaptive recovery source through paper lifecycle"
git push origin main
```

## Post-deploy acceptance

```bash
PID=$(systemctl show cryptomaster -p MainPID --value)
sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat | grep -E \
"PAPER_LEARNING_ADMISSION_ALLOWED|PAPER_LEARNING_ENTRY|paper_adaptive_recovery|PAPER_ENTRY_BLOCKED|PAPER_EXIT|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL|Traceback|UnboundLocalError"
```

Accept only when:

```text
- `[PAPER_LEARNING_ENTRY]` includes a real trade_id and is not followed by open failure for that same attempted entry.
- Recovery close/update preserves `learning_source=paper_adaptive_recovery`.
- Blocked recovery attempts do not emit successful entry log.
- D_NEG remains shadow-only.
```

## Return report

```text
ROOT CAUSE OF LOST RECOVERY METADATA:
ROOT CAUSE OF FALSE ENTRY TELEMETRY:
FILES CHANGED:
TEST RESULTS:
COMMIT/PUSH:
POST-DEPLOY SUCCESSFUL RECOVERY ENTRY WITH TRADE_ID:
POST-DEPLOY RECOVERY CLOSE/UPDATE WITH SOURCE:
POST-DEPLOY BLOCKED-ATTEMPT TELEMETRY:
D_NEG NON-REGRESSION:
```
