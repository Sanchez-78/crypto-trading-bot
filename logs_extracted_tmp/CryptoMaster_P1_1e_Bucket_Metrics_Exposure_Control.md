# CryptoMaster P1.1e — Bucket Learning Metrics + Exploration Exposure Control

## Context
P1.1d production validation succeeded.

Confirmed live flow:
```text
PAPER_ENTRY -> PAPER_STATE_SAVE -> PAPER_EXIT -> LEARNING_UPDATE
```

Robot now paper-trades on real market prices, closes trades, and triggers learning.

Observed logs:
```text
[PAPER_ENTRY] ... size_usd=8.00 reason=PAPER_EXPLORE
[PAPER_EXIT] symbol=XRPUSDT reason=TIMEOUT ... outcome=LOSS
[LEARNING_UPDATE] source=paper_closed_trade symbol=XRPUSDT outcome=LOSS net_pnl_pct=-0.0650
[PAPER_ENTRY_BLOCKED] reason=max_open_exceeded open=3
```

## Problems
1. `[LEARNING_UPDATE]` does not include `bucket`.
2. Bucket-level performance is not measurable.
3. `C_WEAK_EV` fills all 3 open paper slots.
4. Same symbol/bucket repeats too much.
5. C_WEAK_EV currently exits mostly by TIMEOUT as LOSS.
6. Do not start P1.2 replay training before bucket metrics are visible.

## Hard constraints
- No real orders.
- Do not change `live_trading_allowed()`.
- Do not weaken live gates.
- Do not start replay training.
- Real prices only.
- No Firebase tick-level writes.
- Keep paper/live metrics separated.

## Task 1 — Add bucket to learning update
Ensure closed exploration trades pass these fields through `_save_paper_trade_closed()` and learning/metrics payload:

```text
paper_source
explore_bucket
original_decision
reject_reason
size_mult
base_size_usd
final_size_usd
max_hold_s
side_raw
side
```

Required log:
```text
[LEARNING_UPDATE] source=paper_closed_trade symbol=XRPUSDT bucket=C_WEAK_EV outcome=LOSS net_pnl_pct=-0.0650
```

If missing:
```text
[LEARNING_UPDATE_WARN] reason=missing_bucket symbol=...
```

Tests:
- closed exploration trade logs bucket
- payload contains bucket + source metadata
- non-exploration paper trade still logs safely
- no live trade collection used

## Task 2 — Add bucket metrics
Track closed paper trade stats by `explore_bucket`.

Metrics:
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

Periodic log every 5–10 minutes:
```text
[PAPER_BUCKET_METRICS] bucket=C_WEAK_EV n=12 wr=25.0% avg=-0.0712 pf=0.42 timeout_rate=91.7% tp_rate=0.0% sl_rate=8.3%
```

Quota:
- in-memory aggregation allowed
- optional Firebase metrics write max once per 5–10 minutes
- no writes on every tick

Tests:
- metrics update after closed WIN/LOSS/FLAT
- PF handles zero loss/gain safely
- timeout_rate/tp_rate/sl_rate correct
- log emits bucket metrics

## Task 3 — Exploration exposure caps
Prevent one bucket/symbol from filling all slots.

Rules:
```text
max_open_total = existing paper executor max
max_open_per_symbol = 1
max_open_per_bucket = 2
max_open_per_symbol_bucket = 1
```

Required block logs:
```text
[PAPER_ENTRY_BLOCKED] symbol=XRPUSDT reason=max_open_per_symbol bucket=C_WEAK_EV open_symbol=1
[PAPER_ENTRY_BLOCKED] symbol=XRPUSDT reason=max_open_per_bucket bucket=C_WEAK_EV open_bucket=2
[PAPER_ENTRY_BLOCKED] symbol=XRPUSDT reason=max_open_per_symbol_bucket bucket=C_WEAK_EV open_symbol_bucket=1
```

Do not block strict TAKE paper trades unless they intentionally share total paper cap.

Tests:
- second same symbol/bucket exploration blocked
- third same bucket blocked if bucket cap reached
- different bucket/symbol can still open
- strict TAKE behavior unchanged

## Task 4 — Log hold window
C_WEAK_EV hold window must be visible.

Entry:
```text
[PAPER_EXPLORE_ENTRY] ... bucket=C_WEAK_EV max_hold_s=600 ...
```

Timeout:
```text
[PAPER_EXIT] ... reason=TIMEOUT hold_s=600 max_hold_s=600 bucket=C_WEAK_EV
```

If current C_WEAK_EV uses another value, make constant explicit and log it.

Tests:
- max_hold_s stored in position
- timeout close includes hold_s and max_hold_s
- C_WEAK_EV constant matches intended config

## Task 5 — Startup state load log
Every restart must log:
```text
[PAPER_STATE_LOAD] open_positions=N source=data/paper_open_positions.json
```

If file exists but log is missing, fix logging path.

Tests:
- import/startup load logs state
- missing file logs open_positions=0
- corrupt file logs load error and starts empty

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
git commit -m "P1.1e: add bucket learning metrics and exploration exposure caps"
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
sudo journalctl -u cryptomaster --since "45 minutes ago" --no-pager \
  | grep -E "PAPER_STATE_LOAD|PAPER_EXPLORE_ENTRY|PAPER_ENTRY|PAPER_ENTRY_BLOCKED|PAPER_EXIT|LEARNING_UPDATE|LEARNING_UPDATE_WARN|PAPER_BUCKET_METRICS|Traceback|ERROR"
```

Success:
```text
[LEARNING_UPDATE] ... bucket=C_WEAK_EV ...
[PAPER_BUCKET_METRICS] bucket=C_WEAK_EV ...
[PAPER_ENTRY_BLOCKED] reason=max_open_per_symbol/max_open_per_bucket/max_open_per_symbol_bucket ...
[PAPER_EXIT] ... hold_s=... max_hold_s=... bucket=...
```

## Decision gate before P1.2
Only start P1.2 replay training after production shows at least:
```text
10+ closed paper exploration trades
LEARNING_UPDATE contains bucket
PAPER_BUCKET_METRICS visible
No real orders
No Traceback/ERROR
```
