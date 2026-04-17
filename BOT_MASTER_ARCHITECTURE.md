# CryptoMaster HF-Quant 5.0 — Master Architecture Document

**Version:** V10.13m+  
**Last Updated:** 2026-04-17  
**Status:** Production (Hetzner 24/7)

---

## 1. SYSTEM OVERVIEW

### Mission
Real-time algorithmic trading on Binance crypto pairs (BTC, ETH, ADA, BNB, DOT, SOL, XRP) using Expected Value (EV) gating, Bayesian calibration, and adaptive risk management.

### Core Principle
**EV-Only Engine**: Trade ONLY when mathematical expected value is positive. All decisions flow through this gate.

### Architecture Pattern
- **Event-Driven**: Market data (WebSocket) → Event Bus → Analysis → Execution
- **Reactive Pipeline**: Every price tick triggers a decision cycle (~100ms)
- **Stateless Modules**: Each component has one clear responsibility
- **Persistent Learning**: Firebase (trades) + Redis (real-time state)

---

## 2. DATA FLOW PIPELINE

```
┌─────────────────────────────────────────────────────────────────┐
│ INPUT: Binance WebSocket (price ticks, order book updates)       │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ market_stream.py: WebSocket listener                             │
│  - Parse tick: symbol, price, bid/ask volumes                   │
│  - Calculate: OBI (Order Book Imbalance)                         │
│  - Publish: 'price_tick' event to event_bus                      │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ event_bus.py: Central message router                            │
│  - Subscribers: signal_generator, trade_executor, learning_event │
│  - Pattern: Publish-Subscribe (one tick → multiple consumers)   │
└─────────────────────────────────────────────────────────────────┘
                    │                    │
         ┌──────────┴──────────┬─────────┴──────────┐
         ▼                     ▼                     ▼
    ┌──────────┐          ┌──────────┐          ┌──────────┐
    │ ANALYSIS │          │EXECUTION │          │ LEARNING │
    └──────────┘          └──────────┘          └──────────┘
         │                     │                     │
         ▼                     ▼                     ▼
    signal_generator → realtime_decision_engine → learning_event
    signal_engine            trade_executor        learning_monitor
    regime_predictor         risk_engine           metrics_update
                            smart_exit_engine      
                                                 (Firebase/Redis)
```

---

## 3. CORE MODULES

### 3.1 MARKET INGESTION (market_stream.py)
**Purpose:** Real-time price data from Binance WebSocket

**Inputs:**
- Binance WSS `@klines@1m` streams (all symbols)
- Order book depth snapshots

**Processing:**
- Parse OHLCV: Open, High, Low, Close, Volume
- Calculate OBI = (BidVolume - AskVolume) / (BidVolume + AskVolume)
- Track 3-tick price history (anti-knife-catch filter)

**Outputs:**
- Event: `price_tick(symbol, price, obi, timestamp)`

**Safety:**
- Reconnect on disconnect (heartbeat: 30s ping interval)
- No client-side ping timeout (let Binance drive heartbeat)

---

### 3.2 SIGNAL GENERATION (signal_generator.py + signal_engine.py)
**Purpose:** Convert market data into trading signals

**Process:**
1. **Feature Extraction**: ADX, EMA, MACD, Bollinger Bands, RSI
2. **Trend Classification**: BULL_TREND, BEAR_TREND, BULL_RANGE, BEAR_RANGE, RANGING, QUIET_RANGE
3. **Signal Generation**: BUY, SELL, HOLD
4. **Confidence Score**: Raw ML model output (0.0-1.0)
5. **Feature Vector**: [momentum, pullback, breakout, wick, vol, bounce, trend, is_weekend]

**Outputs:**
```json
{
  "symbol": "BTCUSDT",
  "action": "BUY",
  "regime": "BULL_TREND",
  "entry_price": 75030.12,
  "tp_ratio": 1.2,
  "sl_ratio": 0.8,
  "confidence": 0.72,
  "features": {...},
  "timestamp": 1713358800
}
```

---

### 3.3 DECISION ENGINE (realtime_decision_engine.py)
**Purpose:** EV gating + Bayesian calibration

**Gate Sequence:**
1. **Micro-Momentum Check**: Price must be ≥ average of last 3 ticks (prevents knife-catches)
2. **Bayesian Calibration**: Map raw confidence → empirical win probability
3. **EV Calculation**: `EV = (win_prob × RR) - (1 - win_prob)` where RR = 1.25
4. **EV Gate**: Only proceed if EV ≥ 0.100 (configurable threshold)
5. **Macro Guard**: Filter by correlation + regime + symbol health

**Bayesian Calibration Logic:**
- Buckets: Confidence scores grouped in 0.1 increments (0.5, 0.6, 0.7, etc.)
- Per-bucket tracking: [wins, total trades]
- Calibration live after ≥30 trades per bucket
- Before that: conservative prior 0.50

**Output:**
```json
{
  "symbol": "BTCUSDT",
  "approved": true,
  "ev": 0.15,
  "win_probability": 0.58,
  "risk_reward": 1.25,
  "tp": 75842.65,
  "sl": 74648.09,
  "reason": "EV=0.15 passed gate"
}
```

---

### 3.4 EXECUTION (trade_executor.py)
**Purpose:** Order placement and position lifecycle management

**Safety Layers:**
1. **Risk Engine**: Portfolio variance budgeting (correlation-aware)
2. **L2 Rejection**: Order book depth filter (reject if bid-ask spread too wide)
3. **Wall Exit Detection**: Exit if hit by major market move mid-trade
4. **Smart Exit Engine**: Multi-level exit hierarchy (V10.13g+)
5. **Runtime Fault Registry** (V10.13L): Fail-closed gate if smart_exit_engine crashes

**Process:**
1. Calculate position size: `size = risk_budget / sl_distance`
2. Check macro exposure + correlation
3. Place order: LIMIT (not market)
4. Hydrate position state (TP, SL, MFE, MAE, age)
5. Wait for fills
6. Monitor for smart exits

**Exit Hierarchy (V10.13g+):**
1. MICRO_TP (0.10% profit harvest)
2. BREAKEVEN_STOP (lock gains at 20% of TP)
3. PARTIAL_TP_25/50/75 (multi-level harvest)
4. EARLY_STOP (cut at 60% of SL)
5. TRAILING_STOP (retracement from peak MFE)
6. SCRATCH_EXIT (near-flat after 90s)
7. STAGNATION_EXIT (stuck after 110s)
(Timeout fallback at 120-300s)

---

### 3.5 LEARNING SYSTEM (learning_monitor.py + learning_event.py)
**Purpose:** Continuous calibration and performance tracking

**Metrics Tracked:**
- **Convergence**: EV stability (std of last 10-20 trades)
- **Win Rate**: Wins / Total
- **Profit Factor**: Gross profit / Gross loss
- **Health Score**: Function of convergence + edge strength

**Health Thresholds:**
- Health ≥ 0.50: NORMAL mode
- 0.10 ≤ Health < 0.50: DEGRADED mode (tighten entries)
- Health < 0.10: CRISIS mode (minimal trading)

**Calibration Update:**
Every closed trade → Calibrator updates win/total counts in confidence buckets

**Persistence:**
- Redis: Real-time LM_STATE (zero-loss cold starts)
- Firestore: Historical trades + metrics (long-term recovery)

---

### 3.6 SMART EXIT ENGINE (smart_exit_engine.py) [V10.13m+]
**Purpose:** Intelligent position exit with full observability

**Exit Audit (V10.13m):**
- **Counters**: Track why branches pass/fail
  - `_exit_audit_rejections`: {branch:reason: count}
  - `_exit_winners`: {exit_type: count}
  - `_timeout_preemptions`: {near_miss: count}
- **Logs**: [EXIT_WINNER] shows which branch fired + why
- **Dashboard**: [V10.13m EXIT_AUDIT] displays top rejections

**Current Mix (Post-V10.13k):**
- scratch=6-8 (now visible, was 0)
- micro=1-2
- timeout_flat=35-40 (dominant, target for V10.13n)
- timeout_profit=4-5
- timeout_loss=6-7

**V10.13n Target:**
- Reduce timeout_flat dominance through evidence-based threshold tuning

---

## 4. STATE MANAGEMENT

### Hybrid Persistence Model

**Firestore (Source of Truth):**
```
/trades/{trade_id}
  - entry_price, exit_price, pnl_pct
  - entry_signal, exit_type, timestamp
  - position_size, tp, sl

/system/stats
  - total_wins, total_losses, win_rate
  - gross_profit, gross_loss, profit_factor
```

**Redis (Real-Time Cache):**
```
LM_STATE = {
  "win_rate": 0.554,
  "profit_factor": 1.53,
  "convergence": 0.0062,
  "health": 0.45,
  "regime": "BEAR_TREND"
}
```

**Cold Start (On Boot):**
1. Try Redis hydration
2. If Redis unavailable → Bootstrap from Firestore (last 100 trades)
3. Rebuild LM_STATE from trade history

---

## 5. CONTROL LOOPS

### Loop A: Calibration Loop
```
Trade closes → learning_event updates win/total in bucket
              → Calibrator remaps raw_confidence → empirical_win_prob
              → Next signal uses updated calibration
```

**Result:** System self-corrects bias over time

### Loop B: Performance Loop
```
Every 50 trades → Health calculated (convergence + edge)
                → Health < 0.10 → Crisis mode (tighten gates)
                → Health > 0.50 → Normal mode (standard gates)
```

**Result:** Dynamic risk management

### Loop C: Risk Loop (V10.13L)
```
Critical module error → runtime_fault_registry.mark_fault()
                     → is_trading_allowed() = False
                     → trade_executor fails-closed (no new trades)
                     → self_heal pauses (doesn't mask errors)
```

**Result:** Fail-closed safety (break, don't mask)

---

## 6. RUNTIME ORCHESTRATION (bot2/main.py)

**Start Sequence:**
1. Load config + Firestore secrets
2. Bootstrap learning state (Redis → Firestore)
3. Initialize exchange connection (Binance)
4. Start market_stream (WebSocket)
5. Start event_bus listener
6. Start execution pipeline

**Main Loop (10s ticks):**
```python
while True:
  collect_market_data()       # 1000ms
  evaluate_all_open_positions() # Check exits
  check_entry_signals()       # EV gating
  update_metrics()            # Learning
  display_dashboard()         # Live feedback
  sleep(10)
```

**Dashboard Sections:**
- Live prices (BTC, ETH, ADA, BNB, DOT, SOL, XRP)
- Open positions (entry, current P&L, TP/SL targets)
- Performance (winrate, profit factor, drawdown)
- Learning state (health, convergence, regime)
- Safety state (V10.13L) — only shows if NOT OK
- Exit audit (V10.13m) — winners + rejections

---

## 7. DEPLOYMENT TOPOLOGY

```
┌─────────────────────────────────────────┐
│ Hetzner VPS (CX21, 2 vCPU, 4GB RAM)    │
│ OS: Ubuntu 24.04                         │
│ Python: 3.12                             │
├─────────────────────────────────────────┤
│ /opt/cryptomaster/                      │
│  ├─ venv/ (Python environment)           │
│  ├─ src/                                 │
│  │  ├─ services/ (40+ modules)          │
│  │  ├─ core/ (utilities)                │
│  │  └─ tests/                           │
│  ├─ bot2/main.py (orchestrator)         │
│  ├─ start.py (entry point)              │
│  └─ requirements.txt                    │
├─────────────────────────────────────────┤
│ Systemd Service: cryptomaster.service   │
│  - Restart policy: always               │
│  - User: cryptomaster (non-root)       │
│  - Logs: journalctl -u cryptomaster    │
├─────────────────────────────────────────┤
│ Connections:                             │
│  → Binance API (WSS + REST)             │
│  → Firestore (trades, stats, learning)  │
│  → Redis (in-memory cache)              │
│  → GitHub (auto-deploy on push)         │
└─────────────────────────────────────────┘
```

**CI/CD Pipeline:**
- **Pre-Live Audit Gate** (audit.yml): Daily validation
- **Deploy to Hetzner** (deploy.yml): Auto-deploy on `git push main`
- **Signal System** (cron.yml): REMOVED (V10.13m cleanup)

---

## 8. KEY INVARIANTS

| Invariant | Value | Rationale |
|-----------|-------|-----------|
| Max open positions | 7 (one per symbol) | Concentration limit |
| Position size range | 0.5% - 5% of capital | Risk control |
| TP/SL ratio (RR) | 1.25 | Risk:Reward balance |
| EV entry gate | ≥ 0.100 | Positive expectancy only |
| Timeout window | 120-300s | Capital efficiency |
| Drawdown halt | ≥ 45% | Catastrophic stop |
| Max loss streak | 3 consecutive | Circuit breaker |
| Calibration minimum | ≥ 30 trades/bucket | Sample size for credibility |

---

## 9. FAILURE MODES & RECOVERY

| Failure | Detection | Response |
|---------|-----------|----------|
| Market crash | Drawdown ≥ 45% | HALT (failsafe_halt) |
| Stalled signals | No signals 900s | STALL anomaly → self_heal |
| High drawdown | DD > 35% | Reduce risk_multiplier to 30% |
| Smart exit error | Exception | mark_fault() → fail-closed gate |
| Redis unavailable | Connection timeout | Fallback to Firestore hydration |
| Binance disconnect | WSS close | Exponential backoff reconnect |
| Corrupt state | Inconsistent metrics | Dashboard alerts + manual review |

---

## 10. MONITORING & OBSERVABILITY

### Real-Time Signals (Dashboard)
- Live P&L, position count, open risk
- Win rate vs target (55%)
- Profit Factor vs target (>1.5)
- Regime classification + feature weights

### Audit Trail (V10.13m)
- Exit audit summary: winners + rejections + near-misses
- Enables evidence-based tuning (V10.13n)

### Logs (journalctl)
- DEBUG: branch evaluation details (if EXIT_AUDIT_DEBUG=1)
- INFO: exits, trades, anomalies
- WARNING: faults, breaches, degradation
- ERROR: crashes, halts

### Metrics (Firestore)
- Daily aggregates: trades, win rate, P&L, max drawdown
- Per-symbol tracking: WR by regime, edge by pair
- Correlation matrix: live correlation updates

---

## 11. CONFIGURATION & TUNING

See: **BOT_PARAMETERS_REFERENCE.md**

Key parameters:
- Exit thresholds: SCRATCH_MAX_PNL, MICRO_TP_BASE, TRAILING_ACTIVATION_BASE
- Entry gates: EV_THRESHOLD, MIN_SAMPLE_SIZE
- Risk: MAX_POSITION_SIZE, RISK_MULTIPLIER
- Learning: CONVERGENCE_WINDOW, HEALTH_THRESHOLD

---

## 12. ROADMAP

| Version | Focus | Status |
|---------|-------|--------|
| V10.13k | Smart exit case fix + regime adaptive TP | ✅ Live |
| V10.13L | Runtime safety (fail-closed gates) | ✅ Live |
| V10.13m | Exit attribution audit (observability) | ✅ Live (collecting data) |
| V10.13n | Evidence-based exit tuning | 📊 Pending data analysis |
| V10.14 | Adaptive entry thresholds | Planned |
| V10.15 | Multi-timeframe signal fusion | Planned |

---

**Document Version:** 1.0  
**Last Sync:** 2026-04-17 10:15 UTC  
**Next Review:** After V10.13m audit (2 hours)
