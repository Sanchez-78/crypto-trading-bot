# CryptoMaster HF-Quant 5.0 — Exit Logic & Decision Hierarchy

**Version:** V10.13m+  
**Last Updated:** 2026-04-17  
**Status:** Production (Exit Attribution Audit Active)

---

## TABLE OF CONTENTS

1. [Exit Hierarchy Overview](#exit-hierarchy-overview)
2. [State Tracking](#state-tracking)
3. [Nine-Level Exit Priority](#nine-level-exit-priority)
4. [Exit Audit Instrumentation (V10.13m)](#exit-audit-instrumentation)
5. [Near-Miss Detection](#near-miss-detection)
6. [Timeout Fallback Logic](#timeout-fallback-logic)
7. [Decision Flow Diagram](#decision-flow-diagram)
8. [State Integrity Checks](#state-integrity-checks)

---

## EXIT HIERARCHY OVERVIEW

The smart exit engine evaluates positions in a **strict 9-level priority order**. The first condition that passes triggers an exit. This multi-tier approach captures profits at multiple scales while protecting capital from large losses.

### Design Philosophy

- **Aggressive profit capture**: MICRO_TP harvests 0.10% (scalp-style wins immediately)
- **Progressive harvest**: PARTIAL_TP_25/50/75 lock profits at milestone levels
- **Risk protection**: EARLY_STOP, TRAILING_STOP cut losses before they grow
- **Capital efficiency**: SCRATCH, STAGNATION, TIMEOUT ensure positions don't stagnate
- **Observability**: V10.13m audit logs explain why branches PASS/FAIL

### Key Invariants

```
- Priority is fixed: no reordering based on regime or market conditions
- Each branch is independent: no cross-branch dependencies
- State is evaluated once per tick: no state mutations between checks
- Thresholds are regime-adaptive: MICRO_TP and TRAILING vary by market structure
- Timeout is the final fallback: positions never hold indefinitely
```

---

## STATE TRACKING

### Position Object State

```python
@dataclass
class Position:
    symbol: str                 # Trading pair (e.g., "BTCUSDT")
    entry_price: float          # Entry price at fill
    tp: float                   # Target profit price
    sl: float                   # Stop loss price
    pnl_pct: float              # Current unrealized P&L as %
    age_seconds: int            # Seconds since entry
    direction: str              # "LONG" (BUY) or "SHORT" (SELL)
    max_favorable_pnl: float    # Peak MFE fraction since entry
    regime: Optional[str]       # Market regime for adaptive thresholds
```

### Critical State Variables

#### pnl_pct (Profit/Loss Percentage)

**Definition:** `(current_price - entry_price) / entry_price` (for LONG)  
**Range:** `-1.0 to +inf` (can exceed +100% in volatile markets)  
**Update Frequency:** Every price tick  
**Used By:** All 9 exit conditions  
**Critical:** If stale or incorrect, entire exit logic fails

**Validation:**
```
- Must be real number (not NaN, Inf)
- Must reflect current market price at evaluation time
- For SHORT: pnl_pct = (entry_price - current_price) / entry_price
```

#### age_seconds (Position Age)

**Definition:** `time.time() - entry_timestamp`  
**Range:** `0 to 300+` (normally exits before 300s)  
**Update Frequency:** Every tick  
**Used By:** SCRATCH (age ≥ 90s), STAGNATION (age ≥ 110s), TIMEOUT (age ≥ 120-300s)  
**Critical:** Drives hard timeout; ensures capital efficiency

**Validation:**
```
- Must be monotonically increasing (time never goes backward)
- Must be non-negative (no negative ages)
- Timestamps must be consistent across evaluations
```

#### max_favorable_pnl (Maximum Favorable Excursion)

**Definition:** Peak P&L since position entry  
**Range:** `0 to +inf`  
**Update Frequency:** Every tick; only increases or stays same, never decreases  
**Used By:** TRAILING_STOP (trailing activation), BREAKEVEN_STOP (trigger validation)  
**Critical:** If not updated correctly, trailing never fires

**Invariant:**
```
max_favorable_pnl >= current_pnl_pct (at all times)
max_favorable_pnl >= 0 (never negative)
```

**Examples:**
```
Entry: BTCUSDT at 75000, current 75050 (+0.067%)
  → max_favorable_pnl = 0.00067

Price retraces to 74980 (-0.027%)
  → max_favorable_pnl stays 0.00067 (unchanged)
  → pnl_pct is now -0.00027
  → Retrace = 1 - (pnl_pct / max_favorable_pnl) = 1.40 (140% retrace)

Price bounces to 75040 (+0.053%)
  → max_favorable_pnl stays 0.00067 (no improvement)
  → Trailing would not fire yet (not at peak)
```

**Setting Rules:**
```
1. Initialize at first tick after entry to current pnl_pct
2. Update: max_favorable_pnl = max(max_favorable_pnl, pnl_pct)
3. Never decrease or reset except on exit
4. Never be negative
```

---

## NINE-LEVEL EXIT PRIORITY

### Level 1: MICRO_TP (Ultra-Tight Profit Harvest)

**Threshold:** Regime-adaptive (0.0006–0.0012, default 0.0010)  
**Trigger Condition:**
```python
if pnl_pct >= threshold and pnl_pct >= 0:
    # MICRO_TP fires
```

**Regime Variants:**
| Regime | Threshold | Rationale |
|--------|-----------|-----------|
| BULL_TREND | 0.0012 | Trends move fast; capture early |
| BEAR_TREND | 0.0012 | Trends move fast |
| BULL_RANGE | 0.0008 | Ranges move slowly; harvest tighter |
| BEAR_RANGE | 0.0008 | Ranges move slowly |
| RANGING | 0.0009 | General range behavior |
| QUIET_RANGE | 0.0006 | Dead market; only take smallest wins |
| UNCERTAIN | 0.0010 | Default if regime unknown |

**Failure Reasons (V10.13m audit):**
- `MICRO_TP:below_threshold` — profit not yet at threshold
- `MICRO_TP:negative_pnl` — position is losing

**Example (BTCUSDT, BULL_TREND):**
```
Entry: 75000, Threshold: 0.0012 (9 pips)
Current: 75009, pnl_pct: 0.00012 (0.12%)
Status: ABOVE threshold → FIRES
Exit Price: 75009 (market order)
```

**Purpose:** Capture scalp-style wins immediately; free capital for next trade

---

### Level 2: BREAKEVEN_STOP (Profit Protection)

**Trigger Level:** 20% of TP move  
**SL Adjustment:** Move to entry price + 1 tick  
**Trigger Condition:**
```python
tp_move = abs(tp - entry_price) / entry_price
tp_progress = pnl_pct / tp_move
if tp_progress >= 0.20 and pnl_pct > 0:
    # Move SL to breakeven, continue holding
```

**Failure Reasons (V10.13m audit):**
- `BREAKEVEN_STOP:non_positive_pnl` — not profitable yet
- `BREAKEVEN_STOP:below_trigger` — below 20% TP progress

**Example (BTCUSDT, target +0.5%):**
```
Entry: 75000, TP: 75375 (0.5% move)
Current: 75107, pnl_pct: 0.14% (28% of TP)
Status: ABOVE 20% → Breakeven protection activates
New SL: 75001 (entry + 1 tick)
Continue: Position held with protected SL
```

**Purpose:** Lock gains early; eliminate downside risk while letting profits run

---

### Level 3–5: PARTIAL_TP (Multi-Level Harvest)

#### Level 3: PARTIAL_TP_25 (First Harvest Milestone)

**Trigger:** 25% of TP move  
**Action:** Exit portion of position (or full position if configured)  
**Failure Reasons:**
- `PARTIAL_TP_25:below_threshold` — below 25% of TP

#### Level 4: PARTIAL_TP_50 (Second Harvest Milestone)

**Trigger:** 50% of TP move  
**Action:** Exit portion of position  
**Failure Reasons:**
- `PARTIAL_TP_50:below_threshold` — below 50% of TP

#### Level 5: PARTIAL_TP_75 (Final Harvest Milestone)

**Trigger:** 75% of TP move  
**Action:** Exit portion of position  
**Failure Reasons:**
- `PARTIAL_TP_75:below_threshold` — below 75% of TP

**Example (Full Progression, ETHUSDT, +1% target):**
```
Entry: 2000
TP: 2020 (1% move)

At 2005 (+0.25%): PARTIAL_TP_25 fires (25% of 1% = 0.25%)
At 2010 (+0.50%): PARTIAL_TP_50 fires (50% of 1% = 0.50%)
At 2015 (+0.75%): PARTIAL_TP_75 fires (75% of 1% = 0.75%)
At 2020: Full TP or timeout fires
```

**Purpose:** Progressively harvest profits; reduce risk as position matures

---

### Level 6: EARLY_STOP (Tight Loss Exit)

**Threshold:** 60% of SL distance  
**Trigger Condition:**
```python
sl_distance = abs(entry_price - sl) / entry_price
loss_pct = abs(pnl_pct)  # negative pnl
if loss_pct >= sl_distance * 0.60 and pnl_pct < 0:
    # EARLY_STOP fires
```

**Failure Reasons (V10.13m audit):**
- `EARLY_STOP:no_loss` — position is profitable (skip this level)
- `EARLY_STOP:below_threshold` — loss below 60% of SL distance

**Example (ADAUSDT, SL at -0.4%):**
```
Entry: 0.50, SL: 0.498 (0.4% loss)
Current: 0.499, pnl_pct: -0.2% (so far)
Threshold: 0.4% × 0.60 = 0.24%
Status: Below threshold → Don't exit yet

Current: 0.497, pnl_pct: -0.6% (exceeds threshold)
Status: ABOVE threshold → EARLY_STOP fires
Exit Price: 0.497
```

**Purpose:** Cut losses early before hitting full SL; better capital allocation

---

### Level 7: TRAILING_STOP (Retracement Exit)

**Activation Threshold:** 0.3% favorable move (regime-adaptive)  
**Minimum Peak:** 0.1% (must have had positive move)  
**Retrace Threshold:** 50% of peak  
**Trigger Condition:**
```python
if max_favorable_pnl >= min_peak_threshold:
    trailing_armed = True
    if max_favorable_pnl >= activation_threshold:
        retrace_pct = 1 - (pnl_pct / max_favorable_pnl)
        if retrace_pct >= 0.50:
            # TRAILING_STOP fires
```

**Regime Variants:**
| Regime | Activation | Rationale |
|--------|------------|-----------|
| BULL_TREND | 0.0035 | Trends armed late; full swings |
| BEAR_TREND | 0.0035 | Trends armed late |
| BULL_RANGE | 0.0025 | Ranges armed early; tight swings |
| BEAR_RANGE | 0.0025 | Ranges armed early |
| RANGING | 0.0025 | General range |
| QUIET_RANGE | 0.0020 | Dead market; immediate activation |
| UNCERTAIN | 0.0030 | Default |

**Failure Reasons (V10.13m audit):**
- `TRAILING_STOP:insufficient_peak` — MFE below activation threshold
- `TRAILING_STOP:insufficient_retrace` — retrace below 50%
- `TRAILING_STOP:not_armed` — (implicit; activation threshold not reached)

**Example (SOLUSDT, BULL_TREND):**
```
Entry: 100, Activation: 0.35%

Tick 1: Current: 100.35 (+0.35%)
  → max_favorable_pnl = 0.0035 ✓ Activation threshold reached
  → Trailing now armed

Tick 2: Current: 100.50 (+0.50%)
  → max_favorable_pnl = 0.0050
  → Trailing still armed, waiting for retrace

Tick 3: Current: 100.25 (+0.25%)
  → pnl_pct = 0.0025
  → retrace = 1 - (0.0025 / 0.0050) = 50% ✓
  → TRAILING_STOP fires

Exit Price: 100.25 (+0.25%)
```

**Purpose:** Lock in gains from momentum moves; exit on reversal

---

### Level 8: SCRATCH_EXIT (Flat Release)

**Minimum Age:** 90 seconds  
**PnL Band:** |pnl| < 0.15%  
**Trigger Condition:**
```python
if age_seconds >= 90 and abs(pnl_pct) < 0.0015:
    # SCRATCH_EXIT fires
```

**Failure Reasons (V10.13m audit):**
- `SCRATCH_EXIT:too_young` — less than 90 seconds old
- `SCRATCH_EXIT:pnl_outside_band` — |pnl| ≥ 0.15%

**Example (BNBUSDT):**
```
Entry: 600 (T=0s), Current: 599.91 (-0.015%)
At T=60s: Age too young → skip
At T=90s: Now old enough, pnl = -0.015% (in band) → SCRATCH_EXIT fires
Exit Price: 599.91
```

**Purpose:** Exit near-flat trades early; prevents stagnation in ranging markets

**Contrast with Stagnation:** SCRATCH is looser band (±0.15%), faster (90s); STAGNATION is tighter (±0.05%), slower (110s)

---

### Level 9: STAGNATION_EXIT (Forced Release)

**Minimum Age:** 110 seconds  
**PnL Band:** |pnl| < 0.05%  
**Trigger Condition:**
```python
if age_seconds >= 110 and abs(pnl_pct) < 0.0005:
    # STAGNATION_EXIT fires
```

**Failure Reasons (V10.13m audit):**
- `STAGNATION_EXIT:too_young` — less than 110 seconds old
- `STAGNATION_EXIT:below_stagnation_pnl` — |pnl| ≥ 0.05%

**Example (XRPUSDT):**
```
Entry: 2.00 (T=0s), Current: 1.999 (-0.05%)
At T=100s: Age too young → skip
At T=110s: Now old enough, pnl = -0.05% (not in ±0.05% band) → skip
At T=120s: pnl = -0.03% (now in band) → STAGNATION_EXIT fires
Exit Price: 1.9994
```

**Purpose:** Force exit of completely stuck positions; ensure capital doesn't sit idle

---

### Level 10: TIMEOUT (Final Fallback)

**Window:** 120–300 seconds (varies by symbol volatility)  
**Typical:** 180 seconds (3 minutes)  
**Trigger Condition:**
```python
if age_seconds >= timeout_threshold:
    # TIMEOUT fires — force exit at market
```

**Timeout Variants:**
| Scenario | Duration |
|----------|----------|
| High volatility | 120s (aggressive) |
| Normal volatility | 180s (standard) |
| Low volatility | 300s (patient) |

**Failure Reasons (N/A — timeout always fires at threshold)**  
**Implicit Win:** `TIMEOUT_FLAT`, `TIMEOUT_PROFIT`, `TIMEOUT_LOSS` (tracked separately)

**Example:**
```
Entry: 50000 (T=0s)
At T=180s: No prior condition fired → TIMEOUT triggers
Current: 50050, pnl: +0.1%
Exit: TIMEOUT_PROFIT (50050)
```

**Purpose:** Capital efficiency; ensures positions don't hold indefinitely

---

## EXIT AUDIT INSTRUMENTATION (V10.13m)

### Three-Tier Audit System

#### 1. Branch Rejection Counters

**Purpose:** Track why each branch FAILS  
**Format:** `{branch:reason: count}`  

**Example Dictionary:**
```python
_exit_audit_rejections = {
    "MICRO_TP:below_threshold": 47,
    "MICRO_TP:negative_pnl": 3,
    "TRAILING_STOP:insufficient_retrace": 33,
    "TRAILING_STOP:insufficient_peak": 12,
    "SCRATCH_EXIT:pnl_outside_band": 28,
    ...
}
```

**Interpretation:**
- High `MICRO_TP:below_threshold` → signals generating small moves; may need threshold tuning
- High `TRAILING_STOP:insufficient_retrace` → MFE activating but no retrace; may indicate trend entries
- High `SCRATCH_EXIT:pnl_outside_band` → many positions drifting away from entry; wider band?

#### 2. Timeout Pre-Emption Trackers

**Purpose:** Detect near-miss exits beaten by timeout  
**Format:** `{exit_type_near_miss: count}`

**Definition of Near-Miss:**
- Within 10–20% distance of threshold, OR
- Branch armed historically but lost on current tick, OR
- Age eligible but price condition narrowly missed

**Example Dictionary:**
```python
_timeout_preemptions = {
    "scratch_near_miss": 14,     # Timeout fired with |pnl| just outside ±0.15%
    "micro_near_miss": 5,        # Timeout fired with pnl near 0.0010 threshold
    "trail_near_miss": 9,        # Timeout fired with retrace almost at 50%
    "partial25_near_miss": 7,    # Timeout fired near 25% TP milestone
}
```

**Interpretation:**
- High `scratch_near_miss` + high `TIMEOUT_FLAT` wins → SCRATCH band may be too tight; widen?
- High `trail_near_miss` → trailing activation threshold may be too high; lower?

#### 3. Exit Winners Counters

**Purpose:** Track which branches actually FIRE  
**Format:** `{exit_type: count}`

**Example Dictionary:**
```python
_exit_winners = {
    "MICRO_TP": 2,
    "BREAKEVEN_STOP": 1,
    "PARTIAL_TP_25": 0,
    "PARTIAL_TP_50": 0,
    "PARTIAL_TP_75": 0,
    "EARLY_STOP": 1,
    "TRAIL_PROFIT": 0,
    "SCRATCH_EXIT": 7,
    "STAGNATION_EXIT": 0,
    "TIMEOUT_FLAT": 41,          # dominant
    "TIMEOUT_PROFIT": 5,
    "TIMEOUT_LOSS": 6,
}
```

**Interpretation:**
- High `TIMEOUT_*` → prior branches not triggering; may indicate:
  - Thresholds too strict?
  - State tracking incorrect?
  - Regime detection broken?
- Low harvest (PARTIAL_TP_*) → positions not reaching profit milestones

### V10.13m Audit Logging

**Log Format (FAIL):**
```
[EXIT_AUDIT] BTCUSDT BUY age=127 pnl=0.00018 mfe=0.00024 branch=SCRATCH_EXIT 
            FAIL reason=pnl_outside_band observed=0.00018 threshold=0.00015
```

**Log Format (PASS/WIN):**
```
[EXIT_WINNER] BTCUSDT BUY reason=SCRATCH_EXIT age=192 pnl=0.00003 
             mfe=0.00026 tp_prog=0.05% regime=BEAR_TREND
```

**Dashboard Summary:**
```
[V10.13m EXIT_AUDIT]
  winners: micro=2 scratch=7 partial=0 trail=0 timeout_flat=36 timeout_profit=5 timeout_loss=6
  near_miss: scratch=14 micro=3 trail=11 partial25=9
  top_rejects:
    TRAILING_STOP:insufficient_retrace=33
    SCRATCH_EXIT:pnl_outside_band=28
    MICRO_TP:below_threshold=24
```

---

## NEAR-MISS DETECTION

### Definition

A position is "near-miss" if timeout fires while another exit was almost eligible:

- **Scratch near-miss:** TIMEOUT fired with |pnl| within 10–20% of ±0.15% band
- **Micro near-miss:** TIMEOUT fired with pnl within 10–20% of 0.0010 threshold
- **Trail near-miss:** TIMEOUT fired with retrace at 40–50% (almost at 50% trigger)
- **Partial near-miss:** TIMEOUT fired within 10% of TP milestone

### Detection Logic (V10.13m)

```python
# Example: Detect scratch near-miss
scratch_threshold = 0.0015
observed_pnl = abs(pnl_pct)
distance_to_threshold = abs(observed_pnl - scratch_threshold)

if distance_to_threshold < scratch_threshold * 0.20:  # Within 20% distance
    _timeout_preemptions["scratch_near_miss"] += 1
```

### Usage for Tuning

**If scratch_near_miss is HIGH:**
- Current: SCRATCH fires at |pnl| < 0.15%
- Issue: Many positions exit via TIMEOUT with pnl between 0.15–0.18%
- Fix (V10.13n): Widen SCRATCH_MAX_PNL to 0.0020

**If trail_near_miss is HIGH:**
- Current: Trailing fires at 50% retrace
- Issue: Many positions retracing 40–50% but timeout fires first
- Fix (V10.13n): Lower TRAILING_RETRACE_PCT to 0.40

---

## TIMEOUT FALLBACK LOGIC

### Timeout Variants

#### TIMEOUT_FLAT
**Condition:** Age ≥ threshold AND pnl ≈ 0%  
**Count:** Largest category (35–40% of exits in typical runs)  
**Indicates:** Ineffective prior branches; too conservative

#### TIMEOUT_PROFIT
**Condition:** Age ≥ threshold AND pnl > 0  
**Count:** Moderate (4–5%)  
**Indicates:** Position profitable but no harvest branch triggered

#### TIMEOUT_LOSS
**Condition:** Age ≥ threshold AND pnl < 0  
**Count:** Moderate (6–7%)  
**Indicates:** Position losing; EARLY_STOP didn't trigger

### Timeout Dominance Issue

**V10.13k/m observation:**
```
timeout_flat = 35–40% (HIGH)
micro = 1–2% (LOW)
trail = 0% (ZERO)
harvest = 0% (ZERO)
scratch = 6–8% (moderate)
```

**Hypothesis:** Timeout is structurally pre-empting better exits  
**Evidence needed:** V10.13m audit data (2-hour window)

**Potential root causes:**
1. MICRO_TP threshold too high relative to signal move distribution
2. TRAILING_STOP activation threshold too high; never arms
3. MFE state tracking broken; max_favorable_pnl not updating
4. Age calculations off; timeout fires earlier than expected
5. Regime detection incorrect; adaptive thresholds using wrong base

---

## DECISION FLOW DIAGRAM

```
┌──────────────────────────────────────────────────────────────┐
│ evaluate_position_exit(position, regime)                      │
└──────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ MICRO_TP (0.0010)    │
                    │ pnl ≥ threshold?     │
                    └────┬────────────┬────┘
                      YES│            │NO
                         │            │
                    (EXIT)│        (CONTINUE)
                         │            │
                         │            ▼
                         │    ┌──────────────────────┐
                         │    │ BREAKEVEN (20% TP)   │
                         │    │ tp_prog ≥ 0.20?      │
                         │    └────┬────────────┬────┘
                         │      YES│            │NO
                         │         │            │
                         │    (EXIT)│        (CONTINUE)
                         │         │            │
                         │         │            ▼
                         │         │    ┌──────────────────────┐
                         │         │    │ PARTIAL_TP (3-level) │
                         │         │    │ 25% / 50% / 75%?     │
                         │         │    └────┬────────────┬────┘
                         │         │      YES│            │NO
                         │         │         │            │
                         │         │    (EXIT)│        (CONTINUE)
                         │         │         │            │
                         │         │         │            ▼
                         │         │         │    ┌──────────────────────┐
                         │         │         │    │ EARLY_STOP (60% SL)  │
                         │         │         │    │ loss ≥ 0.60*sl?      │
                         │         │         │    └────┬────────────┬────┘
                         │         │         │      YES│            │NO
                         │         │         │         │            │
                         │         │         │    (EXIT)│        (CONTINUE)
                         │         │         │         │            │
                         │         │         │         │            ▼
                         │         │         │         │    ┌──────────────────────┐
                         │         │         │         │    │ TRAILING_STOP        │
                         │         │         │         │    │ mfe > 0.3% &         │
                         │         │         │         │    │ retrace > 50%?       │
                         │         │         │         │    └────┬────────────┬────┘
                         │         │         │         │      YES│            │NO
                         │         │         │         │         │            │
                         │         │         │         │    (EXIT)│        (CONTINUE)
                         │         │         │         │         │            │
                         │         │         │         │         │            ▼
                         │         │         │         │         │    ┌──────────────────────┐
                         │         │         │         │         │    │ SCRATCH (90s, 0.15%) │
                         │         │         │         │         │    │ age ≥ 90s &          │
                         │         │         │         │         │    │ |pnl| < 0.15%?       │
                         │         │         │         │         │    └────┬────────────┬────┘
                         │         │         │         │         │      YES│            │NO
                         │         │         │         │         │         │            │
                         │         │         │         │         │    (EXIT)│        (CONTINUE)
                         │         │         │         │         │         │            │
                         │         │         │         │         │         │            ▼
                         │         │         │         │         │         │    ┌──────────────────────┐
                         │         │         │         │         │         │    │ STAGNATION (110s, .05%)
                         │         │         │         │         │         │    │ age ≥ 110s &         │
                         │         │         │         │         │         │    │ |pnl| < 0.05%?       │
                         │         │         │         │         │         │    └────┬────────────┬────┘
                         │         │         │         │         │         │      YES│            │NO
                         │         │         │         │         │         │         │            │
                         │         │         │         │         │         │    (EXIT)│        (CONTINUE)
                         │         │         │         │         │         │         │            │
                         │         │         │         │         │         │         │            ▼
                         │         │         │         │         │         │         │    ┌──────────────────────┐
                         │         │         │         │         │         │         │    │ TIMEOUT (120-300s)   │
                         │         │         │         │         │         │         │    │ age ≥ timeout_s?     │
                         │         │         │         │         │         │         │    └────┬────────────┬────┘
                         │         │         │         │         │         │         │      YES│            │NO
                         │         │         │         │         │         │         │         │            │
                         │         │         │         │         │         │         │    (EXIT)│        (HOLD)
                         │         │         │         │         │         │         │         │            │
                         └─────────┴─────────┴─────────┴─────────┴─────────┴─────────┘         └────────────┘
                                             │
                                             ▼
                                     ┌──────────────────────┐
                                     │ Exit Position        │
                                     │ Log [EXIT_WINNER]    │
                                     │ Update counters      │
                                     └──────────────────────┘
```

---

## STATE INTEGRITY CHECKS

### Pre-Evaluation Validation

Before evaluating any branches, the engine should verify:

```python
# 1. Position object completeness
assert position.entry_price > 0
assert position.tp > 0
assert position.sl > 0
assert position.direction in ["LONG", "SHORT"]
assert position.age_seconds >= 0

# 2. Price consistency
assert position.entry_price != position.tp  # Entry and TP must differ
assert position.entry_price != position.sl  # Entry and SL must differ

# 3. PnL validity
assert not math.isnan(position.pnl_pct)
assert not math.isinf(position.pnl_pct)
assert position.pnl_pct > -1.0  # Can't lose more than 100%

# 4. MFE consistency
assert position.max_favorable_pnl >= position.pnl_pct
assert position.max_favorable_pnl >= 0
assert not math.isnan(position.max_favorable_pnl)

# 5. Regime validity
assert regime in [None, "BULL_TREND", "BEAR_TREND", "BULL_RANGE", 
                   "BEAR_RANGE", "RANGING", "QUIET_RANGE", "UNCERTAIN"]
```

### State Degradation Symptoms

**Symptom 1: TRAILING_STOP never fires**
```
Likely cause: max_favorable_pnl not updating
Check: Is MFE reset on each tick? Should only increase.
```

**Symptom 2: SCRATCH_EXIT and STAGNATION never fire**
```
Likely cause: age_seconds calculation wrong, or age_seconds in milliseconds not seconds
Check: age_seconds should reach 90+ within 90 real-world seconds
```

**Symptom 3: TIMEOUT_FLAT dominates (>50% of exits)**
```
Likely cause: All prior branches too conservative
Check: Increase thresholds one at a time; re-run V10.13m audit
```

**Symptom 4: MICRO_TP fires every tick**
```
Likely cause: pnl_pct computed incorrectly or threshold set to 0
Check: Verify pnl_pct calculation for current price
```

---

**Document Version:** 1.0  
**Last Sync:** 2026-04-17  
**Next Review:** After V10.13m audit data collection (2-hour window)
