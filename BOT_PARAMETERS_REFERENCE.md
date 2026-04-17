# CryptoMaster HF-Quant 5.0 — Parameters Reference

**Version:** V10.13m+  
**Last Updated:** 2026-04-17  
**Status:** Active Production

---

## TABLE OF CONTENTS

1. [Market Data Parameters](#market-data)
2. [Risk Management Parameters](#risk-management)
3. [Entry Gate Parameters](#entry-gates)
4. [Exit Hierarchy Parameters](#exit-hierarchy)
5. [Learning & Calibration Parameters](#learning--calibration)
6. [Health & Safety Parameters](#health--safety)
7. [Environment Toggles](#environment-toggles)
8. [Default Configuration](#default-configuration)

---

## MARKET DATA

### Symbols
**Parameter:** `SYMBOLS`  
**Location:** `config.py`  
**Value:** `["BTCUSDT", "ETHUSDT", "ADAUSDT", "BNBUSDT", "DOTUSDT", "SOLUSDT", "XRPUSDT"]`  
**Description:** List of trading pairs to monitor on Binance  
**Impact:** Portfolio diversification and liquidity

### Candle Interval
**Parameter:** `INTERVAL`  
**Location:** `config.py`  
**Value:** `"1m"` (1-minute)  
**Description:** Candle size for all technical indicators and OHLCV data  
**Impact:** Dictates decision frequency (~100ms reaction time per tick)

### Candle History Limit
**Parameter:** `CANDLE_LIMIT`  
**Location:** `config.py`  
**Value:** `100`  
**Description:** Number of historical candles retained in memory per symbol  
**Impact:** Feature extraction window size (100 min = 1.67 hours of history)

---

## RISK MANAGEMENT

### Maximum Open Positions
**Parameter:** `MAX_OPEN_POSITIONS` (implicit in risk_engine)  
**Value:** `7` (one per symbol)  
**Description:** Hard limit on concurrent trades  
**Rationale:** Concentration risk control; prevents over-exposure  
**Override:** Risk engine fails-closed if exceeded

### Position Size — Base Allocation
**Parameter:** `MAX_POSITION_SIZE`  
**Location:** `src/core/self_heal.py`  
**Value:** `0.05` (5% of account)  
**Description:** Maximum % of capital in single trade (before multipliers)  
**Calculation:** `size = (risk_budget / stop_loss_distance) * risk_multiplier`

### Position Size — Minimum Floor
**Parameter:** `min_position_floor`  
**Location:** `src/core/self_heal.py`  
**Value:** `0.01` (1% of account in safe/micro mode)  
**Description:** Prevents complete freeze at zero position size  
**Usage:** Applied in micro-trading recovery mode

### Maximum Loss Streak
**Parameter:** `MAX_LOSS_STREAK`  
**Location:** `config.py`  
**Value:** `3` (consecutive losing trades)  
**Description:** Circuit breaker threshold — halt trading if exceeded  
**Mechanism:** Managed by learning system + failsafe_halt()

### Drawdown Halt Threshold
**Parameter:** `drawdown_halt` (implicit)  
**Value:** `0.45` (45% peak-to-trough)  
**Description:** Emergency halt if portfolio loses >45%  
**Mechanism:** `failsafe_halt()` in self_heal.py  
**Recovery:** Manual restart required; no auto-recovery

### Risk Multiplier
**Parameter:** `risk_multiplier`  
**Location:** `src/core/self_heal.py`, `state` object  
**Value:** `1.0` (normal) → `0.5` (EQUITY_DROP) → `0.3` (HIGH_DRAWDOWN)  
**Description:** Position size scalar applied during anomalies  
**Dynamic:** Adjusts in response to system health

---

## ENTRY GATES

### Expected Value (EV) Threshold
**Parameter:** `EV_THRESHOLD` (adaptive)  
**Location:** `src/services/realtime_decision_engine.py`  
**Base Value:** `0.15` (cold start, until 100 samples collected)  
**Adaptive:** `75th percentile of last 50 EV values`  
**Floor:** `0.10` (absolute minimum)  
**Description:** Only trade if EV ≥ threshold  
**Formula:** `EV = (win_prob × RR) - (1 - win_prob)` where `RR = 1.25`

### Confidence Score Threshold
**Parameter:** `score_threshold` (adaptive)  
**Location:** `src/services/realtime_decision_engine.py`  
**Normal Mode:** `0.18` (18% raw ML confidence required)  
**Unblock Mode:** `0.12` (relaxed, during stall recovery)  
**Description:** Minimum ML model confidence to pass entry filter  
**Update Trigger:** Every 50 trades via calibration loop

### Minimum Volatility
**Parameter:** `MIN_VOLATILITY`  
**Location:** `config.py`  
**Value:** `0.001` (0.1%)  
**Description:** Reject signals if ATR too low (market too quiet)  
**Rationale:** Prevents knife-catching in ranging/dead markets

### Minimum Confidence
**Parameter:** `MIN_CONFIDENCE`  
**Location:** `config.py`  
**Value:** `0.55` (55%)  
**Description:** Hard floor on Bayesian-calibrated win probability  
**Rationale:** Edge must be >50% to trade

### Frequency Cap
**Parameter:** `MAX_TRADES_15` (per 15-minute window)  
**Location:** `src/services/realtime_decision_engine.py`  
**Value:** `15` (raised from 8; allows high-edge pairs to trade freely)  
**Description:** Circuit breaker on signal frequency  
**Mechanism:** Skip signal if >15 trades in last 15 minutes  
**Rationale:** Prevents overtrading even with positive EV

### Micro-Momentum Check
**Parameter:** `knife_catch_filter` (implicit)  
**Value:** `price ≥ avg(last_3_ticks)`  
**Description:** Reject signals on downward momentum (anti-knife-catch)  
**Rationale:** Avoids whipsaw entries on reversal tails

---

## EXIT HIERARCHY

### MICRO_TP (Regime-Adaptive)

**Base Value:** `0.0010` (0.10%)  
**Regime Variants:**
- BULL_TREND: `0.0012` (wider — trends move fast)
- BEAR_TREND: `0.0012`
- BULL_RANGE: `0.0008` (tighter — ranges move slow)
- BEAR_RANGE: `0.0008`
- RANGING: `0.0009`
- QUIET_RANGE: `0.0006` (tightest — dead markets)
- UNCERTAIN: `0.0010`

**Description:** Ultra-tight profit harvest  
**Trigger:** Position ≥ threshold AND pnl ≥ 0  
**Purpose:** Capture scalp-style wins immediately

### Breakeven Stop

**Parameter:** `BREAKEVEN_TRIGGER_PCT`  
**Value:** `0.20` (20% of TP move)  
**Description:** Move SL to entry price once reaching 20% profit  
**Trigger:** Once position reaches 20% of target profit  
**Purpose:** Lock gains early, reduce downside risk

### Partial TP Levels (Multi-Level Harvest)

#### Partial TP 25%
**Parameter:** `PARTIAL_TP_25_BASE`  
**Value:** `0.25` (25% of TP move)  
**Trigger:** Position ≥ 25% of distance from entry to TP  
**Purpose:** First harvest milestone

#### Partial TP 50%
**Parameter:** `PARTIAL_TP_50_BASE`  
**Value:** `0.50` (50% of TP move)  
**Trigger:** Position ≥ 50% of distance from entry to TP  
**Purpose:** Second harvest milestone

#### Partial TP 75%
**Parameter:** `PARTIAL_TP_75_BASE`  
**Value:** `0.75` (75% of TP move)  
**Trigger:** Position ≥ 75% of distance from entry to TP  
**Purpose:** Final harvest before timeout

### Early Stop (Tight Loss Exit)

**Parameter:** `EARLY_STOP_THRESHOLD`  
**Value:** `0.60` (60% of SL distance)  
**Description:** Cut losers at partial loss  
**Trigger:** Unrealized loss ≥ 60% of stop loss distance  
**Purpose:** Prevent full SL hit; exit early on deterioration  
**Rationale:** Better than zero-loss-streak circuit breaker

### Trailing Stop

**Activation Threshold (Regime-Adaptive):**
- Base: `0.003` (0.3% favorable move)
- BULL_TREND: `0.0035` (wider activation)
- BEAR_TREND: `0.0035`
- BULL_RANGE: `0.0025` (tighter activation)
- BEAR_RANGE: `0.0025`
- RANGING: `0.0025`
- QUIET_RANGE: `0.0020` (tightest)

**Minimum Peak MFE:** `0.001` (0.1%)  
**Retrace Threshold:** `TRAILING_RETRACE_PCT = 0.50` (50%)  
**Description:** Exit on retracement from peak MFE  
**Trigger:** Once peak MFE ≥ threshold AND retraces ≥ 50%  
**Purpose:** Lock retracement profits mid-move

### Scratch Exit (Flat Release)

**Parameter:** `SCRATCH_MIN_AGE_S`  
**Value:** `90` (seconds)  
**Constant:** `SCRATCH_MAX_PNL = 0.0015` (0.15%)  
**Trigger:** Age ≥ 90s AND |pnl| < 0.15%  
**Purpose:** Exit near-flat trades early instead of timeout  
**Rationale:** Recovers capital for better opportunities

### Stagnation Exit

**Parameter:** `STAGNATION_MIN_AGE_S`  
**Value:** `110` (seconds)  
**Constant:** `STAGNATION_MAX_PNL = 0.0005` (0.05%)  
**Trigger:** Age ≥ 110s AND |pnl| < 0.05%  
**Purpose:** Exit completely stuck positions  
**Rationale:** Forced exit before timeout fallback

### Timeout Fallback

**Window:** `120–300 seconds` (varies by symbol)  
**Base:** `120s` minimum, `180s` typical, `300s` maximum  
**Description:** Force exit if no prior condition triggered  
**Purpose:** Capital efficiency; prevent indefinite holds  
**Fallback Logic:** Exit at market, loss absorbed

### Target Profit (TP) Calculation

**Formula:**
```
TP = entry_price + (ATR × regime_multiplier)
```

**Regime Multipliers:**
- BULL_TREND: `TP_MULT = 0.6`
- BEAR_TREND: `TP_MULT = 0.6`
- RANGING: `TP_MULT = 0.5`
- QUIET_RANGE: `TP_MULT = 0.4`

### Stop Loss (SL) Calculation

**Formula:**
```
SL = entry_price - (ATR × regime_multiplier)
```

**Regime Multipliers:**
- BULL_TREND: `SL_MULT = 0.4`
- BEAR_TREND: `SL_MULT = 0.4`
- RANGING: `SL_MULT = 0.4`
- QUIET_RANGE: `SL_MULT = 0.35`

**Minimum SL Distance:** `MIN_SL = 0.0020` (0.2%)  
**Minimum TP Distance:** `MIN_TP = 0.0025` (0.25%)  
**Risk-Reward Ratio:** `MIN_RR = 1.25`

---

## LEARNING & CALIBRATION

### Bayesian Calibration Buckets

**Structure:** Confidence scores grouped in 0.1 increments  
**Buckets:** 0.5, 0.6, 0.7, 0.8, 0.9, 1.0  
**Per-Bucket Tracking:** [wins, total trades]

### Calibration Minimum Sample Size

**Parameter:** `CALIBRATION_MINIMUM` (implicit)  
**Value:** `30` (trades per bucket)  
**Description:** Minimum trades before bucket WR becomes credible  
**Before Threshold:** Use conservative prior of `0.50`

### Convergence Window

**Parameter:** `CONVERGENCE_WINDOW`  
**Location:** `learning_monitor.py`  
**Value:** `10–20` trades  
**Description:** Rolling window for EV stability calculation  
**Purpose:** Detect sharp performance changes

### Health Score Calculation

**Input Factors:**
- Convergence (EV variance)
- Win rate vs. target (55%)
- Profit factor (gross profit / gross loss)

**Health Thresholds:**
- `Health ≥ 0.50`: NORMAL mode (standard gates)
- `0.10 ≤ Health < 0.50`: DEGRADED mode (tighten entries)
- `Health < 0.10`: CRISIS mode (minimal trading)

### Update Frequency

**Calibration:** Every closed trade  
**Health Recalc:** Every 50 trades  
**Dashboard:** Every 10 seconds

---

## HEALTH & SAFETY

### Safe Mode Triggers

**Trigger 1 — Equity Drop**
- Condition: Account equity drops unexpectedly
- Response: Risk multiplier → 50%, max position size → 50%
- Mode: `safe_mode = True`

**Trigger 2 — High Drawdown**
- Condition: Drawdown > 35%
- Response: Risk multiplier → 30%, filter strength ↑ 20%
- Mode: `safe_mode = True`

**Trigger 3 — Stall (No Trades for 900s)**
- Condition: 900 seconds without signal
- Response: Exploration factor ↑ 50%, EV threshold ↓ 10%
- Mode: Micro-trading enabled

### Safe Mode Position Sizing

**During Safe Mode:**
- Base position size × 0.3 (reduced to 30%)
- Confidence × 0.8 (signal confidence penalized)
- Minimum floor: 1% of account (micro mode)

### Failsafe Halt Condition

**Trigger:** `safe_mode = True` AND `drawdown > 0.45`  
**Response:** `trading_enabled = False`  
**Recovery:** Manual restart via systemd  
**Log Level:** CRITICAL

### Runtime Fault Registry (V10.13L)

**Mechanism:** Track hard failures in smart_exit_engine, signal_generator, trade_executor  
**Response:** If fault marked, `is_trading_allowed() = False`  
**Behavior:** Fail-closed; no new trades until manual recovery

---

## ENVIRONMENT TOGGLES

### Exit Audit Debug

**Parameter:** `EXIT_AUDIT_DEBUG`  
**Value:** `"0"` (disabled) or `"1"` (enabled)  
**Usage:** `export EXIT_AUDIT_DEBUG=1`  
**Effect:** Emits `[EXIT_AUDIT]` logs for every branch evaluation  
**Overhead:** ~5-10% logging overhead when enabled

### Exit Audit Verbosity

**Parameter:** `EXIT_AUDIT_VERBOSE`  
**Value:** `"0"` (disabled) or `"1"` (enabled)  
**Usage:** `export EXIT_AUDIT_VERBOSE=1`  
**Effect:** Emits per-branch metrics (requires EXIT_AUDIT_DEBUG=1)  
**Overhead:** ~10-15% when enabled

### Signal Engine Enabled

**Parameter:** `SIGNAL_ENGINE_ENABLED`  
**Value:** `"0"` (legacy sync) or `"1"` (async async)  
**Usage:** `export SIGNAL_ENGINE_ENABLED=1`  
**Effect:** Routes signals through async Redis channel  
**Default:** Currently disabled; legacy sync path active

### Redis URL

**Parameter:** `REDIS_URL`  
**Value:** `"redis://localhost:6379/0"` (default)  
**Usage:** `export REDIS_URL="redis://host:port/db"`  
**Impact:** In-memory cache location; Firebase fallback if unavailable

---

## DEFAULT CONFIGURATION

### Firestore Paths

**Trades:** `/trades/{trade_id}` (entry_price, exit_price, pnl_pct, timestamp)  
**System Stats:** `/system/stats` (total_wins, total_losses, win_rate, profit_factor)  
**Learning State:** `/learning/{symbol}` (per-symbol calibration buckets)

### Redis Keys

**Learning State:** `LM_STATE` (win_rate, profit_factor, convergence, health, regime)  
**Live Positions:** `positions:{symbol}` (entry, current P&L, TP/SL, MFE/MAE)  
**Signal Channel:** `signals` (PubSub for TradeSignal objects)  
**Audit Channel:** `audits` (PubSub for exit audit logs)

### Systemd Service

**Service File:** `/etc/systemd/system/cryptomaster.service`  
**User:** `cryptomaster` (non-root)  
**Restart:** Always  
**Start:** `python /opt/cryptomaster/bot2/main.py`  
**Logs:** `journalctl -u cryptomaster -f`

### Cold Start Hydration Sequence

```
1. Try Redis hydration (LM_STATE)
2. If unavailable → Bootstrap from Firestore (last 100 trades)
3. Rebuild learning state from trade history
4. Initialize calibration buckets
5. Calculate health score
6. Log bootstrap status via log_bootstrap_status()
```

---

**Document Version:** 1.0  
**Last Sync:** 2026-04-17  
**Next Review:** After V10.13n evidence analysis
