# CryptoMaster P1.1L — Active Paper Trading + Learning Feedback Loop

## Goal
Stop patch loop. Robot must actively trade in `paper_train`, learn from closed real-price paper trades, and adjust its own paper-training settings. No real money yet.

Current phase:
- No real capital.
- Use real live market prices only.
- Need enough paper trades → exits → Firebase/learning → parameter updates.
- Preserve future live trading ability, but never bypass live guards.

## Hard Rules
- Never place real orders unless `live_trading_allowed()` passes all confirmations.
- `paper_train` and `paper_live` must never call exchange order APIs.
- No synthetic prices, no fake fills.
- No Firebase writes on ticks.
- Only closed paper trades write to Firebase/learning.
- Do not delete strict TAKE path.
- Do not weaken live_real safety.
- All training trades must be clearly tagged.

## Required Runtime Modes
File: `src/core/runtime_mode.py`

Support:
- `paper_live`: conservative paper mode.
- `paper_train`: active paper learning mode.
- `live_real`: real-money mode, locked by guard.

Startup log must show:
```text
[TRADING_MODE] mode=paper_train real_orders=False live_allowed=False exploration=True training=True
```

## Phase 1 — End-to-End Paper Training Flow
Implement complete flow, not foundation only.

Flow:
```text
live WebSocket price
→ RDE/features/regime
→ strict TAKE OR reject
→ paper_train sampler if no strict TAKE
→ open paper position at real current price
→ TP/SL/max_hold_s exit at real prices
→ closed trade saved to trades_paper
→ learning update
→ adaptive setting update
→ health/readiness report
```

## Phase 2 — Active Training Sampler
File: `src/services/paper_training_sampler.py`

Function:
```python
maybe_open_training_sample(signal, ctx, reason, current_price) -> dict
```

Run only when:
```text
TRADING_MODE=paper_train
PAPER_TRAINING_ENABLED=true
current_price valid
live_real false
```

Training buckets:
```text
A_STRICT_TAKE          existing strict RDE TAKE, size_mult=1.00
B_RECOVERY_READY       recovery/near-take, size_mult=0.15
C_WEAK_EV_TRAIN        positive EV below threshold, size_mult=0.05–0.08, hold=240–300s
D_NEG_EV_CONTROL       negative EV control, size_mult=0.02, hold=180–240s, max 2/hour
E_NO_PATTERN_BASELINE  no candidate pattern with inferred side, size_mult=0.02, hold=180–240s, max 2/hour
```

In `paper_train`, cost-edge failure must not always block. It must tag:
```text
cost_edge_ok=false
expected_move_pct=...
required_move_pct=...
```

In `paper_live`, keep conservative P1.1j behavior.

## Phase 3 — Side Inference for Missing Side
For `NO_CANDIDATE_PATTERN`, infer side from real features.

BUY votes:
```text
ema_diff > 0
macd > 0
mom5 > 0
mom10 > 0
obi > 0
rsi < 35
regime == BULL_TREND
```

SELL votes:
```text
ema_diff < 0
macd < 0
mom5 < 0
mom10 < 0
obi < 0
rsi > 65
regime == BEAR_TREND
```

Rules:
```text
buy_score > sell_score → BUY
sell_score > buy_score → SELL
tie → skip side_inference_tie
```

Log:
```text
[PAPER_TRAIN_SIDE] symbol=... side=BUY buy_score=... sell_score=... reason=feature_vote
```

## Phase 4 — Wire Into Production Reject Paths
Files:
- `src/services/trade_executor.py`
- `src/services/realtime_decision_engine.py`

Order:
```text
1. strict TAKE → paper executor in paper modes
2. reject → existing paper_exploration_override()
3. if skipped and paper_train enabled → maybe_open_training_sample()
```

Wire:
```text
REJECT_ECON_BAD_ENTRY
REJECT_NEGATIVE_EV
NO_CANDIDATE_PATTERN
weak EV / weak score
missing side with valid price
```

Logs:
```text
[PAPER_TRAIN_ENTRY] bucket=... symbol=... side=... price=... size_usd=... source_reject=...
[PAPER_TRAIN_SKIP] reason=... symbol=... source_reject=...
```

## Phase 5 — Paper Executor Metadata
File: `src/services/paper_trade_executor.py`

Persist in open and closed trade:
```text
paper_source=training_sampler
training_bucket=...
explore_bucket=...
original_decision=...
reject_reason=...
side_inferred=true/false
cost_edge_ok=true/false
expected_move_pct=...
required_move_pct=...
size_mult=...
max_hold_s=...
features snapshot
regime
entry_price
exit_price
net_pnl_pct
outcome
exit_reason
hold_s
```

Exit log:
```text
[PAPER_EXIT] symbol=... reason=TP/SL/TIMEOUT net_pnl_pct=... outcome=... hold_s=... max_hold_s=... bucket=... training_bucket=...
```

## Phase 6 — Learning Must Update Settings
Learning is not only logging. Closed trades must update model/config state.

Add/extend:
- `src/services/learning_monitor.py`
- `src/services/bucket_metrics.py`
- `src/services/adaptive_training_policy.py` new if useful.

On every closed paper trade:
```text
1. save to Firebase trades_paper
2. update canonical metrics
3. update per-symbol/regime/bucket stats
4. update EV calibration
5. update adaptive paper policy
6. persist policy/model_state
```

Log:
```text
[LEARNING_UPDATE] source=paper_closed_trade symbol=... regime=... bucket=... outcome=... net_pnl_pct=...
[PAPER_POLICY_UPDATE] bucket=... old_size=... new_size=... old_hold=... new_hold=... reason=...
```

## Phase 7 — Adaptive Paper Policy
Robot may adjust only paper-training parameters until promotion readiness.

Adjust per bucket/symbol/regime:
```text
size_mult
max_hold_s
tp_mult
sl_mult
entry frequency cap
allow/disable bucket
minimum direction_quality
```

Rules:
```text
n < 20 → collect data, only small adjustments
n >= 20 and PF < 0.70 and avg_pnl < 0 → reduce size/frequency or disable bucket
n >= 20 and timeout_rate > 80% → reduce max_hold_s or tighten TP/SL
n >= 30 and PF > 1.10 and avg_pnl > 0 → allow slightly higher frequency/size within paper caps
```

Never adjust:
```text
live_real guard
real order flags
API keys
exchange live execution path
```

Persist:
```text
model_state/paper_policy
local data/paper_policy.json fallback
```

## Phase 8 — Training Throughput Health
Every 10 minutes:
```text
[PAPER_TRAIN_HEALTH] open=... entries_1h=... closed_1h=... target_entries_1h=6 learning_updates_1h=... status=OK/STARVED
```

If STARVED:
```text
[PAPER_TRAIN_STARVED] top_skips=... open=... caps=...
```

If closed trades exist but learning not called:
```text
[PAPER_LEARNING_BROKEN] closed=... learning_updates=0
```

## Phase 9 — Readiness for Real Money
Do not enable live trading automatically.

Log:
```text
[PAPER_PROMOTION_STATUS] ready=false closed=... days=... pf=... wr=... max_dd=... reason=...
```

Minimum:
```text
300+ closed paper trades
7+ live-market days
PF > 1.15 overall
PF > 1.05 on 3+ symbols
max drawdown within limit
stable learning updates
no live guard bypass
profit not dominated by D/E/F control buckets
```

## Phase 10 — Tests
Add tests:
```text
1. paper_train never allows real orders
2. strict TAKE still works
3. REJECT_ECON_BAD_ENTRY opens C_WEAK_EV_TRAIN
4. REJECT_NEGATIVE_EV opens D_NEG_EV_CONTROL within cap
5. NO_CANDIDATE_PATTERN infers BUY
6. NO_CANDIDATE_PATTERN infers SELL
7. tie skips
8. training trade uses real current_price
9. metadata persisted open+closed
10. max_hold_s exit works
11. closed trade writes trades_paper
12. closed trade calls learning update
13. adaptive policy updates after enough samples
14. STARVED health emitted when no entries
15. paper_live remains conservative
16. live_real blocks sampler
17. no Firebase writes on tick
```

## Validation
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
git commit -m "P1.1L: enable active paper trading and adaptive learning"
git push origin main
```

## Production Validation
```bash
cd /opt/cryptomaster
git pull origin main
sudo systemctl restart cryptomaster
sleep 60

sudo journalctl -u cryptomaster --since "60 minutes ago" --no-pager \
  | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_TRAIN_ENTRY|PAPER_TRAIN_SKIP|PAPER_TRAIN_SIDE|PAPER_EXIT|LEARNING_UPDATE|PAPER_POLICY_UPDATE|PAPER_TRAIN_HEALTH|PAPER_TRAIN_STARVED|PAPER_PROMOTION_STATUS|PAPER_LEARNING_BROKEN|Traceback|ERROR"
```

Success within 30–60 min:
```text
[PAPER_TRAIN_ENTRY]
[PAPER_EXIT]
[LEARNING_UPDATE]
[PAPER_POLICY_UPDATE] after enough samples
[PAPER_TRAIN_HEALTH] status=OK or clear STARVED reason
no Traceback/ERROR
no real orders
```
