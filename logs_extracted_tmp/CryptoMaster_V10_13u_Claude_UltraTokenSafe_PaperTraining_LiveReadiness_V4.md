# CryptoMaster V10.13u — Token-Safe Full Prompt: Real-Data Paper Training + Future Live Capability

Use this as the single Claude Code/Codex implementation prompt. Keep all existing safety hardening. Stop diagnostic-only patching unless needed to prove this flow works.

## 1) Mission

We do **not** use real money now. The bot must actively learn from:

```text
real market prices + real timestamps + Firebase history + closed paper/replay trades
```

Target architecture:

```text
real prices → signals/features → RDE → paper/replay executor → exits → closed trades → canonical metrics/Firebase → learning update → promotion report
```

Core problem: current strict V10.13u gates prevent trades, so the bot cannot learn. In paper/replay mode, use controlled exploration. Preserve future real-money trading ability, but disabled by default.

## 2) Non-negotiable rules

```text
NO real orders by default.
NO real money by default.
NO Binance live order endpoint unless live_trading_allowed() is true.
ALL current trades = paper_live or replay_train.
ALL entries/exits use real live or real historical prices.
NO synthetic/fake prices for learning.
NO TIMEOUT=WIN bug.
NO Firebase tick spam.
NO exploration in live_real.
```

Default `.env`:

```env
TRADING_MODE=paper_live
ENABLE_REAL_ORDERS=false
LIVE_TRADING_CONFIRMED=false
PAPER_EXPLORATION_ENABLED=true
PAPER_EXPLORATION_PROFILE=balanced
```

Startup must log:

```text
[TRADING_MODE] mode=paper_live real_orders=false live_allowed=false exploration=true profile=balanced
[RUNTIME_VERSION] commit=...
```

## 3) Relevant files must be updated

Implement in actual runtime files, not dead modules only. Inspect repo first. Likely files:

```text
.env.example
start.py
bot2/main.py
src/core/runtime_mode.py
src/services/realtime_decision_engine.py
src/services/trade_executor.py
src/services/paper_trade_executor.py
src/services/paper_exploration.py
src/services/firebase_client.py
src/services/canonical_metrics.py
src/services/learning_monitor.py
src/services/learning_event.py
src/tools/replay_train.py
src/tools/promotion_report.py
tests/test_paper_mode.py
tests/test_paper_exploration.py
tests/test_replay_train.py
tests/test_live_order_guard.py
tests/test_promotion_report.py
tests/test_v10_13u_patches.py
README.md or docs/PAPER_TRAINING.md
```

Production path appears to be:

```text
systemd → start.py → bot2/main.py → event loop
```

Do not rely on unused `v5_main.py` only.

## 4) Runtime modes + live capability

Create/verify `src/core/runtime_mode.py`.

```python
class TradingMode(str, Enum):
    PAPER_LIVE = "paper_live"
    REPLAY_TRAIN = "replay_train"
    LIVE_REAL = "live_real"
```

Helpers:

```python
get_trading_mode()
real_orders_enabled()
paper_exploration_enabled()
is_paper_mode()
live_trading_allowed()
```

`live_trading_allowed()` must require all:

```text
TRADING_MODE=live_real
ENABLE_REAL_ORDERS=true
LIVE_TRADING_CONFIRMED=true
PAPER_EXPLORATION_ENABLED=false
```

Before any live exchange order:

```python
if not live_trading_allowed():
    log.error("[LIVE_ORDER_DISABLED] symbol=%s side=%s mode=%s", symbol, side, get_trading_mode())
    return {"status": "blocked", "reason": "LIVE_ORDER_DISABLED"}
```

Mode behavior:

```text
paper_live: real live prices, simulated orders, exploration allowed, writes closed paper trades.
replay_train: real historical prices, simulated orders, broad exploration, deterministic, Firebase writes off by default.
live_real: real prices/orders, strict gates only, no exploration, manual promotion only.
```

## 5) Paper executor

Create `src/services/paper_trade_executor.py`.

API:

```python
open_paper_position(signal, price, ts, reason) -> dict
update_paper_positions(symbol_prices, ts) -> list[dict]
close_paper_position(position_id, price, ts, reason) -> dict
get_paper_open_positions() -> list[dict]
```

Trade schema must include:

```text
trade_id, mode, symbol, side, entry_price, exit_price, entry_ts, exit_ts,
size_usd, gross_pnl_pct, fee_pct, slippage_pct, net_pnl_pct, exit_reason,
ev_at_entry, score_at_entry, p_at_entry, coh_at_entry, af_at_entry,
regime, features, rde_decision, paper_explore, explore_bucket,
original_reject_reason, unit_pnl, weighted_pnl, created_at
```

Rules:
- entry/exit price from real live feed or real historical replay candle/tick
- PnL includes fees/slippage
- outcome from `net_pnl_pct`, not exit reason
- closed paper trades compatible with canonical metrics

Logs:

```text
[PAPER_ENTRY] symbol=... side=... price=... bucket=... ev=... score=...
[PAPER_EXIT] symbol=... reason=... entry=... exit=... net_pnl_pct=...
[LEARNING_UPDATE] source=paper_closed_trade symbol=... bucket=... net_pnl_pct=...
```

## 6) Route production TAKE to paper

In actual production loop (`start.py → bot2/main.py`):

```text
RDE TAKE + paper_live → open_paper_position()
price loop → update_paper_positions()
paper close → Firebase/canonical metrics/learning update
```

Do not call real executor in paper/replay mode. Preserve real executor for future `live_real`, behind `live_trading_allowed()`.

## 7) Paper exploration

Create `src/services/paper_exploration.py`.

```python
paper_exploration_override(signal, ctx, reject_reason) -> {
  allowed, reason, size_mult, bucket, tags
}
```

Applies only if:

```text
mode in paper_live/replay_train
ENABLE_REAL_ORDERS=false
PAPER_EXPLORATION_ENABLED=true
real price exists
TP/SL/timeout can close
paper open-position cap not exceeded
signal/features valid
```

May override paper-only rejects such as:

```text
REJECT_ECON_BAD_ENTRY, REJECT_NEGATIVE_EV, weak_ev, weak_score,
below_probe_ev, LOSS_CLUSTER, FAST_FAIL
```

Do not override true invalid data:

```text
missing real price, invalid TP/SL, NaN features, no close mechanism,
untradeable spread/slippage, duplicate cap reached
```

Profiles:

```text
conservative: allow_ev_min=0.020, negative_ev=false, exploration_rate=0.10
balanced: allow_ev_min=-0.010, negative_ev=true, exploration_rate=0.25
aggressive_training: allow_ev_min=-0.030, negative_ev=true, exploration_rate=0.50, replay default only
```

Buckets and size multipliers:

```text
A_STRICT_TAKE: 1.00
B_NEAR_MISS: 0.30
C_WEAK_EV: 0.15
D_NEGATIVE_EV_SMALL: 0.05
E_RANDOM_BASELINE: 0.03
F_COUNTERFACTUAL: 0.03
```

Every exploration trade must tag:

```json
{"paper_explore":true,"would_live_block":true,"original_reject_reason":"...","explore_policy":"balanced","explore_bucket":"C_WEAK_EV"}
```

Logs:

```text
[PAPER_EXPLORE_ALLOWED] symbol=... bucket=... ev=... original_reject=...
[PAPER_EXPLORE_BLOCKED] symbol=... reason=...
```

## 8) Replay trainer

Create `src/tools/replay_train.py`.

CLI:

```bash
python -m src.tools.replay_train --symbols XRPUSDT,ADAUSDT,SOLUSDT,BNBUSDT,ETHUSDT --start 2026-04-01 --end 2026-04-27 --timeframe 1m --profile balanced --max-trades 3000
```

Requirements:
- real historical OHLCV/trade data only
- cache under `data/market_cache/`
- deterministic for same input
- same pipeline as live paper:
```text
historical price → features → signal → RDE → paper/explore → exits → learning
```
- Firebase writes off by default; optional summary/trade-limit flags only

Logs:

```text
[REPLAY_SUMMARY] trades=... pf=... wr=... ev=... net=... max_dd=...
[REPLAY_BY_BUCKET] bucket=... trades=... pf=... ev=...
[REPLAY_BY_SYMBOL] symbol=... trades=... pf=... ev=...
[REPLAY_REJECTS] reason=... count=...
```

## 9) Firebase/canonical learning

Collections:

```text
trades_paper
trades_paper_compressed
model_state
metrics
```

Rules:
- write closed paper trades only
- batch writes
- keep quota safe: reads <= 50k/day, writes <= 20k/day
- replay writes summaries only unless explicitly enabled
- canonical PF/WR/EV must include closed paper/replay trades for training metrics, but separate them from future real-live metrics

Learning should update from:

```text
Firebase history + replay closed trades + paper_live closed trades
```

## 10) Required metrics

Do not use winrate alone.

Core profitability:

```text
closed_trades, win_rate_net, profit_factor_net, expectancy_net_pct,
median_net_pnl_pct, avg_win_pct, avg_loss_pct, reward_risk_realized,
total_net_pnl_pct, max_drawdown_pct, recovery_factor,
sharpe_like, sortino_like
```

Robustness:

```text
out_of_sample_pf, walk_forward_pf_min, bootstrap_pf_lower_5pct,
bootstrap_ev_lower_5pct, rolling_100_trade_pf, rolling_100_trade_ev,
rolling_100_trade_dd, symbol_regime_pf_matrix
```

Execution realism:

```text
fee_model_pct, slippage_model_pct, spread_avg_pct, spread_p95_pct,
cost_stress_pf_1x, cost_stress_pf_2x, cost_stress_pf_3x,
timeout_rate, avg_duration_s, p95_duration_s,
max_adverse_excursion_avg, max_favorable_excursion_avg
```

Learning quality:

```text
calibration_brier_score, calibration_bucket_error,
ev_prediction_correlation, ev_realized_gap, sample_count_confidence,
feature_drift_score, regime_drift_score, paper_vs_replay_gap
```

Ops/safety:

```text
live_order_guard_passed, real_orders_blocked_count,
firebase_read_count_est, firebase_write_count_est,
missing_price_count, nan_feature_count, duplicate_close_count,
exit_integrity_errors, traceback_count
```

Report by bucket:

```text
A_STRICT_TAKE, B_NEAR_MISS, C_WEAK_EV, D_NEGATIVE_EV_SMALL, E_RANDOM_BASELINE, F_COUNTERFACTUAL
```

Only `A_STRICT_TAKE` and vetted `B_NEAR_MISS` can count for future live readiness. Never count random/negative/counterfactual as live-ready evidence.

Symbol/regime matrix:

```text
symbol, regime, n, pf, ev, wr, avg_win, avg_loss, timeout_rate, max_dd, ready_for_live
```

Pair is live-ready only if:

```text
n>=100, pf_net>=1.30, expectancy_net_pct>0,
bootstrap_ev_lower_5pct>0, timeout_rate<=25%, no severe drift
```

## 11) Readiness levels

Implement status:

```text
NOT_READY → DATA_READY → PAPER_PROFITABLE → SHADOW_READY → MICRO_LIVE_READY → SCALE_READY
```

NOT_READY if any:

```text
paper closed <500 OR pf_net<1.15 OR expectancy<=0 OR bootstrap_ev_lower_5pct<=0
OR Traceback in last 24h OR exit_integrity_errors>0 OR live guard not tested
```

DATA_READY:

```text
paper/replay closed >=500, >=5 symbols tested, real prices/timestamps,
paper exits work, learning updates work, Firebase quota safe
```

PAPER_PROFITABLE:

```text
paper_live closed >=500, replay_train closed >=3000,
A_STRICT_TAKE pf_net>=1.30, overall paper PF>=1.20,
expectancy>0, bootstrap_ev_lower_5pct>0, rolling_100_ev>0,
max_drawdown<=15%, cost_stress_pf_2x>=1.05
```

SHADOW_READY:

```text
PAPER_PROFITABLE, 7-14 days stable paper_live,
no Traceback 72h, no Firebase breach, no missing-price spike,
spread/slippage model active, live-ready whitelist generated
```

MICRO_LIVE_READY:

```text
SHADOW_READY, paper_live closed>=1000, replay_train closed>=5000,
A_STRICT_TAKE pf>=1.50, out_of_sample_pf>=1.25,
walk_forward_pf_min>=1.10, bootstrap_pf_lower_5pct>=1.05,
cost_stress_pf_2x>=1.10, max_drawdown<=10%, timeout_rate<=20%,
>=3 live-ready symbol/regime pairs, no live guard failure
```

Micro-live restrictions:

```text
very small max_position_usd, very small max_daily_loss_usd,
max_open_positions=1, daily kill switch, manual confirmation
```

SCALE_READY:

```text
micro-live trades>=100, micro-live pf>=1.20, micro-live expectancy>0,
micro-live drawdown within cap, paper/live divergence acceptable,
no execution integrity issue
```

Never jump from paper directly to scaled live.

## 12) Promotion report

Create `src/tools/promotion_report.py`.

CLI:

```bash
python -m src.tools.promotion_report --days 14 --min-trades 500
```

Output:

```text
[PROMOTION_REPORT] status=... recommended_live=false|true recommended_mode=paper_live|shadow|micro_live|scale reason=...
[READINESS_CORE] closed_paper=... closed_replay=... pf_net=... expectancy=... bootstrap_ev_lower_5pct=... out_of_sample_pf=... max_dd=... cost_stress_pf_2x=...
[READINESS_BUCKETS] bucket=... n=... pf=... ev=... live_counted=true|false ready=...
[READINESS_SYMBOL_REGIME] symbol=... regime=... n=... pf=... ev=... timeout=... ready_for_live=true|false
[READINESS_BLOCKERS] blocker=...
```

Never auto-enable live trading. If ready, print only manual steps:

```text
[LIVE_PROMOTION_REQUIRED_MANUAL_CONFIRMATION]
TRADING_MODE=live_real
ENABLE_REAL_ORDERS=true
LIVE_TRADING_CONFIRMED=true
PAPER_EXPLORATION_ENABLED=false
```

## 13) Future live_real behavior

When manually enabled after readiness:

```text
use learned Firebase/model_state
strict RDE gates only
real executor only through live_trading_allowed()
exploration disabled
only A_STRICT_TAKE and approved symbol/regime whitelist
```

Live allowed only if:

```text
EV positive and above live threshold, score above live threshold,
calibrated p acceptable, spread/slippage acceptable, risk budget ok,
no emergency/econ-bad hard block, no forced exploration, no paper-only override
```

Logs:

```text
[LIVE_ENTRY_ALLOWED] symbol=... ev=... score=... reason=strict_trained_policy
[LIVE_ENTRY_BLOCKED] symbol=... reason=... mode=live_real
```

## 14) Dashboard/Android metrics

Expose:

```text
readiness_status, recommended_mode, closed_paper, closed_replay,
paper_pf, replay_pf, strict_bucket_pf, out_of_sample_pf,
expectancy, bootstrap_ev_lower_bound, max_drawdown, timeout_rate,
best_symbol_regime, worst_symbol_regime, live_ready_pairs_count,
current_blockers, last_learning_update_ts, real_order_guard_status
```

User interpretation:

```text
NOT_READY = robot se učí
DATA_READY = dost dat, ziskovost nepotvrzena
PAPER_PROFITABLE = paper edge
SHADOW_READY = může běžet bez peněz vedle trhu
MICRO_LIVE_READY = lze zvážit velmi malý reálný test
SCALE_READY = lze opatrně zvyšovat po úspěšném micro-live
```

## 15) Tests

Add/extend tests:

```text
runtime defaults paper_live
live order blocked when ENABLE_REAL_ORDERS=false
live_real impossible with exploration enabled
paper entry uses real price
paper exit net PnL includes fees/slippage
closed paper trade updates canonical metrics
paper exploration allows weak reject in paper mode
paper exploration never applies in live_real
negative EV paper probe tagged and small size
replay deterministic on fixture candles
replay dry run writes no Firebase trades
Firebase writer batches closed paper trades only
promotion_report readiness blockers correct
existing V10.13u tests still pass
```

Run:

```bash
python -m py_compile src/core/runtime_mode.py src/services/paper_trade_executor.py src/services/paper_exploration.py src/tools/replay_train.py src/tools/promotion_report.py
python -m pytest tests/test_paper_mode.py tests/test_paper_exploration.py tests/test_replay_train.py tests/test_live_order_guard.py tests/test_promotion_report.py tests/test_v10_13u_patches.py -v
git diff --check
```

## 16) Deployment validation

Hetzner:

```bash
cd /opt/cryptomaster
grep -E "TRADING_MODE|ENABLE_REAL_ORDERS|PAPER_EXPLORATION|LIVE_TRADING" .env .env.example || true
sudo systemctl restart cryptomaster
sudo journalctl -u cryptomaster --since "10 minutes ago" --no-pager | grep -E "RUNTIME_VERSION|TRADING_MODE|LIVE_ORDER_DISABLED|PAPER_EXPLORE|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|Traceback"
```

Expected:

```text
[TRADING_MODE] mode=paper_live real_orders=false live_allowed=false exploration=true
[PAPER_EXPLORE_ALLOWED] ...
[PAPER_ENTRY] ...
[PAPER_EXIT] ...
[LEARNING_UPDATE] source=paper_closed_trade ...
```

If no `[PAPER_ENTRY]` within 30 minutes: run replay trainer. Do not add more diagnostics first.

## 17) Done criteria

Complete only when:

```text
✅ all relevant production files updated
✅ no real order can be placed by default
✅ paper_live enters/exits using real live prices
✅ replay_train creates hundreds/thousands of closed trades from real historical prices
✅ closed paper/replay trades feed canonical PF/WR/EV and learning
✅ exploration buckets reveal profitable vs harmful rejected signals
✅ future live_real path preserved but disabled by default
✅ exploration impossible in live_real
✅ promotion_report gives readiness status and blockers
✅ Android/dashboard metrics available
✅ tests pass
```

Implementation summary must include:

```text
[IMPLEMENTATION_FILES_CHANGED] file=... purpose=...
```

## 18) What not to do

```text
Do not add diagnostics-only patch.
Do not loosen real-money gates globally.
Do not remove future live trading ability.
Do not fake prices.
Do not train on synthetic/random prices.
Do not classify TIMEOUT as win.
Do not write every tick to Firebase.
Do not call Binance live order endpoint by default.
Do not hide exploration trades as normal strict trades.
Do not auto-promote to real money.
```

## 19) Implementation order

```text
P0: inspect runtime path + runtime_mode + live-order guard
P0: paper executor + route production TAKE to paper
P0: paper exits + canonical learning update
P1: paper_exploration_override + bucket tags
P1: replay_train with real historical data/cache
P1: Firebase batching/metrics separation
P2: promotion_report + readiness metrics
P2: dashboard/Android exposure
P2: docs/tests/deployment validation
```

Final instruction: implement incrementally, preserve V10.13u safety hardening, verify runtime logs, and prioritize a working real-data paper learning loop over more gate diagnostics.
