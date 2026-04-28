# CryptoMaster P1.1d — Close Paper Exploration Trades + Learning Update

## Context
P1.1c is live and validated. Exploration sizing is now correct:
- `C_WEAK_EV` opens `size_usd=8.00`, not `100.00`
- Logs confirmed:
  - `[PAPER_EXPLORE_ENTRY] ... base_size_usd=100.00 size_mult=0.0800 final_size_usd=8.00`
  - `[PAPER_ENTRY] ... size_usd=8.00 reason=PAPER_EXPLORE`

Do **not** start P1.2/replay training yet.

## Current risk
Paper exploration now opens trades, but training is useful only if:
1. paper positions close via TP/SL/TIMEOUT,
2. closed trades feed learning,
3. open paper positions survive restart,
4. side aliases are normalized,
5. skip reasons are diagnostic.

## Hard constraints
- No real orders.
- Do not change `live_trading_allowed()`.
- Do not weaken live gates.
- Do not write Firebase on every tick.
- Use real market prices only.
- Do not synthesize prices.
- Do not hardcode BUY/SELL for `NO_CANDIDATE_PATTERN` when side is unknown.
- Keep paper/live metrics separated.

## Task 1 — Verify/fix paper exits
Ensure `update_paper_positions()` is called on every real price tick and closes paper positions on:
- TP
- SL
- TIMEOUT/max_hold_s

On close:
- remove from in-memory open positions
- update `data/paper_open_positions.json`
- return closed trade to caller

Required log:
```text
[PAPER_EXIT] symbol=... reason=TP/SL/TIMEOUT entry=... exit=... net_pnl_pct=... outcome=WIN/LOSS/FLAT bucket=C_WEAK_EV
[PAPER_STATE_SAVE] open_positions=N source=data/paper_open_positions.json
```

Tests:
- open C_WEAK_EV paper position
- simulate TP hit
- closed trade returned
- open position removed
- persistence file updated

## Task 2 — Feed closed exploration trades into learning
When an exploration paper trade closes:
- write one closed trade doc to Firebase `trades_paper`
- call existing canonical metrics/learning update
- never write to live trade collection

Required log:
```text
[LEARNING_UPDATE] source=paper_closed_trade symbol=... bucket=C_WEAK_EV outcome=WIN/LOSS/FLAT net_pnl_pct=...
```

Closed trade schema must include:
```text
paper_source
explore_bucket
original_decision
reject_reason
size_mult
base_size_usd
final_size_usd
entry_price
exit_price
entry_ts
exit_ts
net_pnl_pct
outcome
exit_reason
```

Tests:
- closed exploration trade triggers learning update
- bucket present in payload/log
- Firebase collection is `trades_paper`
- one write per closed trade only

## Task 3 — Confirm restart persistence
Open paper positions must survive systemd restart.

Expected file:
```text
data/paper_open_positions.json
```

Required logs:
```text
[PAPER_STATE_LOAD] open_positions=N source=data/paper_open_positions.json
[PAPER_STATE_SAVE] open_positions=N source=data/paper_open_positions.json
[PAPER_STATE_LOAD_ERROR] err=...
[PAPER_STATE_SAVE_ERROR] err=...
```

Tests:
- open paper position
- save state
- clear memory
- load state
- position exists
- simulate exit after reload
- learning still updates

## Task 4 — Normalize side/action
Paper executor must use canonical internal side.

Accepted aliases:
```text
BUY  -> BUY
LONG -> BUY
SELL -> SELL
SHORT -> SELL
```

Store:
```text
side_raw
side
```

PnL must use canonical `side`.

Tests:
- BUY and LONG produce same long PnL
- SELL and SHORT produce same short PnL
- invalid side rejects with clear reason

## Task 5 — Improve skip reasons
Replace generic skips where possible.

Use:
```text
neg_control_hourly_cap
neg_ev_outside_control_profile
invalid_ev
missing_price
no_side
invalid_side
no_bucket_matched
```

For `NO_CANDIDATE_PATTERN`, keep `no_side` if side cannot be safely inferred.

## Validation
Run:
```bash
python -m py_compile \
  src/services/paper_exploration.py \
  src/services/paper_trade_executor.py \
  src/services/trade_executor.py \
  src/services/realtime_decision_engine.py

python -m pytest \
  tests/test_paper_mode.py \
  tests/test_p0_3_paper_integration.py \
  tests/test_p1_paper_exploration.py \
  -v

git diff --check
```

Commit:
```bash
git add src tests
git commit -m "P1.1d: close exploration paper trades and feed learning"
git push origin main
```

## Production validation
Deploy:
```bash
cd /opt/cryptomaster
git pull origin main
sudo systemctl restart cryptomaster
sleep 60
```

Check:
```bash
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_STATE_LOAD|PAPER_STATE_SAVE|PAPER_EXPLORE_ENTRY|PAPER_EXPLORE_SKIP|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|Traceback|ERROR"
```

Success:
```text
[PAPER_STATE_LOAD] open_positions=...
[PAPER_STATE_SAVE] open_positions=...
[PAPER_ENTRY] ... size_usd=8.00 reason=PAPER_EXPLORE
[PAPER_EXIT] ... bucket=C_WEAK_EV
[LEARNING_UPDATE] source=paper_closed_trade bucket=C_WEAK_EV
```

## Extra immediate check
Before coding, check whether current open paper trades already closed:
```bash
sudo journalctl -u cryptomaster --since "2026-04-28 07:40:00" --no-pager \
  | grep -E "PAPER_STATE|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|Traceback|ERROR"
```

If no `PAPER_EXIT` after 15+ minutes from entry, prioritize Task 1.
