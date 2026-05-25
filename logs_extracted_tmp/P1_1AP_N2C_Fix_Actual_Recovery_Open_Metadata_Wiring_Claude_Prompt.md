# Claude Code — P1.1AP-N2C: Fix the Actual Recovery-Open Metadata Wiring (No Economic Changes)

## Runtime failure: N2B is not accepted

Current deployed state:

```text
HEAD: 0dd81c1 P1.1AP-N2B: Preserve recovery metadata through actual paper trades
Server-safe baseline verified directly: 908 passed, 0 failures, 0 warnings
Current post-N2B PID: 1321980
```

N2B attempted to fix recovery source propagation by adding `expected_move_src` to one `trade_executor.py` extra dict and by changing anomaly/source handling in `paper_trade_executor.py`.

Production proves that this did **not** fix the actual open path.

### Decisive new post-N2B evidence

This position was newly opened after N2B under PID `1321980`:

```text
[PAPER_TRAIN_QUALITY_ENTRY]
trade_id=paper_547504070f3b
symbol=XRPUSDT side=BUY
source=training_sampler
bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN
regime=BULL_TREND
ev=0.0300
expected_move_pct=0.000
expected_move_src=None
cost_edge_ok=False
cost_edge_bypassed=False
bypass_reason=none
entry=1.35505000
hold_limit_s=300

[PAPER_TRAIN_ANOMALY]
type=cost_edge_false_without_bypass
trade_id=paper_547504070f3b
symbol=XRPUSDT
source=training_sampler
```

Why this is decisive:

```text
Since N2, an EV-positive C_WEAK candidate with cost_edge_ok=False is intentionally allowed
only through the integrated PAPER recovery path (`paper_adaptive_recovery`).

Therefore `paper_547504070f3b` is an admitted recovery sample whose metadata was lost
before the stored position/quality log was built.

Expected after N2B:
  source=paper_adaptive_recovery
  expected_move_src=atr_abs_price_normalized (or actual sampler recovery source)
  no cost_edge_false_without_bypass anomaly

Observed:
  source=training_sampler
  expected_move_src=None
  false anomaly still emitted
```

There is also a new D_NEG control entry:

```text
[PAPER_TRAIN_QUALITY_ENTRY] trade_id=paper_617d27fc57cb
bucket=D_NEG_EV_CONTROL cost_edge_ok=False source=training_sampler
[PAPER_TRAIN_ANOMALY] type=cost_edge_false_without_bypass ...
```

For D_NEG this anomaly is diagnostic noise; preserve its shadow-only close exclusion. Do not allow it into adaptive learning.

---

## Goal

Fix only the actual metadata/log handoff for successfully opened `paper_adaptive_recovery` trades, and suppress misclassified `cost_edge_false_without_bypass` for intentional recovery and D_NEG control samples.

Do not change:

```text
- admission eligibility or caps;
- EV / ECON_BAD / cost-edge thresholds;
- TP/SL/timeout geometry;
- rolling metric formulas or policy/readiness thresholds;
- REAL_READY/operator unlock;
- D_NEG shadow-only learning exclusion;
- normal paper routing behavior;
- live/real execution behavior;
- Android/Firebase contracts.
```

No new bucket, no new learner, no shadow lane.

---

## Mandatory investigation: find the real caller/data path before editing

N2B likely patched a dict that is not the one used by the runtime open shown above, or recovery fields are overwritten/dropped before `open_paper_position()` persists them.

Inspect the full *runtime* path:

```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git status --short
git log --oneline -8

grep -R "def maybe_open_training_sample\|maybe_open_training_sample\|recovery_admission\|paper_adaptive_recovery\|PAPER_LEARNING_ENTRY\|PAPER_LEARNING_ADMISSION_ALLOWED\|open_paper_position\|PAPER_TRAIN_QUALITY_ENTRY\|cost_edge_false_without_bypass\|expected_move_src" -n src/services tests

nl -ba src/services/paper_training_sampler.py | sed -n '430,1060p'
nl -ba src/services/trade_executor.py | sed -n '1560,1815p'
nl -ba src/services/paper_trade_executor.py | sed -n '780,1010p'
nl -ba src/services/paper_trade_executor.py | sed -n '1830,2085p'
```

Before modifying code, write a short work note with exact file:line evidence:

```text
1. Where recovery admission is approved and exact keys returned.
2. Every call site of maybe_open_training_sample/open_paper_position used in production.
3. Which call site produced PAPER_TRAIN_QUALITY_ENTRY for paper_547504070f3b.
4. What `extra` dict that call site passes into open_paper_position.
5. Exactly where learning_source/recovery_admission/expected_move_src disappears or gets overwritten.
6. Exactly where successful PAPER_LEARNING_ENTRY should be emitted with the created trade_id.
```

Do not make another speculative one-line patch before proving the missing handoff.

---

## Required implementation

### A. One canonical recovery metadata object

At the recovery approval result, define/return one consistent metadata payload, using existing structures where possible:

```python
{
    "recovery_admission": True,
    "learning_source": "paper_adaptive_recovery",
    "admission_reason": "paper_learning_must_continue",
    "historical_health": "BAD",
    "original_decision": "REJECT_ECON_BAD_ENTRY",
    "original_reject_reason": <actual weak_ev reason>,
    "expected_move_pct": <corrected value>,
    "expected_move_src": <corrected source, e.g. atr_abs_price_normalized>,
    "required_move_pct": <where available>,
    "cost_edge_ok": False,
    "cost_edge_bypassed": False
}
```

Pass the *same* metadata through the actual production caller that invokes `open_paper_position()`.

A successful recovery position stored on disk/in memory must include at least:

```text
learning_source=paper_adaptive_recovery
recovery_admission=True
admission_reason=paper_learning_must_continue
original_decision=REJECT_ECON_BAD_ENTRY
original_reject_reason
expected_move_pct
expected_move_src
cost_edge_ok=False
cost_edge_bypassed=False
```

Normal non-recovery positions must not be mislabeled.

### B. Successful entry telemetry must be post-open and trade-correlated

A real successful recovery open must emit **after the position has a trade_id**:

```text
[PAPER_LEARNING_ENTRY]
trade_id=paper_...
symbol=... side=...
learning_source=paper_adaptive_recovery
admission_reason=paper_learning_must_continue
original_decision=REJECT_ECON_BAD_ENTRY
reject_reason=weak_ev
ev=...
expected_move_pct=...
expected_move_src=...
cost_edge_ok=False
```

A pre-open allow may emit:

```text
[PAPER_LEARNING_ADMISSION_ALLOWED] ...
```

A blocked or failed open must not emit `[PAPER_LEARNING_ENTRY]`.

### C. Recovery identity must survive all logs and the close update

For the same recovery `trade_id`, require:

```text
[PAPER_TRAIN_QUALITY_ENTRY] ... source=paper_adaptive_recovery expected_move_src=...
[PAPER_TRAIN_QUALITY_EXIT] ... source=paper_adaptive_recovery ...
[PAPER_TRAIN_ECON_ATTRIB] ... source=paper_adaptive_recovery ...
[PAPER_CANONICAL_LEARNING_UPDATE] ... learning_source=paper_adaptive_recovery ...
```

The position must persist this metadata over normal timeout/TP/SL close and service restart.

### D. Correct cost-edge diagnostic classification

Do not emit:

```text
[PAPER_TRAIN_ANOMALY] type=cost_edge_false_without_bypass
```

when either is true:

```text
learning_source == "paper_adaptive_recovery" and recovery_admission is True
bucket/training_bucket == "D_NEG_EV_CONTROL"
```

These are intentional cost-edge-false samples/control positions.

Optional non-error telemetry is permitted:

```text
[PAPER_ADAPTIVE_RECOVERY_COST_SAMPLE] trade_id=... expected_move_pct=... required_move_pct=...
[PAPER_DNEG_COST_CONTROL_SAMPLE] trade_id=...
```

Do not set `cost_edge_bypassed=True` merely to silence the anomaly; preserve truthful semantics.

Unexpected non-recovery C_WEAK samples with `cost_edge_ok=False` and no valid recovery marker must still emit the anomaly.

---

## Required tests — actual open/close chain

Add regression tests that execute the same production call chain that created `paper_547504070f3b`. Existing helper-only tests are insufficient.

1. Recovery admission response from sampler contains every required metadata field.

2. Production open path for positive `REJECT_ECON_BAD_ENTRY` + `cost_edge_too_low`:
   - creates a paper position;
   - persisted position has `learning_source=paper_adaptive_recovery`, `recovery_admission=True`, `expected_move_src` not empty;
   - emits `[PAPER_LEARNING_ENTRY]` only after trade_id exists.

3. Recovery-approved candidate blocked by max-open:
   - may emit `PAPER_LEARNING_ADMISSION_ALLOWED`;
   - emits `PAPER_ENTRY_BLOCKED`;
   - emits no `PAPER_LEARNING_ENTRY`;
   - creates no position / no learning update.

4. Recovery position quality entry:
   - reports `source=paper_adaptive_recovery`;
   - preserves expected_move_src;
   - emits no `cost_edge_false_without_bypass`.

5. End-to-end recovery close:
   - same trade_id;
   - quality exit/econ attribution retain recovery source;
   - `PAPER_CANONICAL_LEARNING_UPDATE learning_source=paper_adaptive_recovery`;
   - adaptive count increments exactly once.

6. D_NEG position with `cost_edge_ok=False`:
   - does not emit `cost_edge_false_without_bypass`;
   - on close emits `PAPER_LEARNING_SHADOW_SKIP`;
   - emits no `PAPER_CANONICAL_LEARNING_UPDATE`;
   - does not change adaptive metrics.

7. Non-recovery unexpected C_WEAK with false cost edge still emits anomaly.

8. N/N1/N2/N2A, I/I2, J/J2 and K regression suites remain green.

---

## Scope boundaries

Allowed only if required by proven handoff:

```text
src/services/paper_training_sampler.py
src/services/trade_executor.py
src/services/paper_trade_executor.py
tests/test_p11ap_n2_recovery_admission.py
tests/test_paper_adaptive_learning.py
directly related paper regression test file only if necessary
```

Forbidden:

```text
data/research/*
phase2b_firebase_probe.py
src/services/app_metrics_contract.py
src/services/firebase_client.py
Android/Firebase contracts
runtime state/backups/logs
threshold or geometry changes
```

---

## Validation

Run targeted:

```bash
./venv/bin/python -m pytest -q \
  tests/test_p11ap_n2_recovery_admission.py \
  tests/test_paper_adaptive_learning.py \
  tests/test_p11ap_i_d_neg_learning_isolation.py \
  tests/test_p1_paper_exploration.py \
  tests/test_paper_mode_p1_1ai.py \
  tests/test_v10_13u_patches.py
```

Run full server-safe suite:

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_n2c_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_n2c_fullsuite.txt || true
tail -30 /tmp/p11ap_n2c_fullsuite.txt
```

Baseline:

```text
N2B: 908 passed in 3.80s, 0 failures, 0 warnings
```

Required result:

```text
>=908 passed plus new tests, 0 failures, 0 warnings
```

---

## Commit / deploy

Only after source-line root cause proof, clean diff and clean tests:

```bash
git status --short
git diff --name-status
git diff --stat

git add <allowed source/test files only>
git commit -m "P1.1AP-N2C: Fix recovery metadata wiring in actual paper open path"
git push origin main
```

## Post-deploy acceptance

Capture only the new PID:

```bash
PID=$(systemctl show cryptomaster -p MainPID --value)
echo "CURRENT_PID=$PID"

sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat | grep -E \
"PAPER_LEARNING_ADMISSION_ALLOWED|PAPER_LEARNING_ENTRY|paper_adaptive_recovery|PAPER_ENTRY_BLOCKED|PAPER_TRAIN_QUALITY_ENTRY|PAPER_TRAIN_ANOMALY|PAPER_ADAPTIVE_RECOVERY_COST_SAMPLE|PAPER_DNEG_COST_CONTROL_SAMPLE|PAPER_EXIT|PAPER_TRAIN_QUALITY_EXIT|PAPER_TRAIN_ECON_ATTRIB|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL|Traceback|UnboundLocalError"
```

Accept only with one complete new recovery lifecycle:

```text
[PAPER_LEARNING_ENTRY] trade_id=paper_X learning_source=paper_adaptive_recovery
[PAPER_TRAIN_QUALITY_ENTRY] trade_id=paper_X source=paper_adaptive_recovery expected_move_src=<not None>
NO cost_edge_false_without_bypass for paper_X
[PAPER_EXIT] trade_id=paper_X
[PAPER_CANONICAL_LEARNING_UPDATE] trade_id=paper_X learning_source=paper_adaptive_recovery
```

and one D_NEG safety confirmation:

```text
new D_NEG trade does NOT emit cost_edge_false_without_bypass
new D_NEG close emits PAPER_LEARNING_SHADOW_SKIP
new D_NEG trade has no PAPER_CANONICAL_LEARNING_UPDATE
```

## Report back

```text
EXACT ROOT CAUSE WITH FILE:LINES:
FILES CHANGED:
TESTS ADDED/UPDATED:
TARGETED RESULTS:
FULL SUITE:
COMMIT/PUSH:
POST-DEPLOY RECOVERY OPEN SOURCE:
POST-DEPLOY RECOVERY CLOSE SOURCE:
POST-DEPLOY D_NEG SAFETY:
```
