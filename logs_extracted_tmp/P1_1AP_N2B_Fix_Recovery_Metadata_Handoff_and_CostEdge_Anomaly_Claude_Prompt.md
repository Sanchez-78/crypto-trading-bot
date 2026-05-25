# CLAUDE CODE — P1.1AP-N2B: Fix Recovery Metadata Handoff and Intentional Cost-Edge Exception Classification

## Objective

P1.1AP-N2 restored paper trade flow. P1.1AP-N2A attempted to preserve recovery identity and make entry telemetry truthful, but **production runtime now proves N2A is incomplete**.

Implement one narrow correctness patch:

```text
A recovery-admitted trade must retain `learning_source=paper_adaptive_recovery`
from sampler approval → actual opened position → quality entry/exit → canonical learning update.

An intentional paper_adaptive_recovery trade with `cost_edge_ok=False`
must not be reported as the unexpected anomaly `cost_edge_false_without_bypass`.

`[PAPER_LEARNING_ENTRY]` must be emitted only after a successful open and must include `trade_id`.
```

Do not change admission thresholds, caps, trade geometry, learner formulas, D_NEG isolation, REAL_READY gates, or any live/real execution behavior.

---

# Confirmed deployed baseline

```text
HEAD: 5bd75f5 P1.1AP-N2A: Preserve adaptive recovery source through paper lifecycle
N2A server-safe suite: 908 passed, 0 failures, 0 warnings
Current runtime PID with evidence: 1320527
```

N2 functional success remains required and must not be reverted:
- positive `REJECT_ECON_BAD_ENTRY` / `cost_edge_too_low` candidates in PAPER can be sampled;
- paper closes update rolling learning metrics;
- D_NEG remains excluded.

---

# Production evidence proving N2A failure

The following trade was created and closed inside the current N2A PID:

```text
[PAPER_ENTRY] symbol=XRPUSDT side=SELL price=1.35625000 size_usd=100.00 ev=0.0300 score=0.171 reason=PAPER_TRAINING

[PAPER_TRAIN_QUALITY_ENTRY]
 trade_id=paper_1ceafb1e5150
 symbol=XRPUSDT side=SELL
 source=training_sampler
 bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN
 ev=0.0300
 expected_move_pct=0.000
 expected_move_src=None
 cost_edge_ok=False
 cost_edge_bypassed=False
 bypass_reason=none

[PAPER_TRAIN_ANOMALY]
 type=cost_edge_false_without_bypass
 trade_id=paper_1ceafb1e5150
 symbol=XRPUSDT
 source=training_sampler
```

It then closed and learned:

```text
[PAPER_EXIT] trade_id=paper_1ceafb1e5150 symbol=XRPUSDT reason=TIMEOUT
 net_pnl_pct=-0.0104 outcome=FLAT
 bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN

[PAPER_TRAIN_ECON_ATTRIB] trade_id=paper_1ceafb1e5150
 source=training_sampler
 cost_edge_ok=False cost_edge_bypassed=False bypass_reason=none
 expected result context: near TP timeout / fee dominated

[PAPER_CANONICAL_LEARNING_UPDATE]
 trade_id=paper_1ceafb1e5150
 symbol=XRPUSDT side=SELL regime=BEAR_TREND
 learning_source=paper_training_sampler
 outcome=FLAT net_pnl_pct=-0.0104
 rolling20_pf=1.581 rolling20_expectancy=0.234475
```

Critical reasoning:

```text
Under the pre-N2 normal C_WEAK path, an EV-positive candidate with cost_edge_ok=False
was skipped at cost_edge_too_low.

N2 intentionally allows such PAPER candidates only as `paper_adaptive_recovery`.

Therefore this current-PID position is a recovery-admitted sample whose identity was lost
before/while opening the position. It is not an ordinary training_sampler trade.

The current anomaly is also wrong: cost_edge_ok=False is expected for a permitted
paper_adaptive_recovery sample and must be classified as intentional recovery sampling,
not unexpected bypass failure.
```

Observed additional proof:
- No `[PAPER_LEARNING_ENTRY] trade_id=paper_1ceafb1e5150 learning_source=paper_adaptive_recovery` appeared for the successful open.
- `expected_move_src` also became `None` despite the recovery candidate path providing `atr_abs_price_normalized`.

---

# Root cause to identify precisely

N2A modified extraction/storage inside `paper_trade_executor.open_paper_position(extra=...)`, but runtime indicates the required recovery metadata is absent by the time `open_paper_position()` receives `extra`, or it is overwritten before the position is stored/logged.

Inspect the complete handoff:

```text
paper_training_sampler._training_quality_gate()
  → maybe_open_training_sample() return payload
  → trade_executor candidate / metadata merge
  → paper_trade_executor.open_paper_position(extra=...)
  → position dict persistence
  → close_paper_position()
  → learner.record_close()
```

Run before edit:

```bash
cd /opt/CryptoMaster_srv
git rev-parse --short HEAD
git status --short
git log --oneline -8

grep -R "recovery_admission\|paper_adaptive_recovery\|PAPER_LEARNING_ADMISSION_ALLOWED\|PAPER_LEARNING_ENTRY\|expected_move_src\|cost_edge_false_without_bypass\|open_paper_position\|maybe_open_training_sample" -n src/services tests

nl -ba src/services/paper_training_sampler.py | sed -n '450,1040p'
nl -ba src/services/trade_executor.py | sed -n '1600,1785p'
nl -ba src/services/paper_trade_executor.py | sed -n '800,990p'
nl -ba src/services/paper_trade_executor.py | sed -n '1240,1690p'
```

Before coding, state in work log:

```text
1. The exact sampler return keys when recovery is approved.
2. The exact trade_executor metadata dict sent to open_paper_position().
3. Which key is dropped/overwritten/missing.
4. Where the successful `PAPER_LEARNING_ENTRY` should be emitted after trade_id creation.
5. Where anomaly logic should recognize intentional recovery cost-edge admission.
```

---

# Required implementation

## 1. Carry recovery metadata from sampler output to position storage

When `maybe_open_training_sample()` allows a recovery candidate, its returned metadata must reach `open_paper_position(extra=...)` without loss:

```text
learning_source = "paper_adaptive_recovery"
recovery_admission = True
admission_reason = "paper_learning_must_continue"
historical_health = "BAD"
original_decision = "REJECT_ECON_BAD_ENTRY"
original_reject_reason = "weak_ev" or precise original reason
expected_move_pct = original corrected expected move
expected_move_src = "atr_abs_price_normalized" where produced
required_move_pct = original threshold where available
cost_edge_ok = False
ev, score, regime, side, symbol as already available
```

Do not manufacture recovery metadata for normal accepted training samples.

The successfully stored position for a recovery admission must contain these keys and persist through restart/close.

## 2. Truthful actual-entry log after successful open

For a successfully opened recovery trade, after `trade_id` has been generated and position storage succeeds, emit:

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
expected_move_src=atr_abs_price_normalized
cost_edge_ok=False
```

Do not emit this log in the sampler gate before actual open.

A blocked attempt may emit:

```text
[PAPER_LEARNING_ADMISSION_ALLOWED] ...
[PAPER_ENTRY_BLOCKED] ...
```

but no success `PAPER_LEARNING_ENTRY`.

## 3. Preserve recovery source through close/update

For a stored recovery position, require:

```text
[PAPER_TRAIN_QUALITY_ENTRY] ... source=paper_adaptive_recovery ...
[PAPER_TRAIN_QUALITY_EXIT] ... source=paper_adaptive_recovery ...
[PAPER_TRAIN_ECON_ATTRIB] ... source=paper_adaptive_recovery ...
[PAPER_CANONICAL_LEARNING_UPDATE] ... learning_source=paper_adaptive_recovery ...
```

If existing quality logs distinguish `source` versus `learning_source`, use their current format consistently, but they must visibly identify recovery origin.

The same `trade_id` must correlate entry, exit and learning update.

## 4. Correct anomaly classification for intentional recovery samples

Do not emit:

```text
[PAPER_TRAIN_ANOMALY] type=cost_edge_false_without_bypass
```

for a trade where:

```text
learning_source == "paper_adaptive_recovery"
AND recovery_admission == True
AND cost_edge_ok == False
```

because cost-edge-negative sampling is the intentional purpose of this paper-learning path.

Instead either:
- emit no anomaly, because the context is already logged; or
- emit non-error telemetry such as:

```text
[PAPER_ADAPTIVE_RECOVERY_COST_SAMPLE]
trade_id=... symbol=... cost_edge_ok=False expected_move_pct=... required_move_pct=...
```

Do not mark `cost_edge_bypassed=True` unless that field already formally means an intentional learner bypass and all downstream semantics remain valid. Prefer a distinct recovery marker over falsifying cost-edge status.

Normal `training_sampler` samples with `cost_edge_ok=False` and no recovery marker must still trigger the anomaly.

## 5. Do not change economics

No changes to:

```text
ECON_BAD / EV / cost-edge threshold numbers
TP/SL/timeout geometry
entry caps
recovery eligibility
rolling metric formulas
policy adaptation thresholds
REAL_READY criteria
D_NEG isolation
live/real order behavior
```

---

# Required tests

Tests must exercise the actual end-to-end open/close path, not only helper predicates.

1. Positive `REJECT_ECON_BAD_ENTRY` + `cost_edge_too_low` PAPER candidate:
   - approved as recovery;
   - opens real paper position;
   - stored position has `learning_source=paper_adaptive_recovery`;
   - expected_move_src and cost metadata persist.

2. Successful recovery open emits:
   ```text
   PAPER_LEARNING_ENTRY with trade_id and learning_source=paper_adaptive_recovery
   ```

3. Recovery-approved attempt blocked by max-open:
   ```text
   PAPER_ENTRY_BLOCKED emitted
   PAPER_LEARNING_ENTRY absent
   no position stored
   no learner update
   ```

4. Recovery position quality entry log identifies recovery source.

5. Recovery position close:
   ```text
   PAPER_CANONICAL_LEARNING_UPDATE learning_source=paper_adaptive_recovery
   same trade_id as entry
   rolling metrics increment once
   ```

6. Recovery trade with `cost_edge_ok=False` does not emit
   ```text
   cost_edge_false_without_bypass
   ```
   and may emit informational recovery cost telemetry.

7. Normal non-recovery `training_sampler` trade with unexpected `cost_edge_ok=False` still emits the anomaly.

8. Normal C_WEAK non-recovery closes remain `learning_source=paper_training_sampler`.

9. D_NEG end-to-end remains:
   ```text
   PAPER_LEARNING_SHADOW_SKIP
   no PAPER_CANONICAL_LEARNING_UPDATE
   no adaptive metric mutation
   ```

10. N2 admission and caps remain unchanged.

---

# Allowed files

Only as necessary:

```text
src/services/paper_training_sampler.py
src/services/trade_executor.py
src/services/paper_trade_executor.py
tests/test_p11ap_n2_recovery_admission.py
tests/test_paper_adaptive_learning.py
existing directly-related paper tests if needed
```

Forbidden:

```text
data/research/*
phase2b_firebase_probe.py
src/services/app_metrics_contract.py
src/services/firebase_client.py
Android/Firebase contracts
runtime state/log files/backups
threshold/geometry/readiness changes
```

---

# Validation

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

Run server-safe full suite:

```bash
./venv/bin/python -m pytest -q \
  --ignore=VERIFICATION_V10_13X \
  --ignore=venv \
  --ignore=server_local_backups \
  --ignore=data/archive \
  --ignore=data/research 2>&1 | tee /tmp/p11ap_n2b_fullsuite.txt

grep -E "^FAILED |^ERROR " /tmp/p11ap_n2b_fullsuite.txt || true
tail -30 /tmp/p11ap_n2b_fullsuite.txt
```

Baseline:

```text
N2A: 908 passed in 3.71s, 0 failures, 0 warnings
```

Required:

```text
>=908 passed plus any new tests, 0 failures, 0 warnings
```

---

# Commit and production acceptance

After clean scope and tests only:

```bash
git status --short
git diff --name-status
git diff --stat

git add <allowed source/test files only>
git commit -m "P1.1AP-N2B: Preserve recovery metadata through actual paper trades"
git push origin main
```

After deploy capture a new PID and validate:

```bash
PID=$(systemctl show cryptomaster -p MainPID --value)
echo "CURRENT_PID=$PID"

sudo journalctl -u cryptomaster _PID="$PID" --no-pager -o cat | grep -E \
"PAPER_LEARNING_ADMISSION_ALLOWED|PAPER_LEARNING_ENTRY|paper_adaptive_recovery|PAPER_ENTRY_BLOCKED|PAPER_TRAIN_QUALITY_ENTRY|PAPER_TRAIN_ANOMALY|PAPER_ADAPTIVE_RECOVERY_COST_SAMPLE|PAPER_EXIT|PAPER_TRAIN_ECON_ATTRIB|PAPER_CANONICAL_LEARNING_UPDATE|PAPER_LEARNING_SHADOW_SKIP|D_NEG_EV_CONTROL|Traceback|UnboundLocalError"
```

Acceptance requires one real recovery lifecycle:

```text
[PAPER_LEARNING_ENTRY] trade_id=paper_X learning_source=paper_adaptive_recovery ...
[PAPER_TRAIN_QUALITY_ENTRY] trade_id=paper_X source=paper_adaptive_recovery ...
NO cost_edge_false_without_bypass anomaly for paper_X
[PAPER_EXIT] trade_id=paper_X ...
[PAPER_CANONICAL_LEARNING_UPDATE] trade_id=paper_X learning_source=paper_adaptive_recovery ...
```

and one safety validation:

```text
new D_NEG close → PAPER_LEARNING_SHADOW_SKIP → no PAPER_CANONICAL_LEARNING_UPDATE
```

---

# Report back

```text
ROOT CAUSE OF METADATA LOSS:
ROOT CAUSE OF FALSE COST-EDGE ANOMALY:
FILES CHANGED:
TARGETED TESTS:
FULL SUITE:
COMMIT/PUSH:
POST-DEPLOY RECOVERY ENTRY WITH TRADE_ID:
POST-DEPLOY RECOVERY QUALITY SOURCE:
POST-DEPLOY RECOVERY CLOSE/UPDATE SOURCE:
POST-DEPLOY ANOMALY CLASSIFICATION:
D_NEG NON-REGRESSION:
