# Claude Code Prompt — P1.1AP-I2: Suppress D_NEG Legacy LEARNING_UPDATE Log

## Goal

Finish P1.1AP-I by stopping the remaining legacy `[LEARNING_UPDATE]` log leak for `D_NEG_EV_CONTROL` after `PAPER_LEARNING_SHADOW_SKIP`.

This is a narrow log/propagation fix.

Do **not** change live/real trading, TP/SL, RDE, strategy logic, paper sampler caps, P1.1AO probe logic, Android snapshot publishing, Firebase contracts, or economic-health scoring.

## Current status

P1.1AP-I is deployed at:

```text
e80807d P1.1AP-I: Isolate D_NEG_EV_CONTROL from canonical learning
```

Good behavior already observed:

```text
[PAPER_EXIT] ... bucket=D_NEG_EV_CONTROL ...
[PAPER_TRAIN_QUALITY_EXIT] ... training_bucket=D_NEG_EV_CONTROL ...
[PAPER_LEARNING_SHADOW_SKIP] ... bucket=D_NEG_EV_CONTROL ...
[PAPER_BUCKET_UPDATE] ... bucket=D_NEG_EV_CONTROL ...
[PAPER_BUCKET_METRICS] ... bucket=D_NEG_EV_CONTROL ...
```

Bad behavior still observed:

```text
[LEARNING_UPDATE] source=paper_closed_trade symbol=BTCUSDT bucket=D_NEG_EV_CONTROL outcome=LOSS ... ok=True
[LEARNING_UPDATE] source=paper_closed_trade symbol=SOLUSDT bucket=D_NEG_EV_CONTROL outcome=LOSS ... ok=True
```

This violates the P1.1AP-I acceptance criterion:

```text
No [LEARNING_UPDATE] lines for bucket=D_NEG_EV_CONTROL
No [LM_STATE_AFTER_UPDATE] lines for bucket=D_NEG_EV_CONTROL
```

Also observed:

```text
[PAPER_LEARNING_SHADOW_SKIP] trade_id=UNKNOWN ...
```

but the preceding `PAPER_EXIT` has a real trade id:

```text
[PAPER_EXIT] trade_id=paper_be1164bd0ca5 ...
```

So this patch must also fix trade_id propagation into `PAPER_LEARNING_SHADOW_SKIP`.

## Root cause evidence

Grep showed two learning-update log paths:

```text
src/services/trade_executor.py:1555
src/services/paper_trade_executor.py:1310
```

`paper_trade_executor.py` correctly triggers `PAPER_LEARNING_SHADOW_SKIP` and appears to skip canonical learning. The remaining leak is very likely the legacy save/log path in `trade_executor.py` around the paper Firebase save:

```python
db.collection(col("trades_paper")).add(paper_record)
log.warning(
    f"[LEARNING_UPDATE] source=paper_closed_trade symbol={closed_trade.get('symbol')} "
    f"bucket={closed_trade.get('explore_bucket', 'A_STRICT_TAKE')} "
    f"outcome={closed_trade.get('outcome')} net_pnl_pct={closed_trade.get('net_pnl_pct', 0):.4f} ok=True"
)
```

This is not the canonical learning update. It is a legacy telemetry/save log that incorrectly looks like a learning update.

## Required behavior

For D_NEG paper trades:

Allowed:

```text
[PAPER_EXIT]
[PAPER_TRAIN_QUALITY_EXIT]
[PAPER_LEARNING_SHADOW_SKIP]
[PAPER_BUCKET_UPDATE]
[PAPER_BUCKET_METRICS]
diagnostic save to trades_paper if currently used as diagnostic-only storage
```

Not allowed:

```text
[LEARNING_UPDATE] ... bucket=D_NEG_EV_CONTROL
[LM_STATE_AFTER_UPDATE] ... bucket=D_NEG_EV_CONTROL
canonical learning_monitor mutation
```

For non-D_NEG paper trades:

```text
Existing learning behavior must remain unchanged.
C_WEAK_EV_TRAIN, A_STRICT_TAKE, B_RECOVERY_READY should still learn normally where they currently do.
```

## Implementation instructions

### 1. Fix `trade_executor.py` legacy LEARNING_UPDATE log leak

In `src/services/trade_executor.py`, around the paper save path near line ~1555, identify whether `closed_trade` is D_NEG.

Use a robust helper or inline guard:

```python
def _closed_trade_is_d_neg_shadow(closed_trade: dict) -> bool:
    bucket = (
        closed_trade.get("bucket")
        or closed_trade.get("training_bucket")
        or closed_trade.get("explore_bucket")
        or "A_STRICT_TAKE"
    )
    return (
        bucket == "D_NEG_EV_CONTROL"
        or closed_trade.get("training_bucket") == "D_NEG_EV_CONTROL"
        or closed_trade.get("explore_bucket") == "D_NEG_EV_CONTROL"
        or closed_trade.get("learning_shadow_only") is True
        or closed_trade.get("learning_skip_reason") == "d_neg_ev_control_shadow_only"
    )
```

Then keep the diagnostic paper save, but do not emit `[LEARNING_UPDATE]` for D_NEG:

```python
db.collection(col("trades_paper")).add(paper_record)

if not _closed_trade_is_d_neg_shadow(closed_trade):
    log.warning(
        f"[LEARNING_UPDATE] source=paper_closed_trade symbol={closed_trade.get('symbol')} "
        f"bucket={bucket} "
        f"outcome={closed_trade.get('outcome')} net_pnl_pct={closed_trade.get('net_pnl_pct', 0):.4f} ok=True"
    )
else:
    log.debug(
        "[PAPER_TRADE_SAVED_SHADOW] trade_id=%s symbol=%s bucket=%s reason=d_neg_ev_control_shadow_only",
        closed_trade.get("trade_id") or closed_trade.get("id") or "UNKNOWN",
        closed_trade.get("symbol"),
        bucket,
    )
```

Important:
- Do not remove the `trades_paper` diagnostic save unless tests show it is canonical learning storage.
- Do not rename non-D_NEG `LEARNING_UPDATE` logs in this patch.
- Do not change the actual learning model in this patch.

### 2. Fix `trade_id=UNKNOWN` in `paper_trade_executor.py`

In `src/services/paper_trade_executor.py`, inside `_safe_learning_update_for_paper_trade()`, in the D_NEG shadow-skip branch, compute `trade_id` with a fallback chain before logging:

```python
trade_id = (
    canon.get("trade_id")
    or canon.get("id")
    or pos.get("trade_id")
    or pos.get("id")
    or pos.get("paper_trade_id")
    or pnl_data.get("trade_id")
    or pnl_data.get("id")
    or "UNKNOWN"
)
```

Use `trade_id` in the log:

```python
log.warning(
    "[PAPER_LEARNING_SHADOW_SKIP] trade_id=%s symbol=%s bucket=%s training_bucket=%s outcome=%s net_pnl_pct=%.4f reason=%s",
    trade_id,
    canon["symbol"],
    canon["bucket"],
    canon.get("training_bucket", "UNKNOWN"),
    canon["outcome"],
    canon["net_pnl_pct"],
    "d_neg_ev_control_shadow_only",
)
```

Also propagate flags back to the original dicts so downstream code can recognize the shadow-only state:

```python
for target in (pos, pnl_data):
    target["trade_id"] = trade_id
    target["learning_shadow_only"] = True
    target["learning_skipped"] = True
    target["learning_skip_reason"] = "d_neg_ev_control_shadow_only"

canon["trade_id"] = trade_id
canon["learning_shadow_only"] = True
canon["learning_skipped"] = True
canon["learning_skip_reason"] = "d_neg_ev_control_shadow_only"
```

This makes downstream `trade_executor.py` detection more reliable.

## Required tests

Update or add tests in:

```text
tests/test_p11ap_i_d_neg_learning_isolation.py
```

Add coverage for:

### Test 1 — D_NEG shadow skip has real trade_id

Given a D_NEG trade with `trade_id="paper_test_dneg_123"`:

Assert log contains:

```text
[PAPER_LEARNING_SHADOW_SKIP] trade_id=paper_test_dneg_123
```

and not:

```text
trade_id=UNKNOWN
```

### Test 2 — D_NEG does not emit legacy LEARNING_UPDATE

Exercise the paper save path that previously emitted:

```text
[LEARNING_UPDATE] source=paper_closed_trade ... bucket=D_NEG_EV_CONTROL ... ok=True
```

Assert no such log is emitted for D_NEG.

### Test 3 — Non-D_NEG legacy behavior unchanged

For `C_WEAK_EV_TRAIN` or `A_STRICT_TAKE`, assert existing `LEARNING_UPDATE` behavior still occurs where expected.

### Test 4 — D_NEG bucket diagnostics still update

Assert `PAPER_BUCKET_UPDATE` / bucket diagnostics are not removed.

## Required commands

Run new focused tests:

```bash
python -m pytest -q tests/test_p11ap_i_d_neg_learning_isolation.py
```

Run paper + V10 safety suite:

```bash
python -m pytest -q   tests/test_p1_paper_exploration.py   tests/test_paper_mode_p1_1ai.py   tests/test_p11ab_stale_position_quarantine.py   tests/test_v10_13u_patches.py   tests/test_p11ap_i_d_neg_learning_isolation.py
```

Run server-safe full suite:

```bash
python -m pytest -q   --ignore=VERIFICATION_V10_13X   --ignore=venv   --ignore=server_local_backups   --ignore=data/archive   --ignore=data/research
```

## Runtime validation after deploy

Restart:

```bash
sudo systemctl restart cryptomaster
sleep 360
```

Check:

```bash
sudo journalctl -u cryptomaster --since "10 min ago" --no-pager | grep -E "PAPER_EXIT|PAPER_TRAIN_QUALITY_EXIT|PAPER_LEARNING_SHADOW_SKIP|LEARNING_UPDATE|LM_STATE_AFTER_UPDATE|D_NEG_EV_CONTROL|Traceback|UnboundLocalError"
```

Expected for D_NEG:

```text
[PAPER_EXIT] ... bucket=D_NEG_EV_CONTROL ...
[PAPER_TRAIN_QUALITY_EXIT] ... training_bucket=D_NEG_EV_CONTROL ...
[PAPER_LEARNING_SHADOW_SKIP] trade_id=paper_... bucket=D_NEG_EV_CONTROL ...
[PAPER_BUCKET_UPDATE] ... bucket=D_NEG_EV_CONTROL ...
[PAPER_BUCKET_METRICS] ... bucket=D_NEG_EV_CONTROL ...
```

Not expected for D_NEG:

```text
[LEARNING_UPDATE] ... bucket=D_NEG_EV_CONTROL
[LM_STATE_AFTER_UPDATE] ... bucket=D_NEG_EV_CONTROL
[PAPER_LEARNING_SHADOW_SKIP] trade_id=UNKNOWN
```

Exact check:

```bash
sudo journalctl -u cryptomaster --since "10 min ago" --no-pager | grep "\[LEARNING_UPDATE\].*D_NEG_EV_CONTROL"
```

Expected:

```text
no output
```

Shadow-skip check:

```bash
sudo journalctl -u cryptomaster --since "10 min ago" --no-pager | grep "\[PAPER_LEARNING_SHADOW_SKIP\].*D_NEG_EV_CONTROL"
```

Expected:

```text
at least one line after a D_NEG close, with real trade_id
```

## Acceptance criteria

- D_NEG emits `PAPER_LEARNING_SHADOW_SKIP`.
- D_NEG shadow skip has a real `trade_id`, not `UNKNOWN`.
- D_NEG emits no `LEARNING_UPDATE`.
- D_NEG emits no `LM_STATE_AFTER_UPDATE`.
- D_NEG paper exit / quality / bucket metrics remain visible.
- Non-D_NEG learning behavior unchanged.
- Full tests pass.
- No runtime/local files committed.

## Commit message

```text
P1.1AP-I2: Suppress D_NEG legacy LEARNING_UPDATE log
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
