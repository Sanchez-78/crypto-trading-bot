# P1.1AP-I — Isolate D_NEG_EV_CONTROL From Canonical Learning

## Goal

Stop `D_NEG_EV_CONTROL` from contaminating canonical learning / economic health while preserving it as a diagnostic paper-control bucket.

This is a narrow safety/economics isolation patch.

Do **not** tune strategy, TP/SL, thresholds, RDE scoring, paper sampler caps, P1.1AO probe logic, Android snapshot publishing, Firebase contracts, or live/real trading behavior.

## Current validated baseline

Recent work is complete and green:

- P1.1AP-G: paper loader / timeout / quarantine fixes validated
- P1.1AP-H1/H1B/H2: V10.13u safety compatibility validated
- Full server-safe suite: `832 passed, 6 warnings`
- Runtime: no visible `Traceback` / `UnboundLocalError`
- ECON BAD weak-signal gate is active and correctly blocks weak entries
- Paper entries/exits and normal learning updates are flowing

## Problem evidence

Last 24h paper exits:

```text
total=48
win=0
loss=45
flat=3
winrate_closed_no_flat=0.00%
winrate_all=0.00%
```

Paper exit bucket breakdown:

```text
bucket=D_NEG_EV_CONTROL outcome=LOSS 25
bucket=C_WEAK_EV_TRAIN outcome=LOSS 16
bucket=B_RECOVERY_READY outcome=LOSS 4
bucket=A_STRICT_TAKE outcome=FLAT 3
```

Quality-exit breakdown:

```text
training_bucket=C_WEAK_EV_TRAIN side=BUY  outcome=LOSS reason=TIMEOUT 8
training_bucket=C_WEAK_EV_TRAIN side=SELL outcome=LOSS reason=TIMEOUT 2
training_bucket=C_WEAK_EV_TRAIN side=BUY  outcome=LOSS reason=SL      4
training_bucket=D_NEG_EV_CONTROL side=SELL outcome=LOSS reason=TIMEOUT 4
training_bucket=D_NEG_EV_CONTROL side=BUY  outcome=LOSS reason=TIMEOUT 20
```

Learning-update bucket breakdown:

```text
bucket=D_NEG_EV_CONTROL outcome=LOSS 48
bucket=C_WEAK_EV_TRAIN  outcome=LOSS 16
bucket=B_RECOVERY_READY outcome=LOSS 4
bucket=None             outcome=LOSS 6
bucket=None             outcome=FLAT 3
```

Observed D_NEG metrics:

```text
[PAPER_BUCKET_METRICS] bucket=D_NEG_EV_CONTROL n=... wr=0.0% avg=... pf=0.00 timeout_rate=100.0% tp_rate=0.0% sl_rate=0.0%
```

Conclusion:

`D_NEG_EV_CONTROL` is the dominant canonical learning contaminant. It is a control/diagnostic bucket with 0% win rate and 100% timeout-loss behavior, yet it currently writes into canonical LM/economic health via:

```text
[LM_STATE_AFTER_UPDATE]
[LEARNING_UPDATE] source=paper_closed_trade bucket=D_NEG_EV_CONTROL outcome=LOSS ok=True
```

This pushes `economic_health` into BAD and lowers PF, while not representing live-like signal quality.

## Required behavior

`D_NEG_EV_CONTROL` should remain visible as diagnostics, but should not affect canonical learning/economic health unless it proves viable.

### Minimum behavior

For closed paper trades where `bucket == "D_NEG_EV_CONTROL"` or `training_bucket == "D_NEG_EV_CONTROL"`:

Allow:

```text
[PAPER_EXIT]
[PAPER_TRAIN_QUALITY_EXIT]
[PAPER_TRAIN_CLOSED]
[PAPER_BUCKET_UPDATE]
[PAPER_BUCKET_METRICS]
```

Skip canonical learning impact:

```text
skip [LM_STATE_AFTER_UPDATE]
skip canonical [LEARNING_UPDATE]
skip learning_monitor canonical state mutation
skip economic_health impact
```

Add explicit diagnostic log:

```text
[PAPER_LEARNING_SHADOW_SKIP] bucket=D_NEG_EV_CONTROL reason=control_bucket_shadow_only ...
```

This log should include at least:

```text
trade_id
symbol
bucket
training_bucket
outcome
net_pnl_pct
reason
```

### Optional guarded promotion

If the codebase already has clean bucket quality access, allow a future-safe promotion gate, but keep it disabled unless clearly implemented and tested.

Suggested future gate:

```text
D_NEG canonical learning allowed only if:
- n >= 20
- winrate > 0%
- pf > 0.8
- timeout_rate < 80%
```

For this patch, prefer simple shadow-only unless existing bucket metrics make promotion trivial and safe.

## Hard rules

Do not modify:

- live/real trading behavior
- order execution
- TP/SL geometry
- RDE decision thresholds
- EV scoring
- paper sampler entry caps
- P1.1AO cold-start probe logic/caps
- Android snapshot publishing
- Firebase schema/contracts
- quarantine behavior for stale/corrupt positions
- existing ECON BAD safety gates

Do not remove D_NEG logging. The bucket must remain diagnosable.

Do not suppress `PAPER_EXIT` for D_NEG. We still need to see control outcomes.

Do not suppress `PAPER_BUCKET_UPDATE` / bucket diagnostics unless they currently mutate canonical LM. Bucket-local metrics are allowed and desired.

Do not make C_WEAK_EV_TRAIN shadow-only in this patch. C_WEAK has useful attribution (`WRONG_DIRECTION`, `FEE_DOMINATED_MOVE`) and should be handled separately if needed.

## Implementation guidance

Likely files:

```text
src/services/paper_trade_executor.py
src/services/learning_monitor.py
src/services/trade_executor.py
```

Search for the paper close path:

```bash
grep -R "paper_closed_trade\|LEARNING_UPDATE\|LM_STATE_AFTER_UPDATE\|_safe_learning_update_for_paper_trade\|D_NEG_EV_CONTROL" -n src/services tests
```

Expected likely hook:

- In the paper closed-trade save/update path, before canonical learning update is called.
- There may already be quarantine handling that marks `closed_trade["quarantined"] = True` and returns before learning.
- Add a separate D_NEG shadow-learning guard, but do **not** label it as quarantined unless quarantine semantics require no bucket diagnostics.
- Prefer explicit field:

```python
closed_trade["learning_shadow_only"] = True
closed_trade["learning_skip_reason"] = "d_neg_ev_control_shadow_only"
```

Then ensure canonical learning update returns early for that reason.

Pseudo-logic:

```python
def _is_d_neg_control_trade(trade: dict) -> bool:
    bucket = trade.get("bucket")
    training_bucket = trade.get("training_bucket")
    return bucket == "D_NEG_EV_CONTROL" or training_bucket == "D_NEG_EV_CONTROL"
```

In canonical learning update path:

```python
if _is_d_neg_control_trade(closed_trade):
    closed_trade["learning_shadow_only"] = True
    closed_trade["learning_skipped"] = True
    closed_trade["learning_skip_reason"] = "d_neg_ev_control_shadow_only"
    logger.warning(
        "[PAPER_LEARNING_SHADOW_SKIP] trade_id=%s symbol=%s bucket=%s training_bucket=%s outcome=%s net_pnl_pct=%.4f reason=%s",
        ...
    )
    return False
```

Important:

- This return must happen **after** `PAPER_EXIT` and quality/bucket diagnostics where appropriate.
- This return must happen **before** LM canonical state mutation, `LM_STATE_AFTER_UPDATE`, and `LEARNING_UPDATE`.
- If the code writes closed paper trades to Firebase as canonical learning records, skip that write for D_NEG too, unless it is a separate diagnostic-only collection.

## Required tests

Add focused regression tests. Prefer existing test file if suitable:

```text
tests/test_p11ab_stale_position_quarantine.py
tests/test_paper_mode_p1_1ai.py
tests/test_p1_paper_exploration.py
tests/test_v10_13u_patches.py
```

Or create a narrow file:

```text
tests/test_p11ap_i_d_neg_learning_isolation.py
```

### Test 1 — D_NEG exits still log/diagnose but skip canonical learning

Create/close a paper trade:

```python
bucket = "D_NEG_EV_CONTROL"
training_bucket = "D_NEG_EV_CONTROL"
outcome = "LOSS"
reason = "TIMEOUT"
```

Assert:

- `PAPER_EXIT` emitted
- `PAPER_TRAIN_QUALITY_EXIT` emitted if the path normally does it
- `PAPER_LEARNING_SHADOW_SKIP` emitted
- no `LM_STATE_AFTER_UPDATE`
- no canonical `LEARNING_UPDATE`
- learning monitor count does not increment

### Test 2 — Non-D_NEG paper trade still learns

Use:

```python
bucket = "C_WEAK_EV_TRAIN"
training_bucket = "C_WEAK_EV_TRAIN"
```

Assert:

- canonical `LEARNING_UPDATE` still occurs
- LM count increments
- no `PAPER_LEARNING_SHADOW_SKIP`

### Test 3 — A_STRICT_TAKE / B_RECOVERY_READY unchanged

Use one representative non-D_NEG bucket.

Assert normal existing behavior is preserved.

### Test 4 — Quarantine behavior unchanged

A stale/corrupt position must still:

- emit `PAPER_POSITION_QUARANTINED`
- skip `PAPER_EXIT`
- skip quality/econ
- skip learning
- not be confused with D_NEG shadow skip

### Test 5 — D_NEG bucket metrics still update

If bucket metrics are testable:

- D_NEG local bucket counters update
- canonical LM counters do not update

## Required targeted commands

Run new tests:

```bash
python -m pytest -q tests/test_p11ap_i_d_neg_learning_isolation.py
```

Run paper safety suite:

```bash
python -m pytest -q   tests/test_p1_paper_exploration.py   tests/test_paper_mode_p1_1ai.py   tests/test_p11ab_stale_position_quarantine.py   tests/test_v10_13u_patches.py
```

Run server-safe full suite:

```bash
python -m pytest -q   --ignore=VERIFICATION_V10_13X   --ignore=venv   --ignore=server_local_backups   --ignore=data/archive   --ignore=data/research
```

## Runtime validation after deploy

Restart:

```bash
sudo systemctl restart cryptomaster
sleep 180
```

Check runtime:

```bash
sudo journalctl -u cryptomaster --since "30 min ago" --no-pager | grep -E "PAPER_EXIT|PAPER_TRAIN_QUALITY_EXIT|PAPER_LEARNING_SHADOW_SKIP|LEARNING_UPDATE|LM_STATE_AFTER_UPDATE|D_NEG_EV_CONTROL|Traceback|UnboundLocalError"
```

Expected:

For D_NEG:

```text
[PAPER_EXIT] ... bucket=D_NEG_EV_CONTROL ...
[PAPER_TRAIN_QUALITY_EXIT] ... training_bucket=D_NEG_EV_CONTROL ...
[PAPER_LEARNING_SHADOW_SKIP] ... bucket=D_NEG_EV_CONTROL ...
```

Not expected for D_NEG:

```text
[LM_STATE_AFTER_UPDATE] ... bucket=D_NEG_EV_CONTROL
[LEARNING_UPDATE] ... bucket=D_NEG_EV_CONTROL
```

Still expected for non-D_NEG:

```text
[LEARNING_UPDATE] source=paper_closed_trade bucket=C_WEAK_EV_TRAIN ...
```

Validate 24h/rolling learning update breakdown:

```bash
sudo journalctl -u cryptomaster --since "60 min ago" --no-pager | grep "\[LEARNING_UPDATE\].*source=paper_closed_trade" | awk '
{
  bucket="unknown"; outcome="unknown";
  for(i=1;i<=NF;i++){
    if($i ~ /^bucket=/){bucket=$i}
    if($i ~ /^outcome=/){outcome=$i}
  }
  c[bucket" "outcome]++;
}
END { for(k in c) print k, c[k] }'
```

Expected after patch:

```text
No bucket=D_NEG_EV_CONTROL LEARNING_UPDATE lines
```

Validate D_NEG still visible:

```bash
sudo journalctl -u cryptomaster --since "60 min ago" --no-pager | grep "PAPER_LEARNING_SHADOW_SKIP.*D_NEG_EV_CONTROL"
```

## Acceptance criteria

- D_NEG paper exits are still visible.
- D_NEG quality/bucket diagnostics still work.
- D_NEG no longer mutates canonical LM/economic health.
- Non-D_NEG learning paths are unchanged.
- Quarantine behavior remains unchanged.
- ECON BAD gate remains active.
- Full server-safe tests pass.
- No runtime/local files committed.

## Commit message

```text
P1.1AP-I: Isolate D_NEG_EV_CONTROL from canonical learning
```

## Do not commit

```text
data/paper_open_positions.json
.env*
venv/
server_local_backups/
data/archive/
data/research/
temporary shell output files
```
