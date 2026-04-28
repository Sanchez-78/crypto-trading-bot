# P1.1c — Fix Paper Exploration Sizing + Persist Open Paper Positions

P1.1b production validation succeeded:
- `commit=d0ba223` live
- `[TRADING_MODE] mode=paper_live real_orders=False live_allowed=False exploration=True`
- `[PAPER_EXPLORE_SKIP]` appears
- `[PAPER_EXPLORE_ENTRY]` appears
- `[PAPER_ENTRY]` appears

Do **not** start P1.2 yet.

## Critical findings

1. `C_WEAK_EV` opened with full size:

```text
[PAPER_EXPLORE_ENTRY] bucket=C_WEAK_EV ...
[PAPER_ENTRY] ... size_usd=100.00 reason=PAPER_EXPLORE
```

This likely ignores exploration `size_mult`. C_WEAK_EV should be reduced, e.g. base `100 × 0.08 = 8`.

2. Service restarted after `PAPER_ENTRY`.

If open paper positions are only in memory, restart loses them, causing no:

```text
[PAPER_EXIT]
[LEARNING_UPDATE]
```

## Goal

Fix paper exploration so learning data is correct:

- exploration trades use reduced bucket size
- open paper positions survive restart
- closed paper trades trigger learning
- no real orders
- no live gate changes
- no Firebase tick writes
- no replay training yet

## Task 1 — Fix exploration sizing

For paper exploration entries, actual `size_usd` must apply bucket `size_mult`.

Expected multipliers:

```text
B_RECOVERY_READY   base_size * 0.15
C_WEAK_EV          base_size * 0.08
D_NEG_EV_CONTROL   base_size * 0.03
E_NO_PATTERN       base_size * 0.02
```

Fix:

- Locate where `maybe_open_paper_exploration_from_reject()` calls `open_paper_position()`.
- Ensure final reduced size is passed into the paper executor.
- Do not let `open_paper_position()` overwrite exploration size with default/base size.
- Preserve normal strict TAKE sizing separately.

Required logs:

```text
[PAPER_EXPLORE_ENTRY] bucket=C_WEAK_EV symbol=... side=... original_decision=... ev=... score=... price=... base_size_usd=100.00 size_mult=0.08 final_size_usd=8.00 reject_reason=...
[PAPER_ENTRY] symbol=... side=... price=... size_usd=8.00 ev=... score=... reason=PAPER_EXPLORE
```

Add/adjust tests:

```text
C_WEAK_EV with base size 100 opens size_usd 8
D_NEG_EV_CONTROL with base size 100 opens size_usd 3
E_NO_PATTERN with base size 100 opens size_usd 2
normal strict TAKE keeps normal size logic unchanged
```

## Task 2 — Persist open paper positions across restart

Open paper positions must survive systemd restart.

Implement simple local persistence in `src/services/paper_trade_executor.py`:

```text
data/paper_open_positions.json
```

Rules:

- save on paper open
- save on paper close
- save when position state changes materially
- do not save every tick unless something closes/changes
- load on startup/module init
- if file missing, start empty
- if file corrupt, start empty and log warning
- never affect live trading path

Required logs:

```text
[PAPER_STATE_LOAD] open_positions=N source=data/paper_open_positions.json
[PAPER_STATE_SAVE] open_positions=N source=data/paper_open_positions.json
[PAPER_STATE_LOAD_ERROR] err=...
[PAPER_STATE_SAVE_ERROR] err=...
```

Add tests:

```text
open paper position
save state
clear in-memory positions
load state
position exists
update_paper_positions can close it later
```

## Task 3 — Ensure closed exploration trades feed learning

After an exploration paper position closes, logs must show:

```text
[PAPER_EXIT] symbol=... reason=TP/SL/TIMEOUT net_pnl_pct=... outcome=WIN/LOSS/FLAT
[LEARNING_UPDATE] source=paper_closed_trade symbol=... bucket=...
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
net_pnl_pct
outcome
entry_ts
exit_ts
entry_price
exit_price
```

Firebase writes:

- write closed trades to `trades_paper`
- one write per closed trade
- no tick-level writes

## Task 4 — Improve skip reasons

Current production skip:

```text
[PAPER_EXPLORE_SKIP] reason=no_bucket_matched bucket=UNKNOWN original_decision=REJECT_NEGATIVE_EV
```

Make negative EV skips more specific:

```text
neg_control_hourly_cap
neg_ev_outside_control_profile
invalid_ev
missing_price
no_side
no_bucket_matched only as final fallback
```

Do not loosen negative EV real trading gates. This is paper-only observability/exploration.

## Safety constraints

```text
Do not place real orders.
Do not change live_trading_allowed().
Do not weaken live safety gates.
Do not start P1.2/replay_train.py.
Do not write Firebase on every tick.
Do not synthesize fake prices.
Use real live prices only.
Do not hardcode BUY/SELL where side is unknown.
```

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
git commit -m "P1.1c: apply exploration sizing and persist paper positions"
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

Check logs:

```bash
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_STATE_LOAD|PAPER_STATE_SAVE|PAPER_EXPLORE_ENTRY|PAPER_EXPLORE_SKIP|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|Traceback|ERROR"
```

## Success criteria

Minimum:

```text
[PAPER_STATE_LOAD] open_positions=...
[PAPER_EXPLORE_ENTRY] ... base_size_usd=100.00 size_mult=0.08 final_size_usd=8.00
[PAPER_ENTRY] ... size_usd=8.00 reason=PAPER_EXPLORE
```

Full success:

```text
[PAPER_EXIT] ...
[LEARNING_UPDATE] source=paper_closed_trade bucket=C_WEAK_EV ...
```

Only after this is validated, continue to P1.2 replay training.
