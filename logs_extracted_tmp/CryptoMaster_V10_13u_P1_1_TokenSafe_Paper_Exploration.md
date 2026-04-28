# CryptoMaster V10.13u+20 — P1.1 Paper Exploration From Rejects

**Purpose:** robot currently runs `paper_live`, uses real prices, but strict `TAKE` rarely happens. P0.3 is deployed and logging works, but no `[PAPER_ENTRY]` because RDE mostly returns rejects. Implement P1.1 so selected rejected signals can open **paper-only** trades for learning.

## Current production evidence

```text
✅ service stable
✅ [TRADING_MODE] visible
✅ mode=paper_live
✅ real_orders=False
✅ live_allowed=False
❌ exploration=False
❌ no PAPER_ENTRY / PAPER_EXIT / LEARNING_UPDATE
❌ RDE emits mostly REJECT_NEGATIVE_EV, REJECT_ECON_BAD_ENTRY weak_ev, NO_CANDIDATE_PATTERN
```

## Hard rules

```text
Never place real orders.
Never bypass live_trading_allowed().
Use real live prices only.
No synthetic entry/exit prices.
No tick-level Firebase writes.
Write only closed paper trades.
Keep paper/live trades separated.
Do not loosen live gates.
Do not change TP/SL/live execution semantics.
P1.1 only: no replay_train yet.
```

## Env

Update `.env.example` and production docs:

```env
TRADING_MODE=paper_live
ENABLE_REAL_ORDERS=false
LIVE_TRADING_CONFIRMED=false
PAPER_EXPLORATION_ENABLED=true
PAPER_EXPLORATION_PROFILE=balanced
```

After deploy, production must show:

```text
[TRADING_MODE] mode=paper_live real_orders=False live_allowed=False exploration=True
```

## Create/extend `src/services/paper_exploration.py`

Add:

```python
def paper_exploration_override(signal: dict, ctx: dict | None = None) -> dict:
    ...
```

Return shape:

```python
{
    "allowed": bool,
    "bucket": str,
    "reason": str,
    "size_mult": float,
    "max_hold_s": int,
    "tags": list[str],
}
```

Must be exception-safe and never raise.

## Buckets

```text
A_STRICT_TAKE      normal TAKE routed by P0.3
B_RECOVERY_READY   weak_ev but recovery/deadlock probe ready or near-ready
C_WEAK_EV          ev > 0 but below ECON_BAD floor
D_NEG_EV_CONTROL   tiny capped sample of negative EV baseline
E_NO_PATTERN       tiny capped NO_CANDIDATE_PATTERN baseline
F_BLOCKED_CONTROL  disabled by default
```

Default policy:

```text
A_STRICT_TAKE: handled by P0.3, always paper in paper mode
B_RECOVERY_READY: allow if ev >= 0.038 or probe_ready=True
C_WEAK_EV: allow if ev > 0 and not all quality fields are zero
D_NEG_EV_CONTROL: max 1/hour, tiny size, control tag
E_NO_PATTERN: max 1/hour, tiny size, baseline tag
F_BLOCKED_CONTROL: disabled
```

Suggested size/hold:

```text
B_RECOVERY_READY size_mult=0.15 max_hold_s=900
C_WEAK_EV        size_mult=0.08 max_hold_s=600
D_NEG_EV_CONTROL size_mult=0.03 max_hold_s=300
E_NO_PATTERN     size_mult=0.02 max_hold_s=300
```

## Integration

When final decision is reject and runtime is paper mode with exploration enabled:

```python
if is_paper_mode() and paper_exploration_enabled():
    ov = paper_exploration_override(signal, ctx)
    if ov.get("allowed"):
        open_paper_position(
            signal,
            price=current_real_price,
            ts=now,
            reason="PAPER_EXPLORE",
            extra={
                "paper_source": "exploration_reject",
                "explore_bucket": ov["bucket"],
                "original_decision": final_decision,
                "reject_reason": reject_reason,
                "size_mult": ov["size_mult"],
                "max_hold_s": ov["max_hold_s"],
                "tags": ov["tags"],
            },
        )
        log.warning(
            "[PAPER_EXPLORE_ENTRY] bucket=%s symbol=%s original_decision=%s ev=%.4f score=%.3f price=%s reason=%s",
            ov["bucket"], symbol, final_decision, ev, score, current_real_price, ov["reason"]
        )
```

Rules:
```text
This is paper-only.
Do not return live TAKE.
Do not call live executor.
Use actual current price from tick/signal context.
If no real price is available, skip and log [PAPER_EXPLORE_SKIP] reason=no_real_price.
```

## Paper executor additions

Ensure paper trade schema includes:

```text
paper_source
explore_bucket
original_decision
reject_reason
size_mult
max_hold_s
tags
ev, score, p, coh, af, regime
entry_price from real live price
exit_price from real live price
net_pnl_pct after fees/slippage
outcome from net_pnl_pct, not exit reason
```

Expected logs:

```text
[PAPER_EXPLORE_ENTRY] bucket=C_WEAK_EV symbol=... original_decision=REJECT_ECON_BAD_ENTRY ev=... score=... price=...
[PAPER_ENTRY] symbol=... side=... price=... bucket=...
[PAPER_EXIT] bucket=... symbol=... reason=TP/SL/TIMEOUT net_pnl_pct=... outcome=...
[LEARNING_UPDATE] source=paper_closed_trade bucket=... symbol=... outcome=... net_pnl_pct=...
```

## Metrics

Add bucket-level closed paper metrics:

```text
trades
winrate
avg_net_pnl_pct
profit_factor
expectancy
timeout_rate
tp_rate
sl_rate
net_after_fees
best_bucket
worst_bucket
```

Add readiness log:

```text
[PAPER_READINESS] eligible_live=false reason=insufficient_samples
```

Live readiness must remain false until all are true:

```text
min 300 closed paper trades
min 7 days live-price paper data
profit_factor >= 1.20
net_pnl_pct positive after fees
drawdown acceptable
at least 2 profitable regimes
strict/recovery buckets outperform controls
no Firebase quota issue
no live guard bypass
```

## Tests

Create `tests/test_p1_paper_exploration.py`.

Required tests:

```text
exploration disabled -> no paper reject entry
weak positive EV -> C_WEAK_EV allowed
recovery-ready weak EV -> B_RECOVERY_READY allowed
negative EV sampled only under hourly cap
NO_CANDIDATE_PATTERN sampled only under hourly cap
paper exploration never calls live executor
closed exploration trade updates learning
bucket fields saved to paper trade
readiness false with insufficient samples
```

Run:

```bash
python -m py_compile   src/services/paper_exploration.py   src/services/paper_trade_executor.py   src/services/trade_executor.py   src/services/realtime_decision_engine.py

python -m pytest   tests/test_paper_mode.py   tests/test_p0_3_paper_integration.py   tests/test_p1_paper_exploration.py   -v

git diff --check
```

## Commit

```bash
git add src tests .env.example docs || true
git commit -m "P1.1: enable paper exploration from rejected real-price signals"
git push origin main
```

## Production validation

```bash
cd /opt/cryptomaster
git pull origin main
sudo systemctl restart cryptomaster
sleep 60

sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager   | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_EXPLORE_ENTRY|PAPER_EXPLORE_SKIP|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|PAPER_READINESS|LIVE_ORDER_DISABLED|Traceback|ERROR"
```

Expected:

```text
[RUNTIME_VERSION] commit=<P1.1 commit>
[TRADING_MODE] mode=paper_live real_orders=False live_allowed=False exploration=True
[PAPER_EXPLORE_ENTRY] bucket=...
[PAPER_ENTRY] ...
[PAPER_EXIT] ...
[LEARNING_UPDATE] source=paper_closed_trade bucket=...
```

## Stop conditions

Stop and fix before P1.2 if:

```text
Traceback appears
exploration=True missing
real order path called
paper entry uses missing/synthetic price
no PAPER_EXPLORE_ENTRY within 30 minutes
no PAPER_EXIT/LEARNING_UPDATE after reasonable hold window
Firebase writes per tick
paper/live metrics mixed
```

## Do not implement yet

```text
No replay_train.py in this patch.
No live money trading.
No global threshold loosening.
No deletion/reset of existing Firebase history.
```
