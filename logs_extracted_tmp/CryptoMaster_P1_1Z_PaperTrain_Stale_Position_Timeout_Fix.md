# CryptoMaster P1.1Z — Paper-Train Stale Position Reconciliation + Timeout Fix

Token-safe implementation prompt for Claude Code / Codex.

## Current production state

Branch: `main`  
Latest confirmed commit: `4468418` (`P1.1Y`)  
Runtime mode:

```env
TRADING_MODE=paper_train
ENABLE_REAL_ORDERS=false
LIVE_TRADING_CONFIRMED=false
PAPER_TRAINING_ENABLED=true
PAPER_EXPLORATION_ENABLED=true
```

Confirmed good after P1.1V/P1.1X/P1.1Y:
- `LEARNING_UPDATE ok=True` works.
- No `LEARNING_UPDATE_ERROR`.
- No `BUCKET_METRICS_ERROR`.
- No `LIVE_ORDER_DISABLED` spam.
- `A_STRICT_TAKE` disabled in `paper_train`.

Current production problem:
- `C_WEAK_EV_TRAIN` entries open, but legacy/open positions can keep `timeout_s=900` while `max_hold_s=300`.
- These stale paper positions block new training samples:
  - `training_sampler_max_open_per_symbol`
  - `training_sampler_max_open_per_bucket`
  - `max_open_exceeded open=3`
- Example real state:
  - `training_bucket=C_WEAK_EV_TRAIN`
  - `age_s≈578`
  - `max_hold_s=300`
  - `timeout_s=900`
  - should have closed already, but remained open and blocked learning throughput.

## Goal

Make `paper_train` self-healing:
1. Training paper positions must close after effective hold time of 300s.
2. Legacy positions with `timeout_s=900` must not block training.
3. Startup/restart must reconcile stale paper positions safely.
4. Cap checks must count only alive/non-expired positions.
5. No live orders. No strategy/EV changes.

## Hard rules

Do not change:
- RDE scoring
- EV thresholds
- signal generation logic
- live trading enable rules
- Firebase write volume behavior
- real order execution logic

Only change paper training state lifecycle / timeout / stale cleanup.

## Patch requirements

### 1. Add canonical effective hold helper

In `src/services/paper_trade_executor.py`, add a helper similar to:

```python
def _effective_paper_hold_s(pos: dict) -> float:
    if not isinstance(pos, dict):
        return 300.0

    bucket = str(pos.get("training_bucket") or pos.get("bucket") or pos.get("explore_bucket") or "")
    source = str(pos.get("paper_source") or pos.get("mode") or "")

    is_training = (
        bucket == "C_WEAK_EV_TRAIN"
        or source == "training_sampler"
    )

    max_hold = _safe_float(pos.get("max_hold_s"), 300.0)
    timeout = _safe_float(pos.get("timeout_s"), max_hold)

    if is_training:
        return max(30.0, min(max_hold or 300.0, timeout or 300.0, 300.0))

    return max(30.0, timeout or max_hold or 300.0)
```

Use an existing safe-float helper if available. Avoid duplicate helpers if one already exists.

### 2. Normalize loaded/open training positions

Where `paper_open_positions.json` is loaded, normalize each position.

For positions where `training_bucket == C_WEAK_EV_TRAIN` or `paper_source == training_sampler`:
- `training_bucket = "C_WEAK_EV_TRAIN"` if missing/legacy weak EV bucket.
- `max_hold_s = min(existing max_hold_s or 300, 300)`
- `timeout_s = min(existing timeout_s or max_hold_s, max_hold_s, 300)`
- ensure `entry_ts` exists from `created_at` if missing
- ensure `created_at` exists from `entry_ts` if missing

Log once per normalized position:

```text
[PAPER_POSITION_NORMALIZED] trade_id=... symbol=... training_bucket=C_WEAK_EV_TRAIN timeout_s=300 max_hold_s=300
```

### 3. Prune or close stale positions before cap checks

Before any open-cap check in:
- training sampler cap check
- `open_paper_position`
- `_check_training_sampler_caps`
- any helper counting open positions

call a stale reconciliation function:

```python
def _reconcile_stale_paper_positions(now=None, price_by_symbol=None) -> int:
    ...
```

Behavior:
- inspect current in-memory paper positions
- for each position, compute `age_s = now - entry_ts`
- if `age_s >= _effective_paper_hold_s(pos)`, close it as `TIMEOUT`
- if current price is available for that symbol, use it
- else use `last_price` if present
- else use `entry_price` and mark outcome as `FLAT`
- must call the existing safe close path so learning and bucket metrics update once
- must not raise
- log:

```text
[PAPER_STALE_RECONCILE] trade_id=... symbol=... age_s=... effective_hold_s=... action=closed reason=TIMEOUT
```

If closing during load is too risky because price data is not ready, mark `stale_pending=True` and close on first tick for that symbol. But stale pending positions must not count against open caps.

### 4. Cap checks must ignore stale positions

When checking:
- max open global
- max open per symbol
- max open per bucket

do not count positions where:

```python
now - entry_ts >= _effective_paper_hold_s(pos)
```

If using pending close instead of immediate close, exclude `stale_pending=True` from cap counts.

This is critical: stale/expired paper positions must never block new `C_WEAK_EV_TRAIN` entries.

### 5. Fix timeout close path

Find the paper position close loop. It currently appears to respect `timeout_s=900` even when `max_hold_s=300`.

Change timeout decision to:

```python
effective_hold_s = _effective_paper_hold_s(pos)
if hold_s >= effective_hold_s:
    close reason = TIMEOUT
```

The `[PAPER_EXIT]` log should show both values:

```text
[PAPER_EXIT] ... hold_s=300 max_hold_s=300 timeout_s=300 effective_hold_s=300 ...
```

### 6. Add startup health log

After loading/reconciling open positions, log:

```text
[PAPER_STATE_RECONCILE_SUMMARY] loaded=N normalized=N stale_closed=N stale_pending=N alive=N
```

### 7. Tests required

Add regression tests in `tests/test_paper_mode.py`:

1. Legacy training position with `timeout_s=900`, `max_hold_s=300`, age 578s is considered expired.
2. Expired training position does not count against per-symbol cap.
3. Expired training position does not count against per-bucket cap.
4. Expired training position is closed/reconciled with reason `TIMEOUT`.
5. Learning update is called exactly once for reconciled stale close.
6. Bucket metrics update is called exactly once.
7. Non-training paper position keeps its configured timeout behavior.
8. No live order path is called in `paper_train`.
9. `PAPER_STATE_RECONCILE_SUMMARY` emits expected counts.

Run:

```bash
PYTHONPATH=. pytest -q tests/test_paper_mode.py
PYTHONPATH=. pytest -q tests/test_p1_paper_exploration.py
PYTHONPATH=. python3 -m compileall src
```

## Production validation after deploy

```bash
cd /opt/cryptomaster
git pull origin main
sudo systemctl restart cryptomaster
sleep 420

sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager \
| grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_STATE_RECONCILE_SUMMARY|PAPER_POSITION_NORMALIZED|PAPER_STALE_RECONCILE|PAPER_TRAIN_ENTRY|PAPER_EXIT|LEARNING_UPDATE|PAPER_ENTRY_BLOCKED|LIVE_ORDER_DISABLED|ERROR|Traceback|TypeError"
```

Expected:
- `commit=<new_commit>`
- `PAPER_STATE_RECONCILE_SUMMARY` appears once on boot
- `PAPER_TRAIN_ENTRY > 0`
- after 5–6 minutes, `PAPER_EXIT > 0`
- `LEARNING_UPDATE ok=True > 0`
- `LIVE_ORDER_DISABLED = 0`
- `LEARNING_UPDATE_ERROR = 0`
- `Traceback/TypeError = 0`
- `PAPER_ENTRY_BLOCKED` may appear only when two fresh training samples are already open, not because stale positions are stuck

Count commands:

```bash
sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager | grep -c "PAPER_TRAIN_ENTRY"
sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager | grep -c "PAPER_EXIT"
sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager | grep -c "LEARNING_UPDATE.*ok=True"
sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager | grep -c "LIVE_ORDER_DISABLED"
sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager | grep -E "LEARNING_UPDATE_ERROR|PAPER_TRAIN_METRICS_ERROR|BUCKET_METRICS_ERROR|Traceback|TypeError|UnboundLocalError|Logging error|ERROR" | wc -l
```

## Optional emergency unblock before/after deploy

Use only if current stale positions block testing. This is safe because these are paper positions only.

```bash
cd /opt/cryptomaster
sudo systemctl stop cryptomaster

mkdir -p data/archive
cp -a data/paper_open_positions.json "data/archive/paper_open_positions_unblock_$(date +%Y%m%d_%H%M%S).json"

PYTHONPATH=. python3 - <<'PY'
import json, os
p = "data/paper_open_positions.json"
old = json.load(open(p)) if os.path.exists(p) else {}
print("clearing_open_positions=", len(old))
json.dump({}, open(p, "w"), indent=2)
print("paper_open_positions reset to {}")
PY

chown cryptomaster:cryptomaster data/paper_open_positions.json
chmod 664 data/paper_open_positions.json

sudo systemctl start cryptomaster
```

## Done criteria

P1.1Z is done only when production shows:

```text
PAPER_TRAIN_ENTRY > 0
PAPER_EXIT > 0 after ~5 min
LEARNING_UPDATE ok=True > 0
LIVE_ORDER_DISABLED = 0
LEARNING_UPDATE_ERROR/Traceback/TypeError = 0
stale positions no longer block caps
```
