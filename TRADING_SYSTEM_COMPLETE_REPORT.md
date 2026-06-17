# CRYPTOMASTER HF-QUANT 5.0 — COMPLETE TRADING SYSTEM REPORT
**Generated:** 2026-06-17 11:00 UTC  
**Version:** V10.13m + V10.27 (Senior Fixes)  
**Status:** Live Trading (Paper Mode + Autonomous Optimization)

---

## EXECUTIVE SUMMARY

**CryptoMaster** is a high-frequency algorithmic trading bot for Binance crypto pairs using:
- **EV-Only principle**: Trade only when expected value is positive
- **Bayesian calibration**: Map model confidence → empirical win probability
- **Multi-level exit hierarchy**: 9 exit conditions capture profits at scale
- **Adaptive risk management**: Dynamic position sizing + regime-aware thresholds
- **Autonomous learning loop**: Continuous self-optimization via evidence-based patches

**Current Status (Cycle 2, 2026-06-17):**
- Live metrics: WR=0%, P&L=-5.50 USD, 100% TIMEOUT exits
- Root cause: TP/SL targets (80/50 bps) unreachable in 600s flat market
- Real fix: Volatility-based calibration to shrink targets proportional to observed movement
- Autonomous loop: Running Layer 2 (Diagnose) with all 8 specialized agents

---

## 1. SYSTEM ARCHITECTURE

### Data Flow Pipeline
```
┌─────────────────────────────────────┐
│ Binance WebSocket (price ticks)     │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ market_stream.py                    │
│ - Parse OHLCV, OBI (order imbalance)│
│ - Publish 'price_tick' to event_bus │
└──────────────────┬──────────────────┘
                   ▼
┌─────────────────────────────────────┐
│ event_bus.py (central router)       │
│ - Publish-Subscribe pattern         │
└─┬────────────┬────────────┬─────────┘
  │            │            │
  ▼            ▼            ▼
ANALYSIS    EXECUTION    LEARNING
  │            │            │
signal_gen  trade_exec   learning_ev
regime_pred risk_engine  smart_exit
```

### Core Modules (8 Specialized Components)

| Module | Role | Key Function |
|--------|------|--------------|
| **market_stream.py** | Market ingestion | WebSocket listener, OHLCV parsing, OBI calculation |
| **signal_generator.py** | Signal generation | ADX/RSI/MACD/EMA feature extraction, trend classification |
| **signal_engine.py** | Signal routing | Regime detection (BULL_TREND, BEAR_TREND, RANGING, etc.) |
| **realtime_decision_engine.py** | EV gating | Bayesian calibration, EV calculation, entry approval |
| **trade_executor.py** | Position lifecycle | Entry validation, size calculation, execution flow |
| **risk_engine.py** | Risk management | Portfolio variance, correlation-aware sizing, circuit breakers |
| **smart_exit_engine.py** | Exit evaluation | 9-level exit hierarchy, multi-scale profit capture |
| **learning_monitor.py** | Calibration loop | Per-bucket win rate tracking, confidence recalibration |

---

## 2. SIGNAL GENERATION & FEATURE EXTRACTION

### Input: Market Data
- **Price**: OHLCV (Open, High, Low, Close, Volume)
- **Order Book**: Bid/ask imbalance (OBI)
- **Time**: Tick timestamp, 1-minute candlestick
- **History**: Last 20-30 candles for indicator warmup

### Feature Pipeline
```
Raw OHLCV
    ↓
ADX(14)     → Trend strength (0-100; >25 = trend)
RSI(14)     → Momentum (0-100; >70 = overbought, <30 = oversold)
MACD        → Momentum divergence
EMA(12,26)  → Short/long trend
Bollinger   → Volatility bands
OBI         → Order book imbalance
```

### Regime Classification (7 States)
| Regime | Condition | Trading Behavior |
|--------|-----------|------------------|
| **BULL_TREND** | ADX > 25, EMA(12) > EMA(26) | Long bias, larger TP targets |
| **BEAR_TREND** | ADX > 25, EMA(12) < EMA(26) | Short bias, larger TP targets |
| **BULL_RANGE** | ADX < 25, price > MA(50) | Bounce trades, tight TP (0.4-0.6%) |
| **BEAR_RANGE** | ADX < 25, price < MA(50) | Fade trades, tight TP (0.4-0.6%) |
| **RANGING** | ADX < 20, no clear direction | Choppy, skip entries |
| **QUIET_RANGE** | ADX < 15, vol < 0.05% | Dead market, MICRO_TP only (0.06%) |
| **UNCERTAIN** | Insufficient data | Default conservative prior |

### Signal Output Structure
```json
{
  "symbol": "BTCUSDT",
  "action": "BUY",              // BUY, SELL, or HOLD
  "regime": "BULL_TREND",       // 7-state classification
  "raw_confidence": 0.72,       // ML model output (0.0-1.0)
  "features": {
    "trend": 1,                 // Bool: uptrend detected
    "pullback": 0.5,            // 0-1: pullback strength
    "breakout": 0.8,            // 0-1: breakout strength
    "wick": 0.3,                // 0-1: wick (rejection) strength
    "volatility": 450,          // ATR(20)
    "momentum": "positive",      // MACD signal
    "bounce": 1,                // Bool: bounce from support
    "is_weekend": 0             // Weekend flag
  },
  "timestamp": 1713358800
}
```

---

## 3. DECISION ENGINE: EV-ONLY PRINCIPLE

### The Core Formula
```
EV = (Win_Probability × Risk_Reward) - (1 - Win_Probability)
```

**Example with RR=1.25:**
- P(win)=0.60 → EV = 0.60×1.25 - 0.40 = +0.35 ✓ Trade
- P(win)=0.55 → EV = 0.55×1.25 - 0.45 = +0.2375 ✓ Trade
- P(win)=0.44 → EV = 0.44×1.25 - 0.56 = -0.05 ✗ Skip

### Bayesian Calibration (Confidence → Win Probability)

**Problem**: Raw model confidence doesn't match reality.
- Model says "70% confident" → Reality: only 52% win rate

**Solution**: Per-bucket empirical win rates
```
Confidence Range  Bucket Center  Empirical Win Rate (after 30+ trades)
0.45-0.55         0.50          54%
0.55-0.65         0.60          55%
0.65-0.75         0.70          63% ← Good bucket!
0.75-0.85         0.80          75% ← Excellent!
0.85-0.95         0.90          68%
```

**Calibration Loop:**
```
1. Signal enters at 0.68 raw confidence
   → Bucket 0.70 (nearest center)
   → Before 30 trades: use prior 0.50
   → After 30 trades: use empirical 0.63

2. Trade closes: WIN
   → Increment bucket 0.70: wins++, total++
   → When total ≥ 30: empirical = wins/total

3. Next signal at 0.69: uses updated calibration
```

### Entry Gate Sequence
```
Signal arrives
    ↓
1. Micro-momentum: price ≥ avg(last_3_ticks)? → PASS/FAIL
    ↓
2. Calibration lookup: raw_conf → empirical P(win)
    ↓
3. RR calculation: (TP - entry) / (entry - SL)  [must be ≥ 1.25]
    ↓
4. EV calculation: P(win) × RR - (1 - P(win))
    ↓
5. EV gate: EV ≥ threshold? [cold start: 0.15; online: adaptive]
    ↓
6. Macro gates: volatility, frequency cap, correlation
    ↓
7. Risk engine: position size via portfolio variance
    ↓
EXECUTE (or SKIP if any gate fails)
```

### EV Threshold Logic
- **Cold start** (first 100 trades): EV ≥ 0.15 (conservative)
- **Online**: EV ≥ 75th percentile of last 50 EVs (adaptive)
- **Floor**: EV ≥ 0.10 (never trade negative EV)

---

## 4. POSITION LIFECYCLE: ENTRY TO EXIT

### Position Opening (open_paper_position)

**Inputs:**
- Signal with EV, raw confidence, regime, symbol
- Current market price
- Position context (training vs live, bucket assignment)

**Process:**
```python
1. Validate price (non-zero, real)
2. Check symbol exposure cap
3. Calculate entry fee drag
4. Determine side (BUY/SELL) with diversity enforcement
5. Calibrate TP/SL via geometry_calibration()
   - Detects: expected_move_pct (observed volatility)
   - If expected_move < 0.15%: FLAT MARKET → shrink TP to 0.40%
   - If expected_move > 0.15%: VOLATILE → scale TP to 75% of move
6. Store position with metadata (ev, score, calibrated flag)
7. Add to _POSITIONS dict and persist JSON state
```

**Stored Position Object:**
```json
{
  "trade_id": "paper_12a4f8...",
  "symbol": "ETHUSDT",
  "side": "BUY",
  "entry_price": 1770.015,
  "entry_ts": 1718606178.5,
  "tp": 1784.175,                 // 80 bps above entry
  "sl": 1761.165,                 // 50 bps below entry
  "tp_pct_at_entry": 0.80,        // Before calibration
  "geometry_calibrated": true,     // Flag: was calibrated
  "tp_pct_before_calibration": 1.33,  // Original wider target
  "size_usd": 25.0,
  "regime": "BULL_TREND",
  "ev_at_entry": 0.045,
  "score_at_entry": 0.19,
  "max_hold_s": 600,
  "last_price": 1770.015,
  "max_seen": 1770.715,           // MFE tracking
  "min_seen": 1769.500,           // MAE tracking
  "entry_features": {...}
}
```

### Position Evaluation (update_paper_positions)

**Triggered**: Every market price tick  
**Per-position checks:**

```python
1. Fetch current price for symbol
2. Update max_seen, min_seen (for MFE/MAE)
3. Calculate unrealized pnl_pct = (current_price - entry) / entry
4. Calculate position age in seconds
5. Sync TP/SL from env vars (PAPER_TP_ZONE_BPS, PAPER_SL_ZONE_BPS)
   - Overrides at-entry calibration on EVERY tick
   - Currently: 80 bps TP / 50 bps SL
6. Evaluate smart_exit_engine (9 exit levels)
7. If exit condition met: close_paper_position()
```

---

## 5. SMART EXIT ENGINE: 9-LEVEL HIERARCHY

### Exit Priority Order (First match fires)

| Level | Name | Threshold | Purpose |
|-------|------|-----------|---------|
| 1 | **MICRO_TP** | 0.06%-0.12% (regime-dependent) | Scalp tiny wins immediately |
| 2 | **BREAKEVEN_STOP** | 20% of TP move | Lock gains, move SL to entry |
| 3 | **PARTIAL_TP_25** | 25% of TP distance | First harvest milestone |
| 4 | **PARTIAL_TP_50** | 50% of TP distance | Second harvest milestone |
| 5 | **PARTIAL_TP_75** | 75% of TP distance | Final harvest milestone |
| 6 | **EARLY_STOP** | 60% of SL distance (loss) | Cut losses before big bleed |
| 7 | **TRAILING_STOP** | Retrace from peak MFE | Protect gains from reversal |
| 8 | **SCRATCH_EXIT** | Near-flat (|pnl| < 0.03%) after 90s | Free capital for next trade |
| 9 | **STAGNATION_EXIT** | Stuck (no price move) after 110s | Avoid zombie positions |
| 10 | **TIMEOUT** | age ≥ 600s (fallback) | Hard limit; never hold indefinitely |

### Critical State Variables

**pnl_pct** (Profit/Loss %)
- Formula: `(current_price - entry_price) / entry_price`
- Updated: Every tick
- Used by: All 9 exit conditions

**age_seconds** (Position age)
- Formula: `time.time() - entry_timestamp`
- Used by: SCRATCH (≥90s), STAGNATION (≥110s), TIMEOUT (≥600s)

**max_favorable_pnl** (Peak P&L since entry)
- Updated: Only increases, never decreases
- Used by: TRAILING_STOP, BREAKEVEN_STOP

### Example: Full Exit Progression (ETHUSDT, BULL_TREND)

```
Entry: 2000 at 10:00:00
TP: 2020 (1.00%), SL: 1990 (0.50%), Timeout: 600s

10:00:05 → Price: 2000.12 (+0.006%)
         MICRO_TP threshold: 0.0012 (0.12%)
         Status: 0.006% < 0.012% → SKIP

10:00:15 → Price: 2003 (+0.15%)
         PARTIAL_TP_25: 25% of 1.00% = 0.25%
         Status: 0.15% < 0.25% → SKIP

10:00:45 → Price: 2005.30 (+0.265%)
         PARTIAL_TP_25: 0.25%
         Status: 0.265% > 0.25% → FIRES ✓
         Exit 25% of position, keep 75%

10:00:50 → Price: 2010 (+0.50%)
         PARTIAL_TP_50: 50% of 1.00% = 0.50%
         Status: 0.50% = 0.50% → FIRES ✓
         Exit another 25%, keep 50%

10:00:55 → Price: 2015 (+0.75%)
         PARTIAL_TP_75: 75% of 1.00% = 0.75%
         Status: 0.75% = 0.75% → FIRES ✓
         Exit another 25%, keep 25%

10:01:00 → Price: 2020.50 (+1.025%)
         Full TP or TIMEOUT fires
         Status: Hit TP (or close) → FIRES ✓
         Exit final position

Total: 4 partial exits + 1 final exit
Result: Average exit prices at 0.25%, 0.50%, 0.75%, 1.00%+
Capital freed: 3 trades' worth returned mid-cycle
```

---

## 6. THE CURRENT BOTTLENECK (Cycle 2)

### Symptom
- WR = 0% (zero TP/SL exits in 60 minutes)
- 100% TIMEOUT exits (all positions age to 600s)
- P&L = -5.50 USD (fee bleed accumulating)

### Root Cause Analysis (Senior Forensics)
```
TP/SL Configuration:
  - Effective bands: 80 bps TP / 50 bps SL (set in systemd override.conf)
  - CYCLE#15_SYNC: Enforces these every tick (confirmed firing in logs)
  
Market Reality (Live positions, last 60 min):
  - Avg favorable travel: 10-15 bps toward TP
  - Min reach: 1-7 bps in 600s window
  - Max reach: ~40 bps (one outlier position)
  
Physics Mismatch:
  - Need: 80 bps to hit TP
  - Have: 10-15 bps movement available
  - Ratio: 5-8x too far
```

### Why Bands Can't Just Be Narrowed
Changing systemd override.conf to `PAPER_TP_ZONE_BPS=20` would:
- ✓ Increase TP hits (lower target)
- ✓ Improve WR short-term
- ✗ Introduce SL noise (tight SL fires on volatility)
- ✗ Reduce R/R (smaller target, same SL) → negative EV

### Real Solution: Volatility-Based Calibration
**Insight**: The `calibrate_paper_training_geometry()` function exists but is BROKEN.

**Bug**: Line 2683 uses `max(original_tp, target)` → never shrinks TP in flat market

**Fix** (V10.27):
```python
# Detect flat market via expected_move_pct
if expected_move_pct < 0.15%:    # Flat market
    tp_target_pct = 0.40%        # Shrink to 40 bps (reachable)
else:                             # Volatile market
    tp_target_pct = expected_move_pct * 0.75  # 75% of observed move

# Always apply calibration (not max(old, new))
new_tp_pct = min(original, tp_target_pct)  # Allow shrinking
```

**Expected Result**: TP targets scale to market reality, TP/SL hits increase, WR > 0%

---

## 7. LEARNING SYSTEM & AUTONOMOUS OPTIMIZATION

### Learning Loop (Calibration)
```
Trade closes with result (WIN / LOSS)
    ↓
Fetch original signal's raw_confidence (stored at entry)
    ↓
Find bucket: confidence → nearest 0.1 increment
    ↓
Increment bucket: if WIN then wins++, always total++
    ↓
If bucket.total ≥ 30: empirical = bucket.wins / bucket.total
                      (now used for future signals in this bucket)
    ↓
Next signal with same raw_confidence uses updated P(win)
```

### Autonomous Optimization (Layer-Based Orchestration)
```
┌─────────────────────────────────────────┐
│ LAYER 1: Monitor (30-min cadence)       │
│ monitoring-remediation-agent            │
│ → Collect: WR%, PF, P&L, quota status   │
│ → Decide: GOAL_REACHED | CAUTION | FAIL │
└──────────────┬──────────────────────────┘
               │
        FAIL? → Go to Layer 2
        
┌──────────────┴──────────────────────────┐
│ LAYER 2: Diagnose & Fix (Parallel)      │
│ evidence-based-patch-orchestrator       │
│ 8 agents (forensic, learning, quota,    │
│ safety, tests, patch, review, ready)    │
│ → Identify root cause with evidence     │
│ → Author minimal patch                  │
│ → Validate safety + tests               │
│ → Get reviewer approval                 │
└──────────────┬──────────────────────────┘
               │
        APPROVED? → Go to Layer 3
        
┌──────────────┴──────────────────────────┐
│ LAYER 3: Deploy & Verify (Atomic)       │
│ deploy-verify-agent                     │
│ → git push → GH Actions → systemctl     │
│ → 2-min health check                    │
│ → PASS: Continue to next cycle          │
│ → FAIL: Auto-revert, wait 1h, retry     │
└──────────────┬──────────────────────────┘
               │
        After 30 min measurement window
        Loop back to Layer 1 (Monitor)
```

### Safeguards
- **Max 100 cycles** (prevent infinite loops)
- **Regression detection** (stop if WR drops 3× in row)
- **Quota respect** (stop if < 10% until 07:00 UTC reset)
- **Atomic deployment** (fail → revert, never partial states)

---

## 8. CURRENT METRICS (Cycle 2, 2026-06-17 10:55 UTC)

| Metric | Value | Status |
|--------|-------|--------|
| Win Rate (WR) | 0.0% | ❌ Target: > 55% |
| Profit Factor (PF) | 0.16 | ❌ Target: > 1.05 |
| Net P&L | -5.50 USD | ❌ Target: > 0 USD |
| Closed Trades | 36 | ✓ Good activity |
| Exit Distribution | 100% TIMEOUT | ❌ Need TP/SL hits |
| Firebase Quota | 0/40k reads | ✓ GO (fresh reset) |
| Avg MFE to TP Ratio | 8.6% | ❌ Need 100% to hit 80 bps |

---

## 9. NEXT STEPS (Autonomous Loop Continuing)

**Orchestrator Status**: Running Layer 2 (Diagnose)
- ✓ Root cause confirmed: TP/SL unreachable in flat market
- 🔍 Verifying: Volatility-based calibration fix is sound
- ⏳ Next: Deploy atomic patch (volatility detection + TP shrinking)
- 📊 Monitor: Metrics for TP/SL hits improving (from 0% → target)

**Success Criteria**:
- WR > 55% sustained 24h
- P&L > 0 USD sustained 24h
- Autonomy: Loop runs without human intervention

---

## APPENDIX: KEY FILES & LOCATIONS

| Component | File | Lines | Purpose |
|-----------|------|-------|---------|
| Signals | `signal_generator.py` | 1-800 | Feature extraction, regime detection |
| Decision | `realtime_decision_engine.py` | 1-600 | EV gating, Bayesian calibration |
| Execution | `trade_executor.py` | 1-2500 | Position lifecycle, risk engine |
| Paper Execution | `paper_trade_executor.py` | 1-3400 | Paper position management, calibration |
| Exits | `smart_exit_engine.py` | 1-1200 | 9-level exit hierarchy, audit logs |
| Learning | `learning_monitor.py` | 1-800 | Win rate tracking, health scoring |
| Calibration | `learning_event.py` | 1-600 | Per-bucket updates, persistence |
| Market Data | `market_stream.py` | 1-400 | WebSocket, OHLCV parsing, OBI |
| Routing | `event_bus.py` | 1-200 | Publish-Subscribe pattern |
| Risk | `risk_engine.py` | 1-400 | Portfolio variance, sizing |

---

## CONCLUSION

**CryptoMaster HF-Quant 5.0** is a sophisticated event-driven trading system with:
- ✅ Rigorous EV-only entry gate (no luck-based trading)
- ✅ Bayesian calibration (confidence → empirical win probability)
- ✅ Multi-scale exit strategy (9 exit levels for efficient capital)
- ✅ Autonomous self-healing (agents diagnose & fix themselves)

**Current Challenge**: Flat market makes 80 bps TP unreachable.  
**Autonomous Solution**: Volatility-calibrated TP sizing (in progress via Layer 2 agents).  
**Success Threshold**: WR > 55% + P&L > 0% sustained 24h.

---

*Report generated during autonomous optimization cycle. All data live as of 2026-06-17 11:00 UTC.*
