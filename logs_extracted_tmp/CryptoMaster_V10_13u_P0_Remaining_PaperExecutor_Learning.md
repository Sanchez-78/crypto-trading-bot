# CryptoMaster V10.13u — P0 Remaining Prompt: Paper Executor + Paper Learning

Use this as the next Claude Code/Codex prompt. Do **not** start P1 exploration/replay yet. Finish P0 foundation first.

## Decision

Proceed with **P0 remaining**:

```text
P0.2 Paper Executor
P0.3 Paper Exits + Canonical/Firebase Learning
```

Goal: bot must open, manage, close, persist, and learn from **paper trades using real live prices**, while real-money trading remains blocked by `live_trading_allowed()`.

---

## Current completed foundation

Already done:

```text
src/core/runtime_mode.py
.env.example safe defaults
live_trading_allowed() guard
runtime status logging
TRADING_MODE=paper_live default
ENABLE_REAL_ORDERS=false default
```

Do not rewrite this unless integration requires small fixes.

---

## P0.2 — Implement paper executor

Create:

```text
src/services/paper_trade_executor.py
```

Required API:

```python
open_paper_position(signal: dict, price: float, ts: float, reason: str) -> dict
update_paper_positions(symbol_prices: dict[str, float], ts: float) -> list[dict]
close_paper_position(position_id: str, price: float, ts: float, reason: str) -> dict
get_paper_open_positions() -> list[dict]
```

### Requirements

Paper positions must use **real live prices** from current runtime feed.

No synthetic/fake/random price.

Each paper position must store:

```text
trade_id
mode=paper_live
symbol
side/action
entry_price
entry_ts
size_usd
tp
sl
timeout_s
regime
features
ev_at_entry
score_at_entry
p_at_entry
coh_at_entry
af_at_entry
rde_decision
paper_explore=false for now
explore_bucket=A_STRICT_TAKE for normal TAKE
original_reject_reason=None
```

Each close must produce a closed trade dict with:

```text
exit_price
exit_ts
exit_reason
duration_s
gross_pnl_pct
fee_pct
slippage_pct
net_pnl_pct
outcome=WIN|LOSS|FLAT from net_pnl_pct
unit_pnl
weighted_pnl
created_at
```

PnL rules:

```text
BUY:  (exit-entry)/entry
SELL: (entry-exit)/entry
gross_pnl_pct = direction return * 100
fee_pct = entry_fee + exit_fee
slippage_pct = configured estimate
net_pnl_pct = gross_pnl_pct - fee_pct - slippage_pct
outcome is based on net_pnl_pct, never on exit reason
TIMEOUT can be WIN/LOSS/FLAT depending on net_pnl_pct
```

Add configurable defaults:

```env
PAPER_INITIAL_EQUITY_USD=10000
PAPER_POSITION_SIZE_USD=100
PAPER_FEE_PCT=0.15
PAPER_SLIPPAGE_PCT=0.03
PAPER_MAX_OPEN_POSITIONS=3
PAPER_MAX_POSITION_AGE_S=900
```

Logs:

```text
[PAPER_ENTRY] symbol=... side=... price=... size_usd=... ev=... score=... reason=...
[PAPER_EXIT] symbol=... reason=... entry=... exit=... net_pnl_pct=... outcome=...
```

---

## P0.2b — Route production TAKE to paper executor

Find actual production path:

```text
systemd → start.py → bot2/main.py
```

In paper modes:

```python
if is_paper_mode():
    open_paper_position(signal, price=current_real_price, ts=now, reason="RDE_TAKE")
else:
    live executor only if live_trading_allowed()
```

Do not call real exchange order functions in `paper_live` or `replay_train`.

If real order is attempted while disabled:

```text
[LIVE_ORDER_DISABLED] ...
```

Acceptance log after restart:

```text
[TRADING_MODE] mode=paper_live real_orders=false live_allowed=false exploration=true
[PAPER_ENTRY] ...
```

---

## P0.3 — Paper exits

Integrate `update_paper_positions()` into the real price loop.

Exit conditions:

```text
TP hit
SL hit
timeout hit
manual/forced close if applicable
```

Use current real price for exit.

No close without real price.

Logs:

```text
[PAPER_EXIT] symbol=... reason=TP|SL|TIMEOUT|... net_pnl_pct=...
```

---

## P0.3b — Canonical metrics + Firebase learning

Closed paper trades must feed learning and metrics.

Relevant modules to inspect/update:

```text
src/services/firebase_client.py
src/services/canonical_metrics.py
src/services/learning_monitor.py
src/services/learning_event.py
```

Add safe writer:

```python
save_paper_trade_closed(trade: dict) -> None
```

Collections:

```text
trades_paper
trades_paper_compressed
metrics
model_state
```

Rules:

```text
write only closed paper trades
batch writes where possible
no tick writes
keep paper/live metrics separated
canonical training metrics may include paper/replay
future real-live metrics must stay separate
```

Learning update log:

```text
[LEARNING_UPDATE] source=paper_closed_trade symbol=... regime=... bucket=A_STRICT_TAKE net_pnl_pct=...
```

---

## Tests to add now

Create/update:

```text
tests/test_paper_mode.py
tests/test_live_order_guard.py
tests/test_v10_13u_patches.py if needed
```

Required tests:

```text
paper executor opens position with real price
paper executor refuses missing/invalid price
paper BUY PnL correct after fees/slippage
paper SELL PnL correct after fees/slippage
TIMEOUT outcome based on net PnL, not reason
paper close produces canonical trade schema
closed paper trade calls Firebase writer
paper mode routes TAKE to paper executor
paper mode never calls live exchange executor
live_real still blocked unless all live_trading_allowed conditions pass
```

Run:

```bash
python -m py_compile src/core/runtime_mode.py src/services/paper_trade_executor.py
python -m pytest tests/test_paper_mode.py tests/test_live_order_guard.py tests/test_v10_13u_patches.py -v
git diff --check
```

---

## Deployment validation

After commit/deploy:

```bash
sudo systemctl restart cryptomaster
sudo journalctl -u cryptomaster --since "20 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|TRADING_MODE|LIVE_ORDER_DISABLED|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|Traceback"
```

Expected:

```text
[TRADING_MODE] mode=paper_live real_orders=false live_allowed=false
[PAPER_ENTRY] ...
[PAPER_EXIT] ...
[LEARNING_UPDATE] source=paper_closed_trade ...
```

If no `[PAPER_ENTRY]` appears within 30 minutes, do **not** add diagnostics first. Confirm:
1. RDE TAKE path reaches paper executor.
2. real current price is available.
3. paper max-open cap not blocking.
4. paper executor is imported in production runtime path, not only tests.

---

## Stop condition

P0 remaining is complete only when:

```text
✅ paper_live opens positions from TAKE using real prices
✅ paper_live closes positions from real prices
✅ closed paper trades have net PnL after fees/slippage
✅ TIMEOUT is classified by net PnL
✅ closed paper trades are saved safely
✅ learning update is triggered
✅ real orders remain blocked by default
✅ tests pass
```

Only after this move to P1:

```text
paper_exploration_override()
replay_train.py
exploration buckets
```
