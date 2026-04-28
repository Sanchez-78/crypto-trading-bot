# CryptoMaster P1.1f — Fix Exposure Cap Order + Bucket Metrics Visibility

## Context
P1.1e is deployed, but production validation shows partial success only.

Confirmed:
```text
PAPER_ENTRY -> PAPER_EXIT -> LEARNING_UPDATE
```

Also confirmed:
```text
[LEARNING_UPDATE] source=paper_closed_trade symbol=XRPUSDT bucket=C_WEAK_EV ...
```

Still failing:
```text
[PAPER_ENTRY_BLOCKED] reason=max_open_exceeded open=3
```

Expected but missing:
```text
[PAPER_ENTRY_BLOCKED] reason=max_open_per_symbol ...
[PAPER_ENTRY_BLOCKED] reason=max_open_per_bucket ...
[PAPER_ENTRY_BLOCKED] reason=max_open_per_symbol_bucket ...
[PAPER_BUCKET_METRICS] ...
[PAPER_EXIT] ... bucket=... hold_s=... max_hold_s=...
[PAPER_STATE_LOAD] ...
```

Do not start P1.2 replay training yet.

## Goal
Fix production observability and exploration controls so paper exploration produces reliable bucket-level learning data before replay training.

## Hard Constraints
- No real orders.
- Do not change `live_trading_allowed()`.
- Do not weaken live gates.
- Real prices only.
- No Firebase tick-level writes.
- Keep paper/live metrics separated.
- Do not start P1.2.

## Task 1 — Fix exposure cap order
Current issue: old generic total cap fires before exploration-specific caps.

For exploration trades, run exploration-specific caps before generic total max cap.

Required order:
```text
1. validate price/side
2. classify exploration bucket
3. check exploration caps:
   - max_open_per_symbol = 1
   - max_open_per_bucket = 2
   - max_open_per_symbol_bucket = 1
4. only then check total paper cap
```

Required logs:
```text
[PAPER_ENTRY_BLOCKED] symbol=XRPUSDT reason=max_open_per_symbol bucket=C_WEAK_EV open_symbol=1
[PAPER_ENTRY_BLOCKED] symbol=XRPUSDT reason=max_open_per_bucket bucket=C_WEAK_EV open_bucket=2
[PAPER_ENTRY_BLOCKED] symbol=XRPUSDT reason=max_open_per_symbol_bucket bucket=C_WEAK_EV open_symbol_bucket=1
```

If total cap still fires, include bucket:
```text
[PAPER_ENTRY_BLOCKED] symbol=XRPUSDT reason=max_open_exceeded bucket=C_WEAK_EV open=3
```

Notes:
- Exploration-specific caps apply only to `reason=PAPER_EXPLORE` or `paper_source=exploration_reject`.
- Normal strict TAKE paper trades must remain unaffected unless intentionally sharing the global paper cap.

## Task 2 — Include bucket/hold in PAPER_EXIT
Exit logs must include exploration metadata.

Required log:
```text
[PAPER_EXIT] symbol=XRPUSDT reason=TIMEOUT entry=... exit=... net_pnl_pct=... outcome=LOSS hold_s=600 max_hold_s=600 bucket=C_WEAK_EV
```

Closed trade payload must contain:
```text
explore_bucket
paper_source
original_decision
reject_reason
hold_s
max_hold_s
side_raw
side
size_mult
base_size_usd
final_size_usd
```

If `explore_bucket` is missing on an exploration trade:
```text
[PAPER_EXIT_WARN] reason=missing_bucket symbol=...
```

## Task 3 — Force visible bucket metrics
`update_bucket_metrics()` must be called on every closed exploration paper trade.

Add immediate compact log on every closed exploration trade:
```text
[PAPER_BUCKET_UPDATE] bucket=C_WEAK_EV n=... outcome=LOSS net_pnl_pct=...
```

Keep periodic summary:
```text
[PAPER_BUCKET_METRICS] bucket=C_WEAK_EV n=... wr=... avg=... pf=... timeout_rate=... tp_rate=... sl_rate=...
```

For validation:
- allow first summary after 1 closed trade
- later throttle to 10 minutes
- no tick-level writes

Metrics per bucket:
```text
count
wins
losses
flats
wr
avg_net_pnl_pct
sum_net_pnl_pct
profit_factor
timeout_rate
tp_rate
sl_rate
last_close_ts
```

## Task 4 — Startup state load visibility
On startup/module init, always log:
```text
[PAPER_STATE_LOAD] open_positions=N source=data/paper_open_positions.json
```

If missing:
```text
[PAPER_STATE_LOAD] open_positions=0 source=data/paper_open_positions.json missing=true
```

If corrupt:
```text
[PAPER_STATE_LOAD_ERROR] source=data/paper_open_positions.json err=...
```

## Task 5 — Tests
Add/adjust tests for:

```text
exploration cap runs before total max cap
second same symbol C_WEAK_EV logs max_open_per_symbol
third same bucket logs max_open_per_bucket
same symbol+bucket logs max_open_per_symbol_bucket
generic max_open_exceeded includes bucket if it fires
PAPER_EXIT includes bucket, hold_s, max_hold_s
closed trade payload keeps exploration metadata
bucket update function/log is called on close
PAPER_BUCKET_METRICS emits after first closed trade
PAPER_STATE_LOAD logs on startup/missing file/corrupt file
normal TAKE paper trade behavior unchanged
```

## Validation Commands
Run:
```bash
python -m py_compile \
  src/services/paper_exploration.py \
  src/services/paper_trade_executor.py \
  src/services/trade_executor.py \
  src/services/realtime_decision_engine.py \
  src/services/bucket_metrics.py

python -m pytest \
  tests/test_paper_mode.py \
  tests/test_p0_3_paper_integration.py \
  tests/test_p1_paper_exploration.py \
  -v

git diff --check
```

## Commit
```bash
git add src tests
git commit -m "P1.1f: fix exploration cap order and bucket metrics visibility"
git push origin main
```

## Production Validation
Deploy:
```bash
cd /opt/cryptomaster
git pull origin main
git log --oneline -5
sudo systemctl restart cryptomaster
sleep 60
```

Check:
```bash
sudo journalctl -u cryptomaster --since "45 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_STATE_LOAD|PAPER_STATE_LOAD_ERROR|PAPER_EXPLORE_ENTRY|PAPER_ENTRY|PAPER_ENTRY_BLOCKED|PAPER_EXIT|PAPER_EXIT_WARN|LEARNING_UPDATE|PAPER_BUCKET_UPDATE|PAPER_BUCKET_METRICS|Traceback|ERROR"
```

## Success Criteria
Production must show:
```text
[PAPER_STATE_LOAD] ...
[PAPER_ENTRY_BLOCKED] reason=max_open_per_symbol/max_open_per_bucket/max_open_per_symbol_bucket ...
[PAPER_EXIT] ... bucket=C_WEAK_EV hold_s=... max_hold_s=...
[LEARNING_UPDATE] ... bucket=C_WEAK_EV ...
[PAPER_BUCKET_UPDATE] bucket=C_WEAK_EV ...
[PAPER_BUCKET_METRICS] bucket=C_WEAK_EV ...
```

## Gate Before P1.2
Do not start replay training until:
```text
10+ closed paper exploration trades
LEARNING_UPDATE contains bucket
PAPER_EXIT contains bucket/hold_s/max_hold_s
PAPER_BUCKET_UPDATE visible
PAPER_BUCKET_METRICS visible
No Traceback/ERROR
No real orders
```

## Important Interpretation
If `C_WEAK_EV` keeps showing negative PF and timeout-loss dominance, P1.2 must not simply train more. Replay must compare bucket strategies and tune hold/TP/SL or demote bad buckets.
