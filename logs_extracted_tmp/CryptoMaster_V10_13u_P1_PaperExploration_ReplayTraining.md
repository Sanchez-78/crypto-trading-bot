# CryptoMaster V10.13u+21 — P1 Prompt: Paper Exploration + Replay Training

Use this only after P0 live validation confirms:

```text
[TRADING_MODE] mode=paper_live real_orders=false live_allowed=false
[PAPER_ENTRY]
[PAPER_EXIT]
[LEARNING_UPDATE] source=paper_closed_trade
```

If these logs are missing, stop and fix P0 runtime routing first. Do not implement P1 on a broken paper loop.

---

## 1) Mission

Now that paper executor + exits + learning are wired, add controlled training volume:

```text
P1.1 paper_exploration_override()
P1.2 replay_train.py with real historical data
P1.3 metrics/reporting by bucket
```

Goal: bot learns from real-price simulated trades, including weak/near-miss rejected candidates, while real-money capability remains preserved and disabled by default.

---

## 2) Hard safety rules

```text
NO real orders.
NO exploration in live_real.
NO fake prices.
NO synthetic/random price series.
NO Firebase tick writes.
NO live gate loosening.
NO promotion to real money.
NO classification of TIMEOUT as WIN unless net_pnl_pct > 0.
```

Default remains:

```env
TRADING_MODE=paper_live
ENABLE_REAL_ORDERS=false
LIVE_TRADING_CONFIRMED=false
PAPER_EXPLORATION_ENABLED=true
PAPER_EXPLORATION_PROFILE=balanced
```

---

## 3) Files to inspect/update

```text
src/core/runtime_mode.py
src/services/realtime_decision_engine.py
src/services/trade_executor.py
src/services/paper_trade_executor.py
src/services/paper_exploration.py
src/services/canonical_metrics.py
src/services/firebase_client.py
src/services/learning_monitor.py
src/tools/replay_train.py
src/tools/promotion_report.py
tests/test_paper_exploration.py
tests/test_replay_train.py
tests/test_promotion_report.py
tests/test_p0_3_paper_integration.py
.env.example
docs/PAPER_TRAINING.md
```

Production path remains:

```text
systemd → start.py → bot2/main.py → trade_executor.handle_signal/on_price
```

---

## 4) P1.1 — Paper exploration override

Create:

```text
src/services/paper_exploration.py
```

API:

```python
paper_exploration_override(signal: dict, ctx: dict, reject_reason: str) -> dict
```

Return shape:

```python
{
  "allowed": bool,
  "reason": str,
  "bucket": str,
  "size_mult": float,
  "tags": dict
}
```

Applies only if:

```text
is_paper_mode() == True
paper_exploration_enabled() == True
live_trading_allowed() == False
real current price exists
signal fields are valid
paper open cap not exceeded
TP/SL/timeout can close
```

Never applies in `live_real`.

Allowed training buckets:

```text
A_STRICT_TAKE          size_mult=1.00  normal TAKE, no override
B_NEAR_MISS           size_mult=0.30  ev/score close to gate
C_WEAK_EV             size_mult=0.15  positive but below ECON_BAD entry floor
D_NEGATIVE_EV_SMALL   size_mult=0.05  small negative EV only in paper/replay
E_RANDOM_BASELINE     size_mult=0.03  rare control sample, paper/replay only
F_COUNTERFACTUAL      size_mult=0.03  compare rejected/counter direction, replay preferred
```

Profiles:

```text
conservative:
  allow_ev_min=0.020
  negative_ev=false
  exploration_rate=0.10

balanced:
  allow_ev_min=-0.010
  negative_ev=true
  exploration_rate=0.25

aggressive_training:
  allow_ev_min=-0.030
  negative_ev=true
  exploration_rate=0.50
  replay default only, not production default
```

May override paper-only rejects:

```text
REJECT_ECON_BAD_ENTRY
REJECT_NEGATIVE_EV if EV >= profile allow_ev_min
weak_ev
weak_score
below_probe_ev
LOSS_CLUSTER
FAST_FAIL
PAIR_BLOCK
```

Must not override:

```text
missing real price
NaN/None features
invalid TP/SL
SL==TP
no exit mechanism
spread/slippage too high
duplicate/cap block
live_real mode
```

Exploration trade tags:

```json
{
  "paper_explore": true,
  "would_live_block": true,
  "original_reject_reason": "...",
  "explore_policy": "balanced",
  "explore_bucket": "C_WEAK_EV"
}
```

Logs:

```text
[PAPER_EXPLORE_ALLOWED] symbol=... bucket=... ev=... score=... original_reject=...
[PAPER_EXPLORE_BLOCKED] symbol=... reason=...
```

---

## 5) Integrate exploration into production rejection path

In actual rejection path where RDE/trade_executor currently prints:

```text
decision=REJECT_ECON_BAD_ENTRY
decision=REJECT_NEGATIVE_EV
```

Add paper-only branch before final return:

```python
if is_paper_mode() and paper_exploration_enabled():
    ov = paper_exploration_override(signal, ctx, reject_reason)
    if ov["allowed"]:
        signal.update(ov["tags"])
        signal["paper_explore"] = True
        signal["explore_bucket"] = ov["bucket"]
        signal["original_reject_reason"] = reject_reason
        signal["_paper_size_mult"] = ov["size_mult"]
        open_paper_position(signal, price=current_real_price, ts=now, reason="PAPER_EXPLORE")
        return None
```

Do not change live-real reject behavior.

Acceptance log:

```text
[PAPER_EXPLORE_ALLOWED] ...
[PAPER_ENTRY] ... bucket=C_WEAK_EV reason=PAPER_EXPLORE
```

---

## 6) P1.2 — Replay training

Create:

```text
src/tools/replay_train.py
```

CLI:

```bash
python -m src.tools.replay_train --symbols XRPUSDT,ADAUSDT,SOLUSDT,BNBUSDT,ETHUSDT --start 2026-04-01 --end 2026-04-27 --timeframe 1m --profile balanced --max-trades 3000 --dry-run
```

Requirements:

```text
Use real historical OHLCV/trade prices only.
Cache under data/market_cache/.
Deterministic for same inputs.
Use same feature/RDE/paper/exploration/exit logic as paper_live when possible.
Firebase writes off by default.
Optional --write-summary and --write-trades with caps.
```

Replay pipeline:

```text
load historical candles
for each candle/tick:
  update features
  evaluate signal/RDE
  strict TAKE → paper position
  reject + paper_exploration_override allowed → paper position
  update exits on next real historical prices
closed trades → canonical metrics + local replay report
```

Replay logs:

```text
[REPLAY_START] symbols=... start=... end=... profile=...
[REPLAY_SUMMARY] trades=... pf=... wr=... ev=... net=... max_dd=...
[REPLAY_BY_BUCKET] bucket=... trades=... pf=... ev=...
[REPLAY_BY_SYMBOL] symbol=... trades=... pf=... ev=...
[REPLAY_REJECTS] reason=... count=...
```

---

## 7) P1.3 — Metrics by bucket

Extend canonical metrics/reporting with:

```text
bucket
paper_explore
would_live_block
original_reject_reason
explore_policy
```

Report:

```text
A_STRICT_TAKE: n, PF, WR, EV, avg_win, avg_loss, timeout_rate
B_NEAR_MISS: same
C_WEAK_EV: same
D_NEGATIVE_EV_SMALL: same
E_RANDOM_BASELINE: same
F_COUNTERFACTUAL: same
```

Important live-readiness rule:

```text
Only A_STRICT_TAKE and later-approved B_NEAR_MISS can count toward future live readiness.
C/D/E/F are for learning and calibration only.
```

---

## 8) Firebase/quota

Collections:

```text
trades_paper
trades_paper_compressed
replay_summaries
model_state
metrics
```

Rules:

```text
paper_live: write closed paper trades, batched
replay_train dry-run: no Firebase writes
replay_train --write-summary: write one summary doc
replay_train --write-trades: capped, compressed, explicit only
no tick writes
```

---

## 9) Tests

Add/extend:

```text
tests/test_paper_exploration.py
tests/test_replay_train.py
tests/test_promotion_report.py
```

Required tests:

```text
paper exploration disabled in live_real
paper exploration allowed in paper_live
weak EV positive maps to C_WEAK_EV
near miss maps to B_NEAR_MISS
small negative EV maps to D_NEGATIVE_EV_SMALL only if profile allows
missing real price blocks exploration
invalid TP/SL blocks exploration
exploration tags original reject reason
paper explored trade opens via paper executor
replay uses real historical fixture prices
replay deterministic for same fixture
replay dry-run performs no Firebase trade writes
bucket metrics include all buckets
live readiness ignores C/D/E/F buckets
```

Run:

```bash
python -m py_compile src/services/paper_exploration.py src/tools/replay_train.py
python -m pytest tests/test_paper_exploration.py tests/test_replay_train.py tests/test_promotion_report.py tests/test_p0_3_paper_integration.py -v
git diff --check
```

---

## 10) Deployment validation

After deploy:

```bash
sudo systemctl restart cryptomaster
sudo journalctl -u cryptomaster --since "30 minutes ago" --no-pager   | grep -E "RUNTIME_VERSION|TRADING_MODE|PAPER_EXPLORE|PAPER_ENTRY|PAPER_EXIT|LEARNING_UPDATE|LIVE_ORDER_DISABLED|Traceback"
```

Expected:

```text
[TRADING_MODE] mode=paper_live real_orders=false live_allowed=false exploration=true
[PAPER_EXPLORE_ALLOWED] symbol=... bucket=...
[PAPER_ENTRY] symbol=... reason=PAPER_EXPLORE ...
[PAPER_EXIT] ...
[LEARNING_UPDATE] source=paper_closed_trade ...
```

Replay validation:

```bash
python -m src.tools.replay_train --symbols XRPUSDT,ADAUSDT,SOLUSDT --start 2026-04-01 --end 2026-04-27 --timeframe 1m --profile balanced --max-trades 500 --dry-run
```

Expected:

```text
[REPLAY_SUMMARY] trades>0 ...
[REPLAY_BY_BUCKET] bucket=A_STRICT_TAKE ...
[REPLAY_BY_BUCKET] bucket=C_WEAK_EV ...
```

---

## 11) Done criteria

P1 complete only when:

```text
✅ paper_live can open normal strict TAKE trades
✅ paper_live can open exploration trades from selected rejects
✅ every exploration trade is tagged by bucket/original reject
✅ all paper entries/exits use real prices
✅ replay_train creates closed trades from real historical prices
✅ replay dry-run writes no Firebase trades
✅ bucket metrics show profitable vs harmful reject classes
✅ live_real remains strict and exploration-disabled
✅ tests pass
```

---

## 12) What not to do

```text
Do not patch diagnostics only.
Do not loosen real-money gates.
Do not make exploration available in live_real.
Do not fake price data.
Do not write replay tick data to Firebase.
Do not classify paper exploration as live-ready evidence.
Do not proceed to promotion gates until replay + paper bucket metrics exist.
```

Final instruction: implement incrementally. First make paper exploration produce real closed paper trades, then add replay. Prioritize learning throughput on real prices over more ECON_BAD tracing.
