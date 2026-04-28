# CryptoMaster V10.13u+20 — Token-Safe P0.3 Production Validation/Fix

Use this before any P1 work. **Do not implement exploration/replay yet.**

## Problem

Live validation failed. Production logs show only:

```text
[RUNTIME_VERSION] commit=eb6c9b1
```

Missing required P0.3 logs:

```text
[TRADING_MODE]
[PAPER_ROUTED]
[PAPER_ENTRY]
[PAPER_EXIT]
[LEARNING_UPDATE]
```

Current HEAD shows only:

```text
eb6c9b1 P0.2: Implement paper executor with real live price trading
```

Likely issue: paper executor exists, but P0.3 runtime integration is missing or not deployed.

---

## Goal

Fix/verify **P0.3 only**:

```text
TAKE → paper executor → real-price exits → closed paper trade → Firebase/canonical learning
```

Do not start P1 until production shows paper entries/exits/learning.

---

## Step 1 — Inspect production code

Run:

```bash
cd /opt/cryptomaster
git status --short
git log --oneline -10

grep -R "PAPER_ROUTED\|_save_paper_trade_closed\|update_paper_positions\|open_paper_position\|LEARNING_UPDATE" -n src bot2 start.py | head -120

grep -R "TRADING_MODE\|log_runtime_mode\|runtime_mode\|is_paper_mode\|live_trading_allowed" -n src bot2 start.py | head -120
```

Interpretation:

```text
If P0.3 strings are missing → implement P0.3.
If strings exist but no logs → runtime path mismatch or mode/env issue.
```

---

## Step 2 — Validate runtime mode

Run:

```bash
cd /opt/cryptomaster
source venv/bin/activate || true

python - <<'PY'
from src.core.runtime_mode import (
    get_trading_mode,
    is_paper_mode,
    live_trading_allowed,
    paper_exploration_enabled,
    real_orders_enabled,
)
print("mode=", get_trading_mode())
print("is_paper_mode=", is_paper_mode())
print("real_orders=", real_orders_enabled())
print("live_allowed=", live_trading_allowed())
print("paper_exploration=", paper_exploration_enabled())
PY
```

Expected:

```text
mode= paper_live
is_paper_mode= True
real_orders= False
live_allowed= False
paper_exploration= True
```

If not, fix `/opt/cryptomaster/.env`:

```env
TRADING_MODE=paper_live
ENABLE_REAL_ORDERS=false
LIVE_TRADING_CONFIRMED=false
PAPER_EXPLORATION_ENABLED=true
PAPER_EXPLORATION_PROFILE=balanced
```

---

## Step 3 — Implement missing P0.3 integration if needed

Relevant production path:

```text
systemd → start.py → bot2/main.py → trade_executor.handle_signal/on_price
```

### 3.1 Log runtime mode from real production entrypoint

At startup, log:

```text
[TRADING_MODE] mode=paper_live real_orders=false live_allowed=false exploration=true
```

Do this in actual entrypoint used by systemd, not unused modules.

### 3.2 Route TAKE to paper executor

In `src/services/trade_executor.py` or actual TAKE handler:

```python
from src.core.runtime_mode import is_paper_mode, live_trading_allowed, get_trading_mode
from src.services.paper_trade_executor import open_paper_position

if is_paper_mode():
    trade = open_paper_position(signal, price=current_real_price, ts=now, reason="RDE_TAKE")
    log.warning("[PAPER_ROUTED] symbol=%s trade_id=%s mode=%s", symbol, trade.get("trade_id"), get_trading_mode())
    return trade

if not live_trading_allowed():
    log.error("[LIVE_ORDER_DISABLED] symbol=%s side=%s mode=%s", symbol, side, get_trading_mode())
    return {"status": "blocked", "reason": "LIVE_ORDER_DISABLED"}
```

Requirements:
- use real current price only
- no Binance real order call in paper mode
- preserve future live path behind `live_trading_allowed()`

### 3.3 Update paper positions from real price loop

In actual `on_price()` / tick loop:

```python
from src.services.paper_trade_executor import update_paper_positions

closed = update_paper_positions({symbol: price}, ts=now)
for trade in closed:
    _save_paper_trade_closed(trade)
```

### 3.4 Save closed paper trade and update learning

Add/verify:

```python
def _save_paper_trade_closed(trade: dict) -> None:
    save_paper_trade_closed(trade)  # Firebase trades_paper
    update_metrics(...)             # learning/canonical metrics
    log.warning(
        "[LEARNING_UPDATE] source=paper_closed_trade symbol=%s regime=%s bucket=%s net_pnl_pct=%.4f outcome=%s",
        trade.get("symbol"),
        trade.get("regime"),
        trade.get("explore_bucket", "A_STRICT_TAKE"),
        float(trade.get("net_pnl_pct") or 0.0),
        trade.get("outcome"),
    )
```

Rules:
```text
write closed paper trades only
no tick writes
collection: trades_paper
TIMEOUT outcome from net_pnl_pct, not reason
paper/live metrics separated
```

---

## Step 4 — Tests

Run/add focused tests:

```bash
python -m py_compile src/core/runtime_mode.py src/services/paper_trade_executor.py src/services/trade_executor.py

python -m pytest   tests/test_paper_mode.py   tests/test_live_order_guard.py   tests/test_p0_3_paper_integration.py   -v

git diff --check
```

Required coverage:

```text
paper mode routes TAKE to open_paper_position
paper mode never calls live exchange executor
on_price closes paper positions
closed paper trade calls Firebase writer
closed paper trade triggers learning update
live_real blocked unless all live_trading_allowed flags true
```

---

## Step 5 — Commit/deploy

```bash
git add src tests .env.example docs || true
git commit -m "P0.3: wire paper executor into production runtime and learning"
git push origin main

sudo systemctl restart cryptomaster
sleep 60
```

---

## Step 6 — Validate production logs

Run:

```bash
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager   | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_ROUTED|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|LIVE_ORDER_DISABLED|Traceback|ERROR"
```

Minimum success:

```text
[RUNTIME_VERSION] commit=<latest>
[TRADING_MODE] mode=paper_live real_orders=false live_allowed=false
```

Full P0.3 success:

```text
[PAPER_ROUTED]
[PAPER_ENTRY]
[PAPER_EXIT]
[LEARNING_UPDATE] source=paper_closed_trade
```

If no `[PAPER_ENTRY]` within 30 minutes, debug only P0 routing:

```text
1. Is handle_signal() reached?
2. Does RDE produce TAKE?
3. Is is_paper_mode() true in systemd runtime?
4. Is current_real_price passed into open_paper_position()?
5. Is paper max-open cap blocking?
6. Is code returning before paper executor call?
7. Is production using a different module/path?
```

---

## Stop condition

Do **not** start P1 until all are true:

```text
✅ [TRADING_MODE] appears in production logs
✅ [PAPER_ROUTED] appears
✅ [PAPER_ENTRY] appears
✅ [PAPER_EXIT] appears
✅ [LEARNING_UPDATE] source=paper_closed_trade appears
✅ no Traceback
✅ live orders still blocked by default
```

Only after this proceed to P1:

```text
paper_exploration_override()
replay_train.py
bucket metrics
```
