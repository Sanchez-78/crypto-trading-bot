# CryptoMaster V10.14-KRONOS — Incremental Patch Prompt

> Role: You are a senior quant/backend engineer. Implement this as an incremental, low-risk patch in the existing `CryptoMaster_srv` project. Do not rewrite the bot. Do not replace the EV/RDE engine. Add Kronos as an optional forecast feature layer with strict safety gates, shadow mode first, and full observability.

## 0) Why this patch exists

Kronos is an open-source foundation model for financial candlesticks/K-lines. It forecasts OHLCV-like sequences using a tokenizer + autoregressive Transformer. The project provides `Kronos`, `KronosTokenizer`, and `KronosPredictor`, with models such as:

- `NeoQuasar/Kronos-mini`
- `NeoQuasar/Kronos-small`
- `NeoQuasar/Kronos-base`

Kronos can forecast future `open/high/low/close/volume/amount` from historical OHLCV windows. It is useful for CryptoMaster only as an auxiliary predictive signal, not as a direct trade executor.

Important constraint: the Kronos repo includes demo finetuning/backtesting scripts, but that does **not** mean it is a production-ready strategy. In CryptoMaster, Kronos must only influence the existing RDE/EV decision layer after validation.

## 1) Existing CryptoMaster assumptions

Project root:

```text
C:\Projects\CryptoMaster_srv
```

Current production architecture:

```text
WebSocket / Binance OHLCV
  -> signal_generator.py
  -> realtime_decision_engine.py
  -> trade_executor.py
  -> on_price exit loop
  -> learning_monitor.py
  -> firebase_client.py / Firestore metrics
```

Do not break:

- current RDE EV gating
- existing TP/SL/trailing/timeout logic
- Firebase write/read budgets
- existing Android metrics data
- production start flow via `start_fresh.py` / `main.py`
- current V10.13x validation tests

## 2) Main design decision

Implement Kronos as:

```text
OHLCV cache
  -> Kronos forecast service
  -> derived forecast features
  -> signal context enrichment
  -> optional RDE score modifier
  -> shadow metrics
```

Do **not** implement:

```text
Kronos forecast -> direct BUY/SELL execution
```

Kronos is an input, not the authority.

## 3) Deployment modes

Add environment variable:

```env
KRONOS_ENABLED=false
KRONOS_MODE=shadow
KRONOS_MODEL=mini
KRONOS_DEVICE=cpu
KRONOS_LOOKBACK=256
KRONOS_PRED_LEN=4
KRONOS_SAMPLE_COUNT=1
KRONOS_MAX_LATENCY_MS=2500
KRONOS_CACHE_TTL_SEC=60
KRONOS_SCORE_MAX_BONUS=0.03
KRONOS_SCORE_MAX_PENALTY=0.04
KRONOS_FIRESTORE_ENABLED=false
KRONOS_LOG_EVERY_N=20
```

Modes:

```text
off       = no imports, no loading, zero runtime effect
shadow    = compute forecast, log/store metrics, no decision effect
advisory  = add features to decision context, no blocking, tiny score effect only if healthy
gated     = may penalize/reject only after validation thresholds pass
```

Default must be safe:

```env
KRONOS_ENABLED=false
KRONOS_MODE=shadow
```

## 4) Dependency strategy

Do not force Kronos dependencies into the main runtime unless enabled.

Preferred:

1. Add optional requirements file:

```text
requirements-kronos.txt
```

Content:

```txt
numpy
pandas==2.2.2
torch>=2.0.0
einops==0.8.1
huggingface_hub==0.33.1
tqdm==4.67.1
safetensors==0.6.2
```

2. Do not import `torch`, `Kronos`, or Hugging Face modules at app startup unless:

```python
KRONOS_ENABLED=true
```

3. If import/model loading fails, bot must continue with:

```text
KRONOS_UNAVAILABLE
```

and Kronos score effect must be exactly zero.

## 5) New files

Create:

```text
src/services/kronos_config.py
src/services/kronos_service.py
src/services/kronos_features.py
src/services/kronos_health.py
tests/test_kronos_features.py
tests/test_kronos_service_fallback.py
docs/V10_14_KRONOS_INCREMENTAL_PATCH.md
```

Optional if project already has config centralization:

```text
src/services/config.py
```

can be extended instead of adding `kronos_config.py`.

## 6) `kronos_config.py`

Implement a tiny config dataclass.

Required fields:

```python
from dataclasses import dataclass
import os

@dataclass(frozen=True)
class KronosConfig:
    enabled: bool
    mode: str
    model_size: str
    device: str
    lookback: int
    pred_len: int
    sample_count: int
    max_latency_ms: int
    cache_ttl_sec: int
    score_max_bonus: float
    score_max_penalty: float
    firestore_enabled: bool
    log_every_n: int

def get_kronos_config() -> KronosConfig:
    ...
```

Validation:

- `mode in {"off","shadow","advisory","gated"}`
- `model_size in {"mini","small","base"}`
- `lookback <= 512` for small/base
- `pred_len >= 1`
- if invalid, log warning and clamp to safe defaults
- never raise during bot startup

Model mapping:

```python
MODEL_MAP = {
    "mini": {
        "tokenizer": "NeoQuasar/Kronos-Tokenizer-2k",
        "model": "NeoQuasar/Kronos-mini",
        "max_context": 2048,
    },
    "small": {
        "tokenizer": "NeoQuasar/Kronos-Tokenizer-base",
        "model": "NeoQuasar/Kronos-small",
        "max_context": 512,
    },
    "base": {
        "tokenizer": "NeoQuasar/Kronos-Tokenizer-base",
        "model": "NeoQuasar/Kronos-base",
        "max_context": 512,
    },
}
```

## 7) `kronos_service.py`

Implement a lazy-loading singleton-style service.

### Public API

```python
@dataclass
class KronosForecast:
    symbol: str
    timeframe: str
    ts: float
    last_close: float
    pred_close: float
    pred_high: float | None
    pred_low: float | None
    pred_return: float
    pred_direction: str  # UP / DOWN / FLAT / UNKNOWN
    pred_volatility: float
    confidence: float
    latency_ms: int
    model: str
    mode: str
    error: str | None = None

class KronosService:
    def forecast(self, symbol: str, timeframe: str, candles: list[dict]) -> KronosForecast:
        ...
```

### Candle format expected

Each candle dict should support:

```python
{
  "timestamp": ...,
  "open": float,
  "high": float,
  "low": float,
  "close": float,
  "volume": float,
  "amount": optional float
}
```

### Required behavior

- If disabled: return forecast with `pred_direction="UNKNOWN"`, `confidence=0`, `error="DISABLED"`.
- If not enough candles: return `error="INSUFFICIENT_CONTEXT"`.
- If missing optional `amount`, fill `amount=0`.
- If loading/inference fails: return `error="KRONOS_UNAVAILABLE"` and do not crash.
- Enforce latency budget. If inference exceeds `KRONOS_MAX_LATENCY_MS`, mark health degraded and use zero effect.
- Cache per `(symbol, timeframe, last_candle_timestamp, lookback, pred_len, model)` for `KRONOS_CACHE_TTL_SEC`.
- Never write raw forecast paths to Firestore every cycle. Keep in memory/log only unless explicitly enabled.

### Lazy load pseudocode

```python
def _ensure_loaded(self):
    if self._loaded:
        return True
    if not self.cfg.enabled or self.cfg.mode == "off":
        return False
    try:
        from model import Kronos, KronosTokenizer, KronosPredictor
        meta = MODEL_MAP[self.cfg.model_size]
        tokenizer = KronosTokenizer.from_pretrained(meta["tokenizer"])
        model = Kronos.from_pretrained(meta["model"])
        self._predictor = KronosPredictor(model, tokenizer, max_context=meta["max_context"])
        self._loaded = True
        return True
    except Exception as exc:
        self._last_error = str(exc)
        self._loaded = False
        return False
```

If the Kronos repo is vendored or installed as a package, adapt the import path. Do not hardcode a fragile relative import.

## 8) `kronos_features.py`

Convert a forecast into stable, bounded features.

Function:

```python
def build_kronos_features(
    forecast: KronosForecast,
    signal_action: str | None,
    atr_pct: float | None,
    spread_pct: float | None,
) -> dict:
    ...
```

Return:

```python
{
  "kronos_available": bool,
  "kronos_error": str | None,
  "kronos_pred_return": float,
  "kronos_pred_direction": "UP|DOWN|FLAT|UNKNOWN",
  "kronos_pred_volatility": float,
  "kronos_confidence": float,
  "kronos_alignment": float,       # -1..1
  "kronos_score_delta": float,     # bounded
  "kronos_reject_reason": str | None,
}
```

### Alignment logic

For BUY/LONG:

```text
UP   -> positive alignment
DOWN -> negative alignment
FLAT -> 0
```

For SELL/SHORT:

```text
DOWN -> positive alignment
UP   -> negative alignment
FLAT -> 0
```

For HOLD/unknown:

```text
alignment = 0
```

### Direction threshold

Avoid noisy tiny moves. Use adaptive threshold:

```python
min_move = max(0.0005, 0.20 * atr_pct if atr_pct else 0.0005)
```

Direction:

```python
if pred_return > min_move: UP
elif pred_return < -min_move: DOWN
else: FLAT
```

### Confidence

Initial confidence must be conservative:

```python
confidence = clamp(abs(pred_return) / max(pred_volatility, 1e-6), 0, 1)
```

Then degrade:

- spread high -> confidence × 0.7
- forecast error -> 0
- stale cache -> 0
- latency exceeded -> 0
- insufficient candles -> 0

### Score delta

Only in advisory/gated mode:

```python
raw_delta = alignment * confidence * abs(pred_return)
```

Bound:

```python
if raw_delta >= 0:
    score_delta = min(raw_delta, KRONOS_SCORE_MAX_BONUS)
else:
    score_delta = max(raw_delta, -KRONOS_SCORE_MAX_PENALTY)
```

In shadow mode:

```python
score_delta = 0
```

## 9) RDE integration

Find canonical decision path in:

```text
src/services/realtime_decision_engine.py
```

Add Kronos features to decision context without changing existing EV truth source.

Patch concept:

```python
decision_ctx["kronos"] = kronos_features
decision_ctx["score_before_kronos"] = score

if cfg.mode in {"advisory", "gated"} and kronos_health_ok:
    score = score + kronos_features["kronos_score_delta"]

decision_ctx["score_after_kronos"] = score
```

Rules:

- `true_ev` remains unchanged.
- `risk_ev` remains unchanged unless explicitly added later after validation.
- Never use Kronos to bypass loss-streak, velocity, emergency, spread, RR, or max exposure guards.
- Kronos may only reduce score or add a small bounded score bonus.
- In `gated` mode, Kronos may reject only when all are true:

```text
historical validation exists
n >= 200 shadow forecasts for symbol/timeframe
directional accuracy above baseline by >= 3 percentage points
calibrated forecast EV positive
alignment <= -0.75
confidence >= 0.65
existing score is near threshold, not strongly positive
```

Reject reason:

```text
KRONOS_CONTRA_CONFIRMED
```

## 10) Signal generator integration

Find where signal context is built in:

```text
src/services/signal_generator.py
```

Add optional call:

```python
kronos_forecast = kronos_service.forecast(symbol, timeframe="15m", candles=ohlcv_cache)
kronos_features = build_kronos_features(
    forecast=kronos_forecast,
    signal_action=signal.action,
    atr_pct=features.get("atr_pct") or features.get("atr"),
    spread_pct=features.get("spread_pct"),
)
signal.context["kronos"] = kronos_features
```

If the system has multi-timeframe features, prefer:

```text
15m for entry timing
1h for directional bias
```

Initial implementation can do only 15m.

## 11) Metrics and logs

Add canonical log line every `KRONOS_LOG_EVERY_N` cycles:

```text
KRONOS[v10.14] BTCUSDT 15m mode=shadow ret=+0.0018 dir=UP conf=0.42 align=+1.00 delta=0.0000 latency=742ms err=None
```

In advisory/gated mode:

```text
RDE[v10.14-kronos] score 0.184 -> 0.197 delta=+0.013 align=+1.00 conf=0.62
```

Add counters:

```python
kronos_total_forecasts
kronos_errors
kronos_latency_ms_avg
kronos_latency_ms_p95
kronos_available_ratio
kronos_direction_up/down/flat
kronos_alignment_avg
kronos_score_delta_avg
kronos_shadow_accuracy_1h
kronos_shadow_ev_1h
```

Keep Firebase budget safe:

- aggregate in memory
- flush summary every 5–15 minutes
- do not write every forecast by default
- if Firestore enabled, collection:

```text
model_state/kronos_summary
```

or existing metrics collection with compact aggregate object.

## 12) Shadow validation

Before enabling advisory mode, implement offline/live shadow evaluation.

For every forecast store in memory:

```python
{
  "symbol": "BTCUSDT",
  "timeframe": "15m",
  "forecast_ts": ...,
  "target_ts": ...,
  "last_close": ...,
  "pred_close": ...,
  "pred_return": ...,
  "actual_close": None,
  "resolved": False,
}
```

When actual future candle arrives, resolve:

```python
actual_return = (actual_close - last_close) / last_close
direction_correct = sign(pred_return) == sign(actual_return)
forecast_error_abs = abs(pred_return - actual_return)
```

Aggregate by:

```text
symbol
timeframe
regime
direction
volatility bucket
```

Promotion rule from shadow -> advisory:

```text
at least 200 resolved forecasts
available_ratio >= 0.90
p95 latency <= KRONOS_MAX_LATENCY_MS
directional accuracy >= naive baseline + 3 percentage points
mean absolute forecast error stable or improving
no increase in simulated rejection of winning trades
```

## 13) Safety gates

Kronos effect must be automatically zeroed when:

```text
cfg.mode == off/shadow
kronos unavailable
latency exceeded
forecast stale
confidence < 0.20
spread too high
emergency mode active
loss cluster active
market data gap detected
```

Kronos must never:

- open trades directly
- increase size directly
- override emergency halt
- override max positions
- override spread guard
- override RR validation
- override SL/TP sanity
- write large raw datasets to Firebase
- block startup if Hugging Face or torch fails

## 14) Tests

Add unit tests.

### `tests/test_kronos_features.py`

Test:

- BUY + UP = positive alignment
- BUY + DOWN = negative alignment
- SELL + DOWN = positive alignment
- SELL + UP = negative alignment
- FLAT = zero alignment
- shadow mode score delta = 0
- score delta bounded by max bonus/penalty
- low confidence = zero/near-zero effect
- error forecast = unavailable

### `tests/test_kronos_service_fallback.py`

Test:

- disabled config does not import torch/model
- insufficient candles returns safe error
- simulated import failure returns `KRONOS_UNAVAILABLE`
- cache key works
- no exception propagates to caller

### Existing validation

Run existing V10.13x tests and ensure unchanged behavior when disabled:

```bash
pytest -q
KRONOS_ENABLED=false pytest -q
```

Expected:

```text
All existing tests pass.
No decision output changes when KRONOS_ENABLED=false.
```

## 15) Implementation order

### Phase A — zero-risk scaffolding

1. Add config.
2. Add `KronosForecast` dataclass.
3. Add service fallback behavior.
4. Add feature conversion.
5. Add tests.
6. Verify bot starts with `KRONOS_ENABLED=false`.

Acceptance:

```text
No runtime import of torch/Kronos when disabled.
Existing logs unchanged except optional config line.
```

### Phase B — shadow mode

1. Wire Kronos forecast into signal context.
2. Add shadow log line.
3. Add in-memory shadow resolver.
4. Add compact aggregate metrics.
5. Do not affect score.

Acceptance:

```text
score_before_kronos == score_after_kronos
No trade decision changed.
KRONOS shadow logs visible.
```

### Phase C — advisory mode

1. Add bounded score delta.
2. Only enable via env.
3. Add canonical RDE score before/after log.
4. Add summary metrics.

Acceptance:

```text
Score delta is bounded.
No hard reject from Kronos.
Emergency/risk guards still dominate.
```

### Phase D — gated mode later only

Do not enable now. Add code path only if validation metrics exist.

Acceptance:

```text
gated mode refuses activation without enough resolved forecasts.
```

## 16) Deployment commands

### Local Windows

```powershell
cd C:\Projects\CryptoMaster_srv

python -m venv .venv
.\.venv\Scripts\activate

pip install -r requirements.txt
pip install -r requirements-kronos.txt

$env:KRONOS_ENABLED="false"
pytest -q

$env:KRONOS_ENABLED="true"
$env:KRONOS_MODE="shadow"
$env:KRONOS_MODEL="mini"
$env:KRONOS_DEVICE="cpu"
python start_fresh.py
```

### Linux server

```bash
cd /opt/cryptomaster
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-kronos.txt

export KRONOS_ENABLED=true
export KRONOS_MODE=shadow
export KRONOS_MODEL=mini
export KRONOS_DEVICE=cpu

python3 start_fresh.py
```

### Systemd environment

Add only after local validation:

```ini
Environment=KRONOS_ENABLED=true
Environment=KRONOS_MODE=shadow
Environment=KRONOS_MODEL=mini
Environment=KRONOS_DEVICE=cpu
Environment=KRONOS_LOOKBACK=256
Environment=KRONOS_PRED_LEN=4
```

Restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart cryptomaster
journalctl -u cryptomaster -f
```

## 17) Production rollout checklist

Do not proceed to advisory unless all pass:

```text
[ ] Existing tests pass with KRONOS_ENABLED=false
[ ] Existing tests pass with KRONOS_ENABLED=true, KRONOS_MODE=shadow
[ ] Bot starts without GPU
[ ] Bot continues if Kronos import fails
[ ] Kronos logs show latency
[ ] p95 latency is acceptable
[ ] No Firestore quota spike
[ ] No decision changed in shadow mode
[ ] At least 200 resolved forecasts per main symbol/timeframe
[ ] Shadow accuracy beats baseline
[ ] Simulated EV impact is positive after fees/slippage
```

## 18) Recommended first configuration

For production live bot:

```env
KRONOS_ENABLED=true
KRONOS_MODE=shadow
KRONOS_MODEL=mini
KRONOS_DEVICE=cpu
KRONOS_LOOKBACK=256
KRONOS_PRED_LEN=4
KRONOS_SAMPLE_COUNT=1
KRONOS_FIRESTORE_ENABLED=false
```

After stable shadow data:

```env
KRONOS_MODE=advisory
KRONOS_SCORE_MAX_BONUS=0.01
KRONOS_SCORE_MAX_PENALTY=0.02
```

Do not use `base` on CPU live until latency is measured.

## 19) Claude Code task

Implement the patch now in small commits:

```text
commit 1: kronos config + dataclasses + safe fallback service
commit 2: feature builder + tests
commit 3: signal/RDE shadow integration
commit 4: metrics/logging + docs
```

For each commit:

1. Show changed files.
2. Explain why the change is safe.
3. Run tests.
4. Confirm disabled mode has zero behavior change.

## 20) Definition of done

Patch is done only when:

```text
KRONOS_ENABLED=false -> exact old behavior
KRONOS_MODE=shadow -> logs/metrics only, no score effect
KRONOS_MODE=advisory -> bounded score effect only
Kronos failures never crash the bot
Firestore budget remains safe
Existing V10.13x validation remains green
```

## 21) Additional senior-review improvements

Add these improvements before enabling anything beyond shadow mode. They are designed to prevent overfitting, hidden latency problems, false confidence, and production instability.

### 21.1 Ablation protocol: prove Kronos adds edge

Do not judge Kronos only by directional accuracy. Add an ablation report comparing the existing bot versus the same bot with Kronos features applied in simulation.

Required comparison groups:

```text
A) baseline CryptoMaster V10.13x decision output
B) baseline + Kronos shadow features, no score effect
C) baseline + Kronos advisory score delta simulated only
D) baseline + inverse Kronos signal sanity check
```

Metrics:

```text
trade_count
winrate
mean_net_pnl
median_net_pnl
profit_factor
max_drawdown
timeout_rate
SL_rate
TP_rate
rejected_winners
accepted_losers
score_near_threshold_impact
net_EV_after_fees
```

Acceptance rule:

```text
Kronos may move from shadow to advisory only if C beats A after fees/slippage and D does not also improve. If inverse Kronos improves too, the signal is probably noise or leakage.
```

### 21.2 Walk-forward validation, not one fixed test window

Add a walk-forward validation script:

```text
scripts/kronos_walkforward_report.py
```

Suggested windows:

```text
train/calibration: 14 days
validation: 7 days
step: 3 days
minimum windows: 6
```

The report must show per-window results, not only aggregate results. Kronos promotion is blocked if performance depends on one lucky window.

Required output:

```text
reports/kronos_walkforward_YYYYMMDD.md
reports/kronos_walkforward_YYYYMMDD.json
```

### 21.3 Strict no-leakage checks

Kronos forecast input must never contain future candles. Add validation:

```python
assert candles[-1]["timestamp"] <= decision_timestamp
assert target_timestamp > candles[-1]["timestamp"]
```

For live data, only closed candles may be used for forecast context unless explicitly named as partial-candle mode.

Default:

```env
KRONOS_USE_PARTIAL_CANDLE=false
```

If partial candles are used later, store this flag in every metric because results are not directly comparable.

### 21.4 Inference scheduler instead of every tick

Do not run Kronos on every WebSocket price update. Run it only when a new closed candle arrives or when cache expires.

Add:

```text
src/services/kronos_scheduler.py
```

Behavior:

```text
per symbol/timeframe only one active inference
skip if previous inference still running
skip if cache valid
skip if CPU load/latency circuit breaker active
return last safe forecast or UNKNOWN
```

This prevents inference from blocking the main trading loop.

### 21.5 Timeout isolation

Wrap inference in a hard timeout. If the project is sync-only, use a thread executor with timeout. If async exists, use `asyncio.wait_for`.

Required behavior:

```text
timeout -> KRONOS_TIMEOUT
score effect = 0
health degraded
bot continues
```

Never let model inference block order execution, exit management, TP/SL updates, or emergency close logic.

### 21.6 Circuit breaker

Add automatic disable logic:

```text
if kronos_errors_last_20 >= 5 -> disable Kronos for 10 minutes
if p95_latency_ms > max_latency_ms for 3 summaries -> disable Kronos for 10 minutes
if available_ratio < 0.70 over last 100 attempts -> disable Kronos for 10 minutes
if process memory exceeds configured limit -> disable Kronos until restart or cooldown
```

New env:

```env
KRONOS_COOLDOWN_SEC=600
KRONOS_MAX_MEMORY_MB=1200
```

Log:

```text
KRONOS_CIRCUIT_BREAKER active reason=LATENCY cooldown=600s effect=0
```

### 21.7 Model warmup and startup safety

Do not load Kronos during critical startup before Binance/Firebase health is known. Load after the bot is already alive.

Startup order:

```text
1. load normal CryptoMaster config
2. verify Firebase optional/available
3. verify market feed
4. start core bot
5. only then lazy-load Kronos if enabled
```

Add a warmup forecast on a tiny cached sample if available. Warmup failure must not fail deployment.

### 21.8 Device policy

CPU is safest for first deployment. GPU/MPS/CUDA must be explicit.

Validation:

```text
KRONOS_DEVICE=cpu|cuda|mps|auto
```

Default:

```env
KRONOS_DEVICE=cpu
```

If `auto`, log the resolved device. If CUDA is unavailable, fall back to CPU only if `KRONOS_ALLOW_DEVICE_FALLBACK=true`; otherwise disable Kronos.

### 21.9 Feature normalization and clipping

Clip all Kronos-derived numeric features before adding them to decision context:

```python
kronos_pred_return = clamp(pred_return, -0.05, 0.05)
kronos_pred_volatility = clamp(pred_volatility, 0.0, 0.10)
kronos_confidence = clamp(confidence, 0.0, 1.0)
kronos_alignment = clamp(alignment, -1.0, 1.0)
kronos_score_delta = clamp(score_delta, -score_max_penalty, score_max_bonus)
```

This prevents bad model output from causing unstable score jumps.

### 21.10 Regime-aware trust, but only after data exists

Do not use one global Kronos quality score. Track quality by:

```text
symbol
timeframe
regime
volatility_bucket
session/liquidity bucket
```

Initial advisory effect should be zero for buckets with insufficient data:

```text
bucket_resolved_n < 50 -> score_delta = 0
```

This is important because Kronos may work in trending markets and fail in quiet/ranging markets.

### 21.11 Cost/slippage-aware target

Forecast correctness is not enough. Add a tradeability threshold:

```python
required_move = 2 * fee_rate + expected_slippage + spread_pct + min_edge_buffer
```

Kronos positive alignment should only get score bonus when:

```text
abs(pred_return) > required_move
```

Suggested default:

```env
KRONOS_MIN_EDGE_BUFFER=0.0005
```

### 21.12 Shadow confusion matrix

Add a compact confusion matrix:

```text
pred_UP_actual_UP
pred_UP_actual_FLAT
pred_UP_actual_DOWN
pred_DOWN_actual_UP
pred_DOWN_actual_FLAT
pred_DOWN_actual_DOWN
pred_FLAT_actual_UP
pred_FLAT_actual_FLAT
pred_FLAT_actual_DOWN
```

This is more useful than a single accuracy number. A model that predicts UP too often can look good in bull periods but fail regime changes.

### 21.13 Near-threshold-only bonus

In advisory mode, Kronos should affect only marginal decisions first.

Rule:

```text
if score is far below threshold -> no Kronos rescue
if score is far above threshold -> no need for Kronos bonus
if score is within threshold band -> allow bounded delta
```

Suggested env:

```env
KRONOS_THRESHOLD_BAND=0.05
```

Implementation concept:

```python
near_threshold = abs(score - score_threshold) <= cfg.threshold_band
if not near_threshold and kronos_score_delta > 0:
    kronos_score_delta = 0
```

Penalty may still apply lightly, but never override emergency/risk gates.

### 21.14 Android/app metrics contract

If Android consumes bot metrics, add Kronos as optional fields only. Do not break current schema.

Recommended compact object:

```json
{
  "kronos": {
    "enabled": true,
    "mode": "shadow",
    "available_ratio": 0.93,
    "p95_latency_ms": 830,
    "last_direction": "UP",
    "last_confidence": 0.42,
    "shadow_accuracy": 0.54,
    "status": "OK"
  }
}
```

UI label in Czech:

```text
Kronos predikce: experimentální modelová vrstva. V režimu shadow neovlivňuje obchody.
```

### 21.15 Rollback plan

Add an explicit rollback checklist to deployment docs:

```bash
# systemd quick rollback
sudo systemctl edit cryptomaster
# set or override:
Environment=KRONOS_ENABLED=false
Environment=KRONOS_MODE=off

sudo systemctl daemon-reload
sudo systemctl restart cryptomaster
journalctl -u cryptomaster -n 100 --no-pager
```

Expected after rollback:

```text
No KRONOS logs except disabled config line.
RDE decisions match pre-Kronos behavior.
No model loaded in memory.
```

### 21.16 Extra tests to add

Add these tests in addition to the original test plan:

```text
[ ] Kronos cannot change score in shadow mode
[ ] Kronos cannot change score when emergency=True
[ ] Kronos cannot rescue a trade below threshold band
[ ] Kronos cannot bypass spread/RR/exposure guards
[ ] Kronos timeout returns UNKNOWN and does not raise
[ ] Kronos circuit breaker disables effect after repeated failures
[ ] Closed-candle-only validation prevents leakage
[ ] Firestore payload remains compact
[ ] Android metrics schema remains backward-compatible
```

### 21.17 Better commit plan

Use smaller commits than the original plan:

```text
commit 1: config/env parsing + safe defaults
commit 2: forecast dataclass + disabled/unavailable service behavior
commit 3: feature builder + clipping + alignment tests
commit 4: scheduler/cache/timeout wrapper
commit 5: shadow resolver + confusion matrix metrics
commit 6: signal context integration in shadow mode
commit 7: RDE logging score_before/after with zero effect in shadow
commit 8: advisory near-threshold bounded delta, behind env only
commit 9: circuit breaker + rollback docs
commit 10: walk-forward/ablation report scripts
```

Each commit must pass:

```bash
KRONOS_ENABLED=false pytest -q
KRONOS_ENABLED=true KRONOS_MODE=shadow pytest -q
```

### 21.18 Final recommendation

For the first live deployment, use this stricter config:

```env
KRONOS_ENABLED=true
KRONOS_MODE=shadow
KRONOS_MODEL=mini
KRONOS_DEVICE=cpu
KRONOS_LOOKBACK=256
KRONOS_PRED_LEN=4
KRONOS_SAMPLE_COUNT=1
KRONOS_MAX_LATENCY_MS=1500
KRONOS_CACHE_TTL_SEC=300
KRONOS_FIRESTORE_ENABLED=false
KRONOS_USE_PARTIAL_CANDLE=false
KRONOS_COOLDOWN_SEC=600
KRONOS_THRESHOLD_BAND=0.05
KRONOS_MIN_EDGE_BUFFER=0.0005
```

Keep this running until there are enough resolved forecasts per symbol/timeframe. Only then consider advisory mode with very small effect:

```env
KRONOS_MODE=advisory
KRONOS_SCORE_MAX_BONUS=0.005
KRONOS_SCORE_MAX_PENALTY=0.010
```

