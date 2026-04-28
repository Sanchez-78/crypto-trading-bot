# CryptoMaster P1.1h — Robust Paper State Loader

## Context
P1.1g is now production-confirmed.

Confirmed in production:
```text
[RUNTIME_VERSION] ... commit=456a5d6
[PAPER_EXIT] ... hold_s=600 max_hold_s=600 bucket=C_WEAK_EV
[LEARNING_UPDATE] ... bucket=C_WEAK_EV ...
[PAPER_BUCKET_UPDATE] bucket=C_WEAK_EV ...
[PAPER_BUCKET_METRICS] bucket=C_WEAK_EV ...
```

The previous max-hold bug is fixed:
```text
hold_s=900 max_hold_s=600  # old bad state
hold_s=600 max_hold_s=600  # fixed
```

New issue:
```text
[PAPER_STATE_LOAD_ERROR] err='list' object has no attribute 'items'
```

Cause:
`data/paper_open_positions.json` may contain a list (`[]`) after manual reset, but loader expects a dict (`{}`) and calls `.items()`.

## Goal
Make paper state loading robust and backward-compatible.

## Hard Constraints
- No real orders.
- Do not change live trading guards.
- Do not change trading decisions.
- Real prices only.
- No Firebase tick writes.
- Keep paper/live metrics separated.
- Do not start P1.2.

## Task 1 — Accept dict and list state formats
Update paper state loader in `src/services/paper_trade_executor.py`.

Supported formats:

### Canonical dict format
```json
{
  "paper_trade_id_1": {"symbol": "XRPUSDT", "side": "BUY"},
  "paper_trade_id_2": {"symbol": "ADAUSDT", "side": "SELL"}
}
```

### Legacy/list format
```json
[
  {"trade_id": "paper_trade_id_1", "symbol": "XRPUSDT", "side": "BUY"},
  {"id": "paper_trade_id_2", "symbol": "ADAUSDT", "side": "SELL"}
]
```

### Empty list
```json
[]
```

Must load as empty state without error.

## Task 2 — Migrate list to dict
If file is a list:
- convert list to dict
- key = `trade_id` if present
- else key = `id` if present
- else generate stable fallback key, e.g. `legacy_<index>_<symbol>_<opened_at_ts>`
- run existing legacy-position migration on every item
- save back in canonical dict format

Required log:
```text
[PAPER_STATE_MIGRATE] from=list to=dict count=N
```

## Task 3 — Normal load logs
On every startup/module load, always log one of these:

```text
[PAPER_STATE_LOAD] open_positions=0 source=data/paper_open_positions.json
[PAPER_STATE_LOAD] open_positions=N source=data/paper_open_positions.json
[PAPER_STATE_LOAD] open_positions=0 source=data/paper_open_positions.json missing=true
[PAPER_STATE_MIGRATE] from=list to=dict count=N
[PAPER_STATE_LOAD_ERROR] source=data/paper_open_positions.json err=...
```

If corrupt JSON:
- log `[PAPER_STATE_LOAD_ERROR]`
- start with empty state
- do not crash

## Task 4 — Save canonical format
After any load/migration/save, ensure `data/paper_open_positions.json` is saved as dict, not list.

Never write `[]`; empty state should be:
```json
{}
```

## Task 5 — Preserve P1.1g migration
For every loaded position, preserve/ensure:

```text
opened_at_ts
max_hold_s
explore_bucket
paper_source
side
side_raw
size_mult
base_size_usd
final_size_usd
```

If `max_hold_s` missing:
- infer by `explore_bucket`
- C_WEAK_EV = 600
- B_RECOVERY_READY = 900
- D_NEG_EV_CONTROL = 300
- E_NO_PATTERN = 300
- unknown/default = 600
- log migration count

## Task 6 — Tests
Add tests in existing paper tests.

Required tests:
```text
empty list state loads as empty without error
list of positions migrates to dict
dict state loads normally
corrupt JSON logs error and starts empty
save writes canonical dict format
legacy position missing max_hold_s gets inferred value
C_WEAK_EV legacy position gets max_hold_s=600
```

## Validation
Run:
```bash
python -m py_compile src/services/paper_trade_executor.py

python -m pytest   tests/test_paper_mode.py   tests/test_p1_paper_exploration.py   tests/test_p0_3_paper_integration.py   -v

git diff --check
```

## Commit
```bash
git add src tests
git commit -m "P1.1h: make paper state loader robust to list format"
git push origin main
```

## Production deploy
```bash
cd /opt/cryptomaster
git pull origin main
git log --oneline -7

sudo systemctl stop cryptomaster
echo "{}" > data/paper_open_positions.json
sudo systemctl start cryptomaster
sleep 60
```

## Production validation
```bash
sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager   | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_STATE_LOAD|PAPER_STATE_MIGRATE|PAPER_STATE_LOAD_ERROR|PAPER_EXPLORE_ENTRY|PAPER_EXIT|LEARNING_UPDATE|PAPER_BUCKET_UPDATE|PAPER_BUCKET_METRICS|Traceback|ERROR"
```

Success criteria:
```text
[PAPER_STATE_LOAD] open_positions=0 ...
No PAPER_STATE_LOAD_ERROR for []
No Traceback/ERROR
New positions still open with max_hold_s=600 for C_WEAK_EV
New exits show hold_s=600 max_hold_s=600 bucket=C_WEAK_EV
```

## Gate Before P1.2
Do not start replay training until:
```text
10+ closed paper exploration trades
PAPER_STATE_LOAD clean
PAPER_EXIT contains bucket/hold_s/max_hold_s
LEARNING_UPDATE contains bucket
PAPER_BUCKET_UPDATE visible
PAPER_BUCKET_METRICS visible
No Traceback/ERROR
No real orders
```

## Current bucket interpretation
Current C_WEAK_EV result is weak:
```text
C_WEAK_EV n=4 wr=0.0% avg=-0.2340 pf=0.00 timeout_rate=100.0%
```

If this persists after 10+ clean closed trades, do not blindly start replay training. Next step should be bucket strategy tuning:
- shorter/longer hold comparison
- TP/SL adjustment
- direction-quality filter
- demote or cap C_WEAK_EV if PF remains near 0
