# CryptoMaster HF-Quant 5.0 — Decision Rules & EV Engine

**Version:** V10.13m+  
**Last Updated:** 2026-04-17  
**Status:** Production (Adaptive Calibration Active)

---

## TABLE OF CONTENTS

1. [EV-Only Principle](#ev-only-principle)
2. [Bayesian Calibration](#bayesian-calibration)
3. [EV Calculation & Gating](#ev-calculation--gating)
4. [Entry Decision Flow](#entry-decision-flow)
5. [Adaptive Thresholds](#adaptive-thresholds)
6. [Learning Loops](#learning-loops)
7. [Anomaly Detection & Recovery](#anomaly-detection--recovery)
8. [Decision Logging & Diagnostics](#decision-logging--diagnostics)

---

## EV-ONLY PRINCIPLE

### Core Concept

**The bot trades ONLY when mathematical expected value is positive.**

This is the fundamental gate through which all signals must pass. No amount of "good vibes," sentiment, or macro context overrides this rule.

### Formula

```
EV = (Win Probability × Risk-Reward Ratio) - (1 - Win Probability)
```

**Breaking it down:**

```
EV = P(win) × RR - (1 - P(win))
   = P(win) × RR - P(loss)
```

**Example (RR = 1.25):**
```
If P(win) = 0.60:
  EV = 0.60 × 1.25 - 0.40
  EV = 0.75 - 0.40 = +0.35
  ✓ Trade (expect +0.35 per unit risk)

If P(win) = 0.55:
  EV = 0.55 × 1.25 - 0.45
  EV = 0.6875 - 0.45 = +0.2375
  ✓ Trade (expect +0.24 per unit risk)

If P(win) = 0.52:
  EV = 0.52 × 1.25 - 0.48
  EV = 0.65 - 0.48 = +0.17
  ✓ Trade (barely positive)

If P(win) = 0.50:
  EV = 0.50 × 1.25 - 0.50
  EV = 0.625 - 0.50 = +0.125
  ✓ Trade (minimum edge: +0.125)

If P(win) = 0.48:
  EV = 0.48 × 1.25 - 0.52
  EV = 0.60 - 0.52 = +0.08
  ✓ Trade (narrow but positive)

If P(win) = 0.45:
  EV = 0.45 × 1.25 - 0.55
  EV = 0.5625 - 0.55 = +0.0125
  ✓ Trade (minimal edge)

If P(win) = 0.44:
  EV = 0.44 × 1.25 - 0.56
  EV = 0.55 - 0.56 = -0.05
  ✗ DO NOT TRADE (negative EV)
```

### EV Threshold Logic

**Adaptive EV Threshold:**
- **Cold Start (first 100 samples):** EV ≥ 0.15
- **Online:** EV ≥ 75th percentile of last 50 EVs
- **Absolute Floor:** EV ≥ 0.10 (never trade with EV < 0.10)

**Rationale:**
- Cold start is conservative: only take high-confidence signals
- Adaptive learns signal difficulty: if environment produces EV ≥ 0.20 consistently, lower bar to 0.20
- Floor prevents zero-edge trading even in noise periods

### Risk-Reward Ratio (RR)

**Standard:** `RR = 1.25` (1:1.25 risk-reward)  
**Formula:** `TP = entry + (ATR × regime_multiplier)`  
**Never Trades:** If RR < 1.25 (would require >80% win rate to profit)

---

## BAYESIAN CALIBRATION

### Purpose

Raw ML model confidence (0.0–1.0) is **miscalibrated** — actual win rate doesn't match predicted confidence.

**Example:**
```
Model says: "This signal is 70% confident"
Reality after 100 trades: Only 52% actually win
```

**Calibration maps raw confidence → empirical win probability.**

### Bucketing System

**Confidence Ranges:**
```
Bucket  Range    Center
------  ------   ------
  0     0.45–0.55  0.50
  1     0.55–0.65  0.60
  2     0.65–0.75  0.70
  3     0.75–0.85  0.80
  4     0.85–0.95  0.90
  5     0.95–1.00  0.95+
```

**Per-Bucket Tracking:**
```python
calibration_buckets = {
    0.50: {"wins": 28, "total": 52},    # 54% actual WR
    0.60: {"wins": 33, "total": 60},    # 55% actual WR
    0.70: {"wins": 41, "total": 65},    # 63% actual WR (good bucket!)
    0.80: {"wins": 18, "total": 24},    # 75% actual WR (excellent!)
    ...
}
```

### Minimum Sample Requirement

**Credibility Threshold:** ≥ 30 trades per bucket  

**Before Threshold:**
- Use conservative prior of 0.50 (honest "I don't know")
- Prevents over-fitting to noise

**After Threshold:**
- Use empirical win rate: wins / total
- Example: bucket 0.70 has 63% actual WR after 65 trades

### Calibration Update Loop

**Sequence (every trade close):**

```
1. Get trade result (win / loss)
2. Find original signal's raw confidence (stored at entry)
3. Find which bucket that confidence falls into
4. Increment bucket's win count (if won) or total count
5. Recalculate empirical win_prob for that bucket
6. Next signal using same raw confidence uses updated bucket
```

**Example:**
```
T=0: Signal enters at 0.68 raw confidence
     → Bucket 0.70 (closest center)
     → Current estimate: 0.50 (prior, only 22 trades in bucket so far)
     → Trade accepted if EV(0.50, 1.25) > threshold

T=45s: Trade closes at +$50 (WIN)
     → Bucket 0.70 incremented: {wins: 23, total: 49}
     → Estimate still 0.50 (< 30 trades)

... 8 more trades close in this bucket ...

T=1800s: 32nd trade closes in bucket 0.70
     → Bucket 0.70 now {wins: 28, total: 32}
     → Empirical WR = 28/32 = 0.875
     → Future 0.68-confidence signals use 0.875, not 0.50

T=2000s: New signal at 0.69 confidence
     → Bucket 0.70 (closest)
     → Current estimate: 0.875
     → Trade evaluated: EV(0.875, 1.25) = 0.875 × 1.25 - 0.125 = 0.96 ✓
```

### Calibration State Persistence

**Storage:** Firebase `/learning/{symbol}/calibration_buckets`  
**Update Frequency:** Every trade close  
**Cold Start:** Load from Firebase, bootstrap from last 100 trades if unavailable  
**Fallback:** Default to 0.50 (conservative)

---

## EV CALCULATION & GATING

### Full EV Evaluation Sequence

```
Signal arrives with raw_confidence = 0.72

Step 1: Look up calibration bucket
  → raw_confidence = 0.72 → nearest bucket = 0.70
  → empirical_win_prob = calibration[0.70].wins / total
  → = 28 / 32 = 0.875

Step 2: Calculate TP and SL based on ATR and regime
  → ATR (20-period) = 450 (BTCUSDT)
  → regime = "BULL_TREND"
  → TP_mult = 0.6, SL_mult = 0.4
  → TP = entry + (450 × 0.6) = entry + 270
  → SL = entry - (450 × 0.4) = entry - 180
  → TP_distance = 270 / entry
  → SL_distance = 180 / entry
  → RR = TP_distance / SL_distance = 270 / 180 = 1.5 ✓ (≥ 1.25)

Step 3: Calculate EV
  → EV = 0.875 × 1.5 - (1 - 0.875)
  → EV = 1.3125 - 0.125
  → EV = 1.1875 ✓ (strong edge)

Step 4: Check EV gate
  → Current EV_THRESHOLD = 0.025 (adaptive)
  → EV = 1.1875 >> 0.025 ✓ PASS

Step 5: Check auxiliary gates
  → Frequency cap: 8 trades in last 15 min < 15 ✓ PASS
  → Volatility minimum: ATR = 450 > 0.1% ✓ PASS
  → Momentum: price ≥ avg(last_3_ticks) ✓ PASS

Signal → APPROVED → Execute trade
```

### EV Spread Guard

**Purpose:** Detect when EV distribution is noise (not signal)

**Mechanism:**
```
Calculate std(ev_history[-50:])  # last 50 EVs
If std < 0.05:
    # All EVs very similar; probably noise
    SKIP signal (too much randomness in the decision process)
```

**Rationale:** If all signals generate EV between 0.18–0.22, system isn't learning; it's just generating random trades with positive EV floor.

---

## ENTRY DECISION FLOW

### Pre-Signal Checks

```
Before even looking at a signal:

1. Is trading enabled?
   → If safe_mode + drawdown > 45% → failsafe_halt = True → NO TRADES

2. Is runtime fault active?
   → If smart_exit_engine or signal_generator crashed → is_trading_allowed = False → NO TRADES

3. Max open positions?
   → If 7 positions already open → Skip (one per symbol max)

4. Are we in unblock mode?
   → If idle > 900s (no trades in 15 min) → Relax thresholds (EV: 0.15→0.025)
```

### Signal Evaluation (Core Loop)

```python
for signal in incoming_signals:
    
    # 1. Calibrate confidence
    bucket = find_nearest_bucket(signal.raw_confidence)
    empirical_win_prob = calibration[bucket].wins / calibration[bucket].total
    
    # 2. Calculate EV
    ev = empirical_win_prob * RR - (1 - empirical_win_prob)
    
    # 3. Check EV gate
    if ev < ev_threshold:
        log_decision("REJECT_EV", symbol, reason=f"ev={ev:.4f} < threshold={ev_threshold:.4f}")
        continue
    
    # 4. Check auxiliary gates
    if not passes_frequency_cap(symbol):
        continue
    if not passes_volatility_minimum(symbol):
        continue
    if not passes_momentum_check(symbol):
        continue
    
    # 5. Calculate position size
    risk_budget = account_size * position_size_pct * risk_multiplier
    sl_distance = abs(signal.sl - signal.entry)
    position_size = risk_budget / sl_distance
    
    # 6. Apply safe mode constraints
    if safe_mode:
        position_size *= 0.3  # 30% of normal
        empirical_win_prob *= 0.8  # conservative
    
    # 7. Apply position floor and cap
    position_size = max(position_size, min_position_floor)
    position_size = min(position_size, max_position_size)
    
    # 8. Execute
    trade_executor.place_order(signal, position_size)
```

### Decision Logging

**Decision log per signal:**
```
decision=ACCEPT sym=BTCUSDT reg=BULL_TREND 
ev=0.118->0.118 score=0.72->0.72
thr_ev=0.025 thr_sc=0.18 
timing=1.00 ofi=1.00 cooldown=inf
fallback_considered=False fallback_used=False
size=0.034 reason="ev_gate_passed"
```

---

## ADAPTIVE THRESHOLDS

### EV Threshold Adaptation

**Algorithm (V10.12g+):**

```python
def update_ev_threshold(ev_history):
    """
    Adaptive EV threshold = 75th percentile of last 50 EVs.
    
    Why 75th percentile?
    - Takes only top 25% of signals
    - Adapts to environment difficulty
    - Prevents floor creep in noisy periods
    """
    if len(ev_history) < 100:
        # Cold start: use fixed conservative threshold
        return 0.15
    
    recent_evs = ev_history[-50:]
    p75 = np.percentile(recent_evs, 75)
    
    # Floor: never go below 0.10
    return max(0.10, p75)
```

**Examples:**

| Period | Recent EV Distribution | P75 | Action |
|--------|----------------------|-----|--------|
| Pre-calibration | All: 0.10–0.15 | 0.14 | Use 0.15 (fixed floor) |
| Early-live | 0.10–0.25 | 0.20 | Use 0.20 (adaptive) |
| Converged | 0.15–0.25 | 0.23 | Use 0.23 (tight gate) |
| Noise period | 0.08–0.30 | 0.25 | Use 0.25 (widen to capture) |

### Unblock Mode Thresholds

**Trigger:** Idle ≥ 900 seconds (no trade in 15 minutes)

**Threshold Changes:**
| Parameter | Normal | Unblock |
|-----------|--------|---------|
| EV gate | Current P75 | P75 × 0.6 (lower) |
| Score gate | 0.18 | 0.12 (relax) |
| Exploration factor | 1.0 | 1.5 (boost) |
| Filter strength | 1.0 | 0.9 (soften) |

**Rationale:** If system frozen, aggressively lower bars to restart; can't lose money if not trading.

**Recovery:** Thresholds auto-revert to normal on first successful trade.

---

## LEARNING LOOPS

### Loop A: Calibration Loop (Per-Trade)

```
Trade closes
  ↓
learning_event.track() records result
  ↓
Bucket identified: find nearest confidence center
  ↓
Increment bucket wins (if win) or total (always)
  ↓
Next signal at same confidence uses updated bucket
  ↓
System self-corrects confidence → empirical mapping
```

**Frequency:** Every trade close (synchronous)  
**Impact:** Immediate; next signal sees updated calibration

### Loop B: Performance Loop (Per-50-Trades)

```
After 50 trades close
  ↓
Calculate Health Score:
  - Convergence: std(last 20 EVs)
  - Win rate vs target (55%)
  - Profit factor: gross_profit / gross_loss
  ↓
Health = f(convergence, win_rate, profit_factor)
  ↓
Health ≥ 0.50: NORMAL mode
  0.10 ≤ Health < 0.50: DEGRADED mode
  Health < 0.10: CRISIS mode
  ↓
Adjust parameters:
  DEGRADED: increase filter_strength, lower ev_threshold relaxation
  CRISIS: reduce position_size to 30%, enable safe_mode
```

**Frequency:** Every 50 trades  
**Impact:** Risk multiplier and mode adjustments

### Loop C: Risk Loop (Fault-Driven)

```
Smart exit engine crashes
  ↓
runtime_fault_registry.mark_fault("smart_exit_engine")
  ↓
has_hard_fault() = True
  ↓
is_trading_allowed() = False (fail-closed)
  ↓
No new trades until:
  - Manual intervention (restart)
  - OR automatic 10-minute reset (if enabled)
```

**Frequency:** On error (asynchronous)  
**Impact:** Immediate halt; prevents cascade failures

---

## ANOMALY DETECTION & RECOVERY

### Anomaly Types

| Anomaly | Detection | Response |
|---------|-----------|----------|
| EQUITY_DROP | Account drops unexpectedly | Risk × 50%, Safe mode ON |
| HIGH_DRAWDOWN | DD > 35% | Risk × 30%, Filter ↑ 20% |
| STALL | No signals for 900s | Exploration ↑ 50%, EV ↓ 10% |
| NO_SIGNALS | Pipeline stuck | EV ↓ 20%, Filter ↓ 20% |

### Self-Healing Logic

**V10.13L Update:** If runtime fault active, skip self_heal threshold relaxations.  
**Rationale:** Don't mask critical errors by loosening gates; break instead.

**Example:**
```python
# Old (V10.13k): Auto-relax thresholds on any anomaly
if anomaly == "STALL":
    ev_threshold *= 0.9  # Lower barrier
    
# New (V10.13L): Skip if hard fault
if anomaly == "STALL" and has_hard_fault():
    # Don't relax — let system fail-closed instead
    return
```

### Recovery Sequence

```
Anomaly detected (e.g., HIGH_DRAWDOWN)
  ↓
state.safe_mode = True
state.risk_multiplier = 0.3
  ↓
Next signal applies constraints:
  - position_size *= 0.3
  - confidence *= 0.8
  ↓
Position floor (1% of account) prevents complete freeze
  ↓
Once drawdown recovers or manual reset:
  state.safe_mode = False
  state.risk_multiplier = 1.0
```

---

## DECISION LOGGING & DIAGNOSTICS

### Log Levels

**DEBUG:** Branch evaluation details (only if EXIT_AUDIT_DEBUG=1)  
**INFO:** Entries, exits, anomalies, mode changes  
**WARNING:** Threshold breaches, health warnings, anomalies detected  
**ERROR:** Crashes, halts, runtime faults  
**CRITICAL:** Failsafe halt (drawdown >45% in safe mode)

### Key Decision Log Format (V10.12g)

```
decision={ACCEPT|REJECT} sym={SYMBOL} reg={REGIME} unblock={bool}
ev={raw}->{adj} score={raw}->{adj}
thr_ev={threshold} thr_sc={threshold}
timing={mult} ofi={mult} cooldown={remaining}
fallback_considered={bool} fallback_used={bool}
anti_deadlock={bool} size={mult}
reason={specific_reason}
```

**Example Reject:**
```
decision=REJECT_EV sym=ETHUSDT reg=RANGING unblock=False
ev=0.08->0.08 score=0.55->0.55
thr_ev=0.15 thr_sc=0.18
reason="ev below threshold (0.08 < 0.15)"
```

**Example Accept:**
```
decision=ACCEPT sym=BTCUSDT reg=BULL_TREND unblock=False
ev=0.38->0.38 score=0.74->0.74
thr_ev=0.15 thr_sc=0.18
size=1.00 reason="all_gates_passed"
```

### Cycle-Level Diagnostics

**Every 10 seconds:**
```
[cycle_result] symbols=7 passed=1 unblock=False idle=12.3s redis=available
[idle_seconds] last_trade=12.3s unblock_triggered_at=900s
[health_score] convergence=0.0062 win_rate=0.554 profit_factor=1.53 health=0.45 mode=DEGRADED
```

### Bootstrap Status (V10.13b)

```
[V10.13b] ── Bootstrap Hydration Status ────────────────────────────
  Learning Monitor: source=redis pairs=7
  Metrics:          source=redis trades=1247
  RDE State:        source=firebase ts=1713358800
```

---

## DECISION INVARIANTS

### Never Violated

1. **No negative EV trades**
   ```
   if ev < 0.0:
       REJECT (always, even in crisis mode)
   ```

2. **No position > 5% of account**
   ```
   position_size = min(position_size, 0.05 * account_size)
   ```

3. **No RR < 1.25**
   ```
   if rr < 1.25:
       REJECT (prevent low-payoff bets)
   ```

4. **No trades if 3+ consecutive losses**
   ```
   if loss_streak >= 3:
       halt_trading = True  # Circuit breaker
   ```

5. **No trades if drawdown > 45%**
   ```
   if safe_mode and drawdown > 0.45:
       trading_enabled = False  # Failsafe
   ```

---

**Document Version:** 1.0  
**Last Sync:** 2026-04-17  
**Next Review:** After calibration convergence check
