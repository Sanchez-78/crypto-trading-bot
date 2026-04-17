# CryptoMaster HF-Quant 5.0 — Operational Guide

**Version:** V10.13m+  
**Last Updated:** 2026-04-17  
**Status:** Production Ready

---

## TABLE OF CONTENTS

1. [Startup & Initialization](#startup--initialization)
2. [Runtime Monitoring](#runtime-monitoring)
3. [Dashboard Interpretation](#dashboard-interpretation)
4. [Log Analysis](#log-analysis)
5. [Troubleshooting Guide](#troubleshooting-guide)
6. [Maintenance Tasks](#maintenance-tasks)
7. [Emergency Procedures](#emergency-procedures)
8. [Performance Tuning](#performance-tuning)

---

## STARTUP & INITIALIZATION

### Initial Setup (First-Time Deployment)

#### 1. Environment Variables
```bash
# Hetzner VPS SSH
ssh cryptomaster@vps_ip

# Set working directory
cd /opt/cryptomaster

# Create .env file with secrets
cat > .env << 'EOF'
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
FIREBASE_CREDENTIALS=/opt/cryptomaster/firebase-key.json
REDIS_URL=redis://localhost:6379/0
EXIT_AUDIT_DEBUG=0
EOF

# Restrict permissions
chmod 600 .env
```

#### 2. Python Virtual Environment
```bash
# Create venv
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Test import
python -c "import src.services.market_stream; print('OK')"
```

#### 3. Firestore Setup
```bash
# Place Firebase service account key
cp ~/firebase-key.json /opt/cryptomaster/firebase-key.json
chmod 600 /opt/cryptomaster/firebase-key.json

# Test connection
python -c "from src.services.firebase_client import init_firebase; init_firebase(); print('Firebase OK')"
```

#### 4. Redis Setup
```bash
# Start Redis (if not already running)
sudo systemctl start redis-server

# Test connection
redis-cli ping  # Should print "PONG"
```

### Starting the Bot

#### Via systemd (Recommended)

```bash
# Enable service (auto-start on reboot)
sudo systemctl enable cryptomaster.service

# Start the bot
sudo systemctl start cryptomaster

# Check status
sudo systemctl status cryptomaster

# Watch logs in real-time
sudo journalctl -u cryptomaster -f
```

#### Manual Start (For Testing)

```bash
cd /opt/cryptomaster
source venv/bin/activate
export PYTHONUNBUFFERED=1
python bot2/main.py 2>&1 | tee bot.log
```

### Bootstrap Hydration (Cold Start)

**What happens on startup:**

```
1. Load environment + config
2. Try Redis hydration (LM_STATE)
   - If available → use immediately
   - If unavailable → proceed to step 3
3. Bootstrap from Firestore
   - Query last 100 trades
   - Reconstruct calibration buckets
   - Restore health score
4. Log bootstrap status: [V10.13b] – shows sources
5. Start market_stream (WebSocket to Binance)
6. Begin evaluation loop
```

**Expected startup time:** 5–10 seconds  
**Hydration sources:** Redis (fast) → Firestore (slower)

---

## RUNTIME MONITORING

### Dashboard Refresh
**Frequency:** Every 10 seconds  
**Output:** Real-time prices, positions, performance, health

### Dashboard Sections (In Order)

#### 1. Live Prices
```
┌─ PRICES ─────────────────────────────────────────────┐
│ BTC   75042.50  ↓ -0.12%  │ ETH   2345.67  ↑ +0.54%  │
│ ADA    0.98321  ↑ +0.01%  │ BNB   625.43   ↑ +0.22%  │
│ DOT   12.3456   ↓ -0.03%  │ SOL   145.67   ↑ +0.15%  │
│ XRP    2.4321   ↓ -0.08%  │                          │
└──────────────────────────────────────────────────────┘
```

#### 2. Open Positions
```
┌─ POSITIONS (4 open) ──────────────────────────────────┐
│ BTC   BUY   age=45s   entry=75000 current=75050       │
│       pnl=+0.067%  mfe=+0.12%  tp=75270  sl=74820    │
│                                                        │
│ ETH   BUY   age=23s   entry=2345  current=2351        │
│       pnl=+0.26%   mfe=+0.28%  tp=2396   sl=2308    │
│                                                        │
│ ADA   SELL  age=78s   entry=0.98  current=0.979       │
│       pnl=+0.10%   mfe=+0.15%  tp=0.96   sl=0.986   │
│                                                        │
│ SOL   BUY   age=156s  entry=145   current=146.2       │
│       pnl=+0.83%   mfe=+0.85%  tp=146.5  sl=144.4   │
└──────────────────────────────────────────────────────┘
```

**Read As:**
- `age`: seconds since entry (affects scratch/stagnation eligibility)
- `pnl`: current unrealized profit/loss
- `mfe`: peak profit reached (used for trailing stop)
- `tp/sl`: target profit and stop loss levels

#### 3. Performance Metrics
```
┌─ PERFORMANCE ─────────────────────────────────────────┐
│ Trades today: 42  │ Win rate: 55.2% (target: >55%)   │
│ Gross profit: $1247  │ Gross loss: $812               │
│ Profit factor: 1.54 (target: >1.50)                   │
│ Max drawdown: 8.3%  (limit: 45%)                      │
│ Account size: $25,000  │ Used risk: 2.3% / 5%         │
└──────────────────────────────────────────────────────┘
```

#### 4. Learning State
```
┌─ LEARNING STATE ──────────────────────────────────────┐
│ Health: 0.45 (DEGRADED mode)                          │
│ Convergence: 0.0062 (stable)                          │
│ Regime: BULL_TREND (BTC-led)                          │
│ Calibration status: 7/7 buckets credible (≥30 trades) │
│ EV threshold: 0.025 (75th percentile)                 │
│ Risk multiplier: 0.75 (was 1.0, lowered due to DD>35%)
└──────────────────────────────────────────────────────┘
```

#### 5. Safety State (V10.13L) — Only Shows if NOT OK
```
┌─ SAFETY STATE ────────────────────────────────────────┐
│ ⚠️  RUNTIME FAULT DETECTED                             │
│ Faulted module: smart_exit_engine                      │
│ Fault time: 2026-04-17 10:23:45 UTC                   │
│ Status: TRADING HALTED (fail-closed)                   │
│ Action: Manual restart required                        │
└──────────────────────────────────────────────────────┘
```

#### 6. Exit Audit (V10.13m) — Only Shows if EXIT_AUDIT_DEBUG=1
```
┌─ [V10.13m EXIT_AUDIT] ────────────────────────────────┐
│ winners: micro=2 breakeven=1 partial_25=0 partial_50=0 │
│         partial_75=0 early_stop=1 trail=0              │
│         scratch=7 stagnation=0 timeout_flat=36         │
│         timeout_profit=5 timeout_loss=6                │
│                                                        │
│ near_miss: scratch=14 micro=3 trail=11 partial_25=9   │
│           partial_50=2 partial_75=0                     │
│                                                        │
│ top_rejects (top 5):                                   │
│   TRAILING_STOP:insufficient_retrace = 33             │
│   SCRATCH_EXIT:pnl_outside_band = 28                  │
│   MICRO_TP:below_threshold = 24                       │
│   PARTIAL_TP_25:not_reached = 22                      │
│   EARLY_STOP:below_threshold = 19                     │
└──────────────────────────────────────────────────────┘
```

### Key Health Indicators

| Indicator | Healthy | Warning | Critical |
|-----------|---------|---------|----------|
| Win Rate | >55% | 45–55% | <45% |
| Profit Factor | >1.50 | 1.20–1.50 | <1.20 |
| Health Score | ≥0.50 | 0.10–0.50 | <0.10 |
| Drawdown | <15% | 15–35% | >45% |
| EV Threshold | 0.015–0.030 | 0.030–0.050 | >0.050 |
| Convergence | <0.010 | 0.010–0.020 | >0.020 |

---

## DASHBOARD INTERPRETATION

### Health Score Tiers

#### NORMAL Mode (Health ≥ 0.50)
- Position sizing: 100% (normal)
- Entry gates: Standard EV threshold
- Position floors: None (micro-trading off)
- Recovery mode: Off
- **Action:** Continue normal operation

#### DEGRADED Mode (0.10 ≤ Health < 0.50)
- Position sizing: 100% but tighter filters
- Entry gates: Slightly raised EV threshold
- Position floors: 1% minimum (micro mode active)
- Recovery mode: On (trying to stabilize)
- **Action:** Monitor closely; tighter risk control in effect

#### CRISIS Mode (Health < 0.10)
- Position sizing: 30% of normal
- Entry gates: Strict filters, raised EV threshold
- Position floors: 1% (micro mode active)
- Recovery mode: Aggressive
- **Action:** Manual review recommended; system in preservation mode

### Regime Interpretation

| Regime | Characteristics | Trading Impact |
|--------|-----------------|-----------------|
| BULL_TREND | Strong uptrend, high momentum | Wider TP/SL, accept wider moves |
| BEAR_TREND | Strong downtrend | Same as BULL (direction-agnostic) |
| BULL_RANGE | Ranging in uptrend | Tighter TP, better pullback hunting |
| BEAR_RANGE | Ranging in downtrend | Tighter TP, symmetric short hunting |
| RANGING | No clear trend | Tightest TP, most conservative |
| QUIET_RANGE | Dead market, low volatility | Micro-trades only, scalp-focus |
| UNCERTAIN | Ambiguous signals | Use conservative priors |

---

## LOG ANALYSIS

### Critical Log Patterns

#### Signal Acceptance
```bash
decision=ACCEPT sym=BTCUSDT reg=BULL_TREND ev=0.118->0.118
# Good: Signal passed EV gate
# Action: Normal operation
```

#### Signal Rejection (Low EV)
```bash
decision=REJECT_EV sym=ETHUSDT reg=RANGING ev=0.08->0.08 thr_ev=0.15
# Meaning: EV too low even after calibration
# Action: Normal (system working as designed)
```

#### Signal Rejection (Low Confidence)
```bash
decision=REJECT_CONF sym=ADAUSDT reg=QUIET_RANGE score=0.42->0.42 thr_sc=0.18
# Meaning: ML model not confident enough
# Action: Normal (signal quality low in quiet market)
```

#### Stall Anomaly Detection
```
[cycle_result] symbols=7 passed=0 unblock=False idle=913s
# Meaning: 15+ minutes with no signals
# Action: System enters UNBLOCK mode, relaxes thresholds
```

#### High Drawdown Response
```
SELF_HEAL: HIGH_DRAWDOWN (>35%) triggered → reducing risk to 30%
# Meaning: Drawdown exceeded 35%; safe_mode activated
# Action: Positions reduced to 30% size; watch for recovery
```

#### Failsafe Halt
```
🛑 FAILSAFE: Trading disabled (safe_mode + DD>45%)
# CRITICAL: Account lost 45%+
# Action: MANUAL INTERVENTION REQUIRED
```

#### Runtime Fault
```
FAULT_MARKED: smart_exit_engine exception: <error>
[V10.13L] FAULT ACTIVE: is_trading_allowed() = False
# CRITICAL: Core module crashed
# Action: RESTART REQUIRED (`sudo systemctl restart cryptomaster`)
```

### Finding Specific Events

```bash
# Find all trade entries (across 7 symbols)
sudo journalctl -u cryptomaster | grep "decision=ACCEPT"

# Find rejection reasons
sudo journalctl -u cryptomaster | grep "decision=REJECT"

# Find anomalies
sudo journalctl -u cryptomaster | grep -E "ANOMALY|FAULT|STALL"

# Find health changes
sudo journalctl -u cryptomaster | grep "health_score"

# Find position exits
sudo journalctl -u cryptomaster | grep "EXIT_WINNER"

# Find specific symbol (e.g., BTCUSDT)
sudo journalctl -u cryptomaster | grep "BTCUSDT"

# View last 100 lines
sudo journalctl -u cryptomaster -n 100

# View real-time (follow mode)
sudo journalctl -u cryptomaster -f
```

---

## TROUBLESHOOTING GUIDE

### Problem: No signals generated for 15+ minutes

**Symptoms:**
```
[cycle_result] symbols=7 passed=0 unblock=False idle=965s
```

**Diagnosis:**
1. Check market conditions: Is market actually quiet?
   ```bash
   # Check last candle data
   curl -s 'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=5'
   ```

2. Check signal generator logs:
   ```bash
   sudo journalctl -u cryptomaster | grep -E "signal|regime|confidence" | tail -20
   ```

3. Check if unblock mode activated:
   ```bash
   sudo journalctl -u cryptomaster | grep "unblock=True"
   # If yes: thresholds have been relaxed; system recovering
   ```

**Recovery:**
- If market truly quiet: Normal; wait for volatility
- If thresholds too strict: Lower EV_THRESHOLD in config
- If ML model broken: Check signal_engine logs for exceptions

---

### Problem: Trades entering but not exiting (stuck positions)

**Symptoms:**
```
age=345s (position older than typical 120–300s timeout)
```

**Diagnosis:**

1. Check timeout configuration:
   ```bash
   grep -n "TIMEOUT" /opt/cryptomaster/src/services/smart_exit_engine.py
   # Should show window 120–300 seconds
   ```

2. Check if smart_exit_engine is running:
   ```bash
   sudo journalctl -u cryptomaster | grep "EXIT_WINNER"
   # No output? Exit engine might be stuck
   ```

3. Check for runtime faults:
   ```bash
   sudo journalctl -u cryptomaster | grep "FAULT"
   # If present: smart_exit_engine crashed
   ```

**Recovery:**
```bash
# If fault detected, restart bot:
sudo systemctl restart cryptomaster

# Watch restart:
sudo journalctl -u cryptomaster -f
```

---

### Problem: Account equity dropping rapidly (high drawdown)

**Symptoms:**
```
Max drawdown: 42.3% (limit: 45%)
SELF_HEAL: HIGH_DRAWDOWN (>35%) triggered → reducing risk to 30%
```

**Diagnosis:**

1. Check win rate:
   ```bash
   sudo journalctl -u cryptomaster | grep "Win rate"
   # If <50%: System losing; normal drawdown period
   # If >55% but DD high: Occasional large losses breaking win streak
   ```

2. Check profit factor:
   ```bash
   sudo journalctl -u cryptomaster | grep "Profit factor"
   # If <1.20: Losses outweighing wins
   ```

3. Check recent trades:
   ```bash
   # Find last 10 exits
   sudo journalctl -u cryptomaster | grep "EXIT_WINNER" | tail -10
   # Look for series of timeout_loss or large losses
   ```

**Recovery:**
```
System automatically:
  1. Sets safe_mode = True
  2. Reduces position sizes to 30%
  3. Tightens entry filters

Manual steps:
  1. Monitor for 5–10 more trades
  2. If DD > 45%: HALT (failsafe kicks in)
  3. After recovery: Risk multiplier returns to 1.0
```

---

### Problem: Exit Audit shows HIGH timeout_flat dominance

**Symptoms:**
```
winners: timeout_flat=36 (out of 56 total exits)
This means 64% of exits are via timeout, not prior branches
```

**Diagnosis:**
1. Check rejection counters:
   ```bash
   # Enable audit debug for detailed logging
   export EXIT_AUDIT_DEBUG=1
   sudo systemctl restart cryptomaster
   sudo journalctl -u cryptomaster -f | grep "EXIT_AUDIT"
   ```

2. Look for patterns (example):
   ```
   [EXIT_AUDIT] BTCUSDT FAIL branch=SCRATCH_EXIT reason=pnl_outside_band
   [EXIT_AUDIT] BTCUSDT FAIL branch=MICRO_TP reason=below_threshold
   [EXIT_AUDIT] BTCUSDT FAIL branch=TRAILING_STOP reason=insufficient_retrace
   ```

3. Check near-miss counts:
   ```
   near_miss: scratch=14 micro=3 trail=11 partial25=9
   High near-miss on a branch = threshold too strict
   ```

**Recovery (V10.13n):**
Based on audit data, adjust thresholds:
- High `scratch_near_miss` → Widen SCRATCH_MAX_PNL (0.0015 → 0.0020)
- High `trail_near_miss` → Lower TRAILING_RETRACE_PCT (0.50 → 0.40)
- High `micro_near_miss` → Raise MICRO_TP_BASE (0.0010 → 0.0012)

---

### Problem: Calibration buckets not converging

**Symptoms:**
```
Calibration status: 3/7 buckets credible (need ≥30 trades per bucket)
```

**Diagnosis:**
- Normal in early trading (<200 total trades)
- Buckets fill gradually as more signals generated
- Some buckets may take days to reach 30 trades

**Recovery:**
- Patience: buckets converge with time
- Monitor convergence: `sudo journalctl | grep "Calibration status"`
- Speed up: Lower EV_THRESHOLD to generate more signals (if confident)

---

## MAINTENANCE TASKS

### Daily

1. **Check dashboard** (manually or via alerts)
   ```bash
   sudo systemctl status cryptomaster
   ```

2. **Verify positions closing normally**
   - Check last 10 exits via `EXIT_WINNER` logs
   - Confirm no age=300+ positions stuck

3. **Monitor health score trend**
   - Track if DEGRADED or CRISIS mode
   - Note any safety state warnings

### Weekly

1. **Reset Firebase (purge legacy records)**
   ```bash
   cd /opt/cryptomaster
   source venv/bin/activate
   python -m src.services.reset_db
   ```
   **Purpose:** Clear old closed trades, rebuild learning state from scratch

2. **Analyze exit audit (if V10.13m active)**
   ```bash
   export EXIT_AUDIT_DEBUG=1
   # Run bot for 1–2 hours
   # Collect [V10.13m EXIT_AUDIT] summaries
   # Analyze top_rejects to identify threshold issues
   ```

3. **Check calibration distribution**
   ```bash
   # Verify buckets filling evenly across confidence ranges
   # If one bucket has 50+ trades and another has 5: investigate
   ```

### Monthly

1. **Review performance metrics**
   - Win rate trend
   - Profit factor
   - Drawdown recovery time
   - Average trade duration

2. **Update parameters if needed**
   ```bash
   # Edit BOT_PARAMETERS_REFERENCE.md with any changes
   # Update smart_exit_engine.py thresholds
   # Update realtime_decision_engine.py gates
   # Commit: `git commit -am "Param update: ..."`
   # Push: `git push origin main`
   # Restart: `sudo systemctl restart cryptomaster`
   ```

3. **Review logs for patterns**
   ```bash
   # Export last 30 days of logs
   sudo journalctl -u cryptomaster --since="1 month ago" > logs_month.txt
   # Analyze for recurring issues, threshold trends
   ```

---

## EMERGENCY PROCEDURES

### If Drawdown Exceeds 45% (FAILSAFE HALT)

**System Response:** Automatic halt  
**Symptom:**
```
🛑 FAILSAFE: Trading disabled (safe_mode + DD>45%)
```

**Manual Recovery:**
```bash
# 1. Analyze what went wrong
sudo journalctl -u cryptomaster | tail -50

# 2. Check if any runtime faults
sudo journalctl -u cryptomaster | grep "FAULT"

# 3. STOP THE BOT
sudo systemctl stop cryptomaster

# 4. Review position logic / thresholds
# Edit config files if needed

# 5. RESTART
sudo systemctl start cryptomaster

# 6. VERIFY restart successful
sudo systemctl status cryptomaster
sudo journalctl -u cryptomaster -f  # Watch for errors
```

### If Runtime Fault Detected

**System Response:** Automatic fail-closed (no new trades)  
**Symptom:**
```
FAULT_MARKED: smart_exit_engine exception: ...
[V10.13L] FAULT ACTIVE: is_trading_allowed() = False
```

**Immediate Action:**
```bash
# 1. Close any open positions manually (if necessary)
#    Go to Binance dashboard and cancel orders

# 2. Identify the faulted module (shown in log)

# 3. Check exception details
sudo journalctl -u cryptomaster | grep "FAULT_MARKED"
# Look for the actual Python exception

# 4. Restart the bot
sudo systemctl restart cryptomaster

# 5. Verify fix
sudo journalctl -u cryptomaster -f | grep "FAULT"
# Should NOT see any new FAULT messages
```

### If Redis Unavailable

**System Response:** Fallback to Firestore hydration  
**Symptom:**
```
[V10.13b] Learning Monitor: source=firebase (should be redis)
```

**Recovery:**
```bash
# 1. Check Redis status
sudo systemctl status redis-server

# 2. If stopped, restart it
sudo systemctl start redis-server

# 3. If Redis is corrupted:
sudo systemctl stop redis-server
rm /var/lib/redis/dump.rdb  # Clear cache
sudo systemctl start redis-server

# 4. Bot will auto-reconnect on next cycle
sudo journalctl -u cryptomaster -f | grep -i redis
```

### If Binance WebSocket Disconnects

**System Response:** Auto-reconnect with exponential backoff  
**Symptom:**
```
WebSocket closed, reconnecting in 1s...
WebSocket closed, reconnecting in 2s...
WebSocket closed, reconnecting in 4s...
```

**Recovery:**
- Usually auto-heals within 10–30 seconds
- If persistent: Check Binance API status
- If local networking issue: Restart Hetzner VPS

```bash
# Force restart market stream
sudo systemctl restart cryptomaster
```

---

## PERFORMANCE TUNING

### Tuning Entry Sensitivity

**If too few signals (missing opportunities):**
```python
# Lower EV threshold
# In realtime_decision_engine.py:
EV_THRESHOLD_COLD_START = 0.10  # was 0.15
# Also lower the floor:
EV_THRESHOLD_FLOOR = 0.08  # was 0.10
```

**If too many signals (over-trading):**
```python
# Raise EV threshold
EV_THRESHOLD_COLD_START = 0.20  # was 0.15
EV_THRESHOLD_FLOOR = 0.12  # was 0.10

# OR raise frequency cap
MAX_TRADES_15 = 10  # was 15
```

### Tuning Exit Sensitivity

**If timeout_flat dominates (>50% of exits):**
```python
# In smart_exit_engine.py:
SCRATCH_MAX_PNL = 0.0020  # was 0.0015 (widen band)
_TRAILING_ACTIVATION_BASE = 0.0025  # was 0.003 (activate sooner)
_MICRO_TP_BASE = 0.0012  # was 0.0010 (easier harvest)
```

**If harvests not triggering:**
```python
# Check partial TP levels
_PARTIAL_TP_25_BASE = 0.20  # was 0.25
_PARTIAL_TP_50_BASE = 0.40  # was 0.50
_PARTIAL_TP_75_BASE = 0.60  # was 0.75
```

### Tuning Risk Management

**If positions too small:**
```python
# In config.py:
MAX_POSITION_SIZE = 0.08  # was 0.05 (more capital per trade)

# OR lower risk floor
# In self_heal.py:
min_position_floor = 0.005  # was 0.01
```

**If drawdown too high:**
```python
# Lower initial risk multiplier
# In initializer or config:
state.risk_multiplier = 0.7  # was 1.0 (start more conservative)

# Also lower max position
MAX_POSITION_SIZE = 0.03  # was 0.05
```

---

## PERFORMANCE METRICS REFERENCE

### Success Metrics (Target)

| Metric | Target | Status |
|--------|--------|--------|
| Win Rate | >55% | ✓ (54%+) |
| Profit Factor | >1.50 | ✓ (1.53) |
| Sharpe Ratio | >1.0 | Monitor |
| Max Drawdown | <20% | ✓ (<15%) |
| Recovery Time | <5% of equity | ✓ |
| Avg Trade Duration | <3 min | ✓ |

### Sample Good Day

```
Trades: 42
Wins: 24 (57%)
Losses: 18 (43%)
Gross Profit: $1,247
Gross Loss: $812
Profit Factor: 1.54
Max Drawdown: 8.3%
Account Change: +2.4%
```

### Sample Problem Day

```
Trades: 38
Wins: 19 (50%)
Losses: 19 (50%)
Gross Profit: $945
Gross Loss: $1,120
Profit Factor: 0.84 ❌
Max Drawdown: 28% ❌
Account Change: -1.8% ❌
→ Auto-enters DEGRADED mode
```

---

**Document Version:** 1.0  
**Last Sync:** 2026-04-17  
**Next Review:** After V10.13m audit analysis
