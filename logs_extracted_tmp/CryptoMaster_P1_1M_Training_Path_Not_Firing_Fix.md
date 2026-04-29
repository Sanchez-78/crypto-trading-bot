# CryptoMaster P1.1M — Fix Training Path Not Firing After Accepted Signals

## Evidence from uploaded log
Counts in `logs.1774626511515.log`:
- `decision=TAKE`: many
- `[EXEC]`: many
- `Generated valid signal`: many
- `[UNBLOCK_LIMIT]`: repeated
- `candidate_gate: DUPLICATE_CANDIDATE`: repeated
- `PAPER_TRAIN_ENTRY`: 0
- `PAPER_ENTRY`: 0
- `PAPER_EXIT`: 0
- `LEARNING_UPDATE`: 0
- `RUNTIME_VERSION/TRADING_MODE`: not present in uploaded slice

Interpretation:
The bot generates valid signals and RDE accepts them, but paper training is not opening positions. The accepted-signal path is being blocked/dropped by operational gates such as `UNBLOCK_RATE_LIMIT` and `DUPLICATE_CANDIDATE` before it reaches paper executor/training learning.

## Goal
In `TRADING_MODE=paper_train`, accepted signals and useful blocked signals must become paper-training trades or explicit structured skips. No silent loss.

Required flow:
```text
valid signal / TAKE / blocked TAKE / reject
→ paper_train router
→ PAPER_TRAIN_ENTRY or PAPER_TRAIN_SKIP
→ PAPER_EXIT
→ LEARNING_UPDATE
```

## Hard Rules
- Never place real orders in `paper_train`.
- Do not weaken `live_real` guards.
- Do not remove live operational risk gates.
- Paper training must use real current prices only.
- No Firebase writes on ticks.
- Only closed paper trades update Firebase/learning.

## Task 1 — Add boundary observability
Add one lightweight trace at each major boundary.

Expected logs:
```text
[PAPER_TRAIN_ROUTER] source=TAKE/REJECT/UNBLOCK_LIMIT/DUPLICATE_CANDIDATE symbol=... mode=paper_train price=...
[PAPER_TRAIN_ENTRY] bucket=... symbol=... side=... price=... size_usd=... source=...
[PAPER_TRAIN_SKIP] reason=... symbol=... source=...
```

Do not log every tick without signal; only log when a signal/reject/block is produced.

## Task 2 — Strict TAKE must open paper trade in paper_train
Files:
- `src/services/trade_executor.py`
- `src/services/realtime_decision_engine.py`

Rule:
If RDE returns `decision=TAKE` and mode is `paper_train`, route to `open_paper_position()` with:
```text
paper_source=training_sampler
training_bucket=A_STRICT_TAKE
original_decision=TAKE
size_mult=1.0 or configured paper-train strict size
max_hold_s=config/default
```

This must happen before any live-only order path.

Log:
```text
[PAPER_TRAIN_ENTRY] bucket=A_STRICT_TAKE symbol=... side=... price=... source=TAKE
```

## Task 3 — Convert UNBLOCK_LIMIT into paper training skip or sample
Current log:
```text
[UNBLOCK_LIMIT] ... UNBLOCK_RATE_LIMIT: 6/6 trades in last hour — signal skipped
```

Problem:
This likely blocks accepted signals before paper training.

In `paper_train`:
- Do not use live/unblock trade limit as hard block for learning.
- Use separate paper training caps:
```text
PAPER_TRAIN_MAX_OPEN_TOTAL=3
PAPER_TRAIN_MAX_OPEN_PER_SYMBOL=1
PAPER_TRAIN_MIN_REENTRY_SECONDS=60
PAPER_TRAIN_MAX_ENTRIES_PER_HOUR=12
```

If paper cap blocks:
```text
[PAPER_TRAIN_SKIP] reason=paper_cap_max_open_per_symbol source=UNBLOCK_LIMIT symbol=...
```

If cap allows:
Open training paper trade:
```text
bucket=A_STRICT_TAKE_BLOCKED or C_WEAK_EV_TRAIN
source=UNBLOCK_LIMIT
```

## Task 4 — Convert DUPLICATE_CANDIDATE into structured paper_train decision
Current log:
```text
candidate_gate: DUPLICATE_CANDIDATE(age=0.0s)
```

In `paper_train`:
- If duplicate age < `PAPER_TRAIN_MIN_REENTRY_SECONDS`, log:
```text
[PAPER_TRAIN_SKIP] reason=candidate_cooldown age_s=... symbol=... source=DUPLICATE_CANDIDATE
```
- If age >= cooldown and caps allow, allow one paper training entry.
- Prevent same-tick floods. One symbol cannot produce dozens of duplicate logs per second.

## Task 5 — Re-check reject path wiring
Ensure these produce either `PAPER_TRAIN_ENTRY` or `PAPER_TRAIN_SKIP`:
```text
REJECT_ECON_BAD_ENTRY
REJECT_NEGATIVE_EV
REJECT_ECON_BAD_FORCED
NO_CANDIDATE_PATTERN
UNBLOCK_LIMIT
DUPLICATE_CANDIDATE
TAKE
```

## Task 6 — Exit + learning still required
For every closed training paper trade:
```text
[PAPER_EXIT] symbol=... reason=... outcome=... training_bucket=...
[LEARNING_UPDATE] source=paper_closed_trade symbol=... training_bucket=... outcome=... net_pnl_pct=...
[PAPER_TRAIN_BUCKET_UPDATE] bucket=... n=... wr=... avg=... pf=...
```

If learning fails:
```text
[PAPER_LEARNING_BROKEN] trade_id=... reason=...
```

## Tests
Add/extend tests:
```text
1. paper_train strict TAKE opens A_STRICT_TAKE paper position
2. paper_live strict TAKE behavior unchanged
3. live_real never calls training sampler
4. UNBLOCK_LIMIT in paper_train does not silently discard signal
5. UNBLOCK_LIMIT opens paper trade when paper caps allow
6. UNBLOCK_LIMIT logs PAPER_TRAIN_SKIP when paper caps block
7. DUPLICATE_CANDIDATE logs candidate_cooldown
8. duplicate flood limited per symbol
9. NO_CANDIDATE_PATTERN still reaches side inference
10. closed training trade calls learning update
11. no tick-level Firebase writes
```

## Validation
Run:
```bash
python -m py_compile \
  src/core/runtime_mode.py \
  src/services/paper_training_sampler.py \
  src/services/paper_trade_executor.py \
  src/services/trade_executor.py \
  src/services/realtime_decision_engine.py \
  src/services/learning_monitor.py

python -m pytest tests/test_paper_mode.py tests/test_p1_paper_exploration.py tests/test_p0_3_paper_integration.py -v
git diff --check
```

Commit:
```bash
git add src tests .env.example
git commit -m "P1.1M: route accepted and blocked signals into paper training"
git push origin main
```

## Production validation
```bash
cd /opt/cryptomaster
git fetch origin main
git reset --hard origin/main
sudo systemctl restart cryptomaster
sleep 60

sudo journalctl -u cryptomaster --since "60 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_TRAIN_ROUTER|PAPER_TRAIN_ENTRY|PAPER_TRAIN_SKIP|PAPER_EXIT|LEARNING_UPDATE|PAPER_TRAIN_BUCKET_UPDATE|PAPER_LEARNING_BROKEN|UNBLOCK_LIMIT|DUPLICATE_CANDIDATE|Traceback|ERROR"
```

Success:
```text
commit=P1.1M latest
mode=paper_train
PAPER_TRAIN_ROUTER > 0
PAPER_TRAIN_ENTRY > 0
PAPER_EXIT > 0 within max_hold_s
LEARNING_UPDATE > 0
PAPER_LEARNING_BROKEN = 0
Traceback/ERROR = 0
```
