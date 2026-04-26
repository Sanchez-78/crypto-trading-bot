# CryptoMaster V10.13u — Post-Patch Review + Implementation Proposals

## TL;DR

Patch **partially worked** and fixed the most critical operational deadlock:

- bot is **no longer stuck in full idle deadlock**
- `pre_live_audit` now **PASSes**
- audit moved from:
  - `Passed to execution: 0 / Blocked: 20`
  - to
  - `Passed to execution: 19 / Blocked: 1`
- at least one real position is now open:
  - `BNB BUY $629.7830 -> $630.2850`
- last trade moved from **hours ago** to **seconds ago**
- forced-explore hard freeze is no longer the only dominant behavior

So the patch improved **mechanical flow**.

But it did **not** solve the main profitability/quality problem.

---

## WHAT IMPROVED

### 1) Hard deadlock was broken
Previously:
- no trades for hours
- repeated stall/self-heal/watchdog loop
- forced explore generated
- forced explore blocked
- audit CI FAIL

Now:
- `Posledni obchod 26s / 36s / 47s zpet`
- one open position exists
- `pre_live_audit complete  ci=PASS`
- `Passed to execution: 19`
- `Blocked: 1`

This is a major improvement.

### 2) Audit gate is no longer the main blocker
Old state:
- blocked ratio was catastrophic
- replay path was unusable

New state:
- `blocked=1 (0.050)`
- `CI PASS`

Conclusion:
- admission pipeline is now permissive enough to trade
- current bottleneck is no longer “nothing can pass”

### 3) Forced-explore is still present but no longer catastrophic
New `block_reasons` still include:
- `FORCED_EXPLORE_GATE: 686`
- later `FORCED_EXPLORE_GATE: 706`

So FE gate is still active a lot, but it is not freezing the whole system anymore.

Conclusion:
- FE gate is still noisy / dominant
- but no longer the total deadlock root cause

---

## WHAT IS STILL WRONG

### 1) Profitability is still poor despite high WR
Observed:
- `WR_canonical 74.4%`
- `Profit Factor 0.65x`
- `Zisk (uzavrene) -0.00090204`

Meaning:
- the bot wins often
- but losers/scratches still dominate economics
- current exit structure is still too weak to monetize edge

This is the same structural problem as before:
**winrate looks good, economics do not.**

### 2) PF inconsistency is still unresolved
Still visible:
- dashboard PF: `0.65x`
- economic PF: `4.93`

This is a major telemetry integrity bug.

Until this is fixed, high-level monitoring is not trustworthy.

Likely causes:
- different trade universe
- gross vs net mismatch
- scratch included in one PF and excluded in another
- different time window or denominator

This needs a **single canonical PF function**.

### 3) Learning quality is still weak
Observed:
- `Health: 0.019 [BAD]`
- `Edge: 0.000  Conv: 0.000  Stab: 0.000  Breadth: 0.000`
- `Hydrated pairs: 12 with n≥5, 6 with n≥10, 5 with conv>0`
- `Edge too weak or low convergence`

Important:
- bot now trades
- but learned edge is still weak / immature
- so passing more trades alone will not make system good

This is now a **quality-of-edge** problem, not primarily a routing problem.

### 4) Exit mix is still too scratch-heavy
Observed:
- `scratch 81%`
- `PARTIAL_TP_25 = 52`
- `SCRATCH_EXIT = 384`
- `STAGNATION_EXIT = 26`

Interpretation:
- the system often enters correctly enough to avoid catastrophic loss
- but does not capture enough directional movement
- edge is being “defensively neutralized” before it monetizes

### 5) Some accepted trades are still too weak
Examples:
- `BNBUSDT/BEAR_TREND wr=12% ev=-0.001`
- then softened to low-confidence TAKE path with reduced AF
- open position example:
  - `BNBUSDT BEAR_TREND EV:-0.0009 Size:0.0005`

That is mechanically defensible in bootstrap.
But it is dangerous if it remains active too long.

The system must distinguish:
- **bootstrap permissive mode**
- vs
- **post-bootstrap quality enforcement**

Right now bootstrap is solving deadlock, but may also be letting in low-quality flow.

---

## HIGH-PRIORITY CONCLUSIONS

### Good news
The patch succeeded in moving the bot from:
- dead system
to
- trading system

### Bad news
The bot is now:
- operationally alive
- economically still weak
- analytically inconsistent
- still over-dependent on bootstrap softening

So the next work should **not** focus on “more relaxed gating”.
That part already worked enough.

The next work must focus on:

1. **canonical metrics integrity**
2. **exit monetization**
3. **pair/regime quality throttling**
4. **bootstrap expiry discipline**
5. **feature quality improvement**

---

# IMPLEMENTATION PLAN

## Priority 1 — Unify canonical metrics

### Goal
Every screen/log/module must use the same canonical trade set and same formulas.

### Implement
Create one shared metrics module, for example:

- `src/services/canonical_metrics.py`

### Required functions
- `compute_canonical_pf(trades)`
- `compute_canonical_wr(trades)`
- `compute_canonical_expectancy(trades)`
- `compute_exit_breakdown(trades)`
- `compute_symbol_breakdown(trades)`

### Rules
- use **net pnl after fees only**
- use one consistent definition of:
  - closed trade
  - scratch
  - winner
  - loser
- dashboard, audit, monitor, Android, logs must all call the same functions

### Example code

```python
# src/services/canonical_metrics.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Dict, Any


@dataclass
class TradeView:
    pnl_net: float
    closed: bool
    scratch: bool
    exit_type: str
    symbol: str


def normalize_trade(t: Dict[str, Any]) -> TradeView:
    pnl = float(t.get("pnl_net", t.get("pnl", 0.0)))
    closed = bool(t.get("closed", True))
    exit_type = str(t.get("exit_type", "UNKNOWN"))
    scratch = exit_type in {"SCRATCH_EXIT", "STAGNATION_EXIT"} or abs(pnl) < 1e-12
    symbol = str(t.get("symbol", "UNKNOWN"))
    return TradeView(
        pnl_net=pnl,
        closed=closed,
        scratch=scratch,
        exit_type=exit_type,
        symbol=symbol,
    )


def closed_trades(trades: Iterable[Dict[str, Any]]) -> List[TradeView]:
    return [normalize_trade(t) for t in trades if normalize_trade(t).closed]


def compute_canonical_wr(trades: Iterable[Dict[str, Any]]) -> float:
    items = closed_trades(trades)
    decisive = [t for t in items if not t.scratch]
    if not decisive:
        return 0.0
    wins = sum(1 for t in decisive if t.pnl_net > 0)
    return wins / len(decisive)


def compute_canonical_pf(trades: Iterable[Dict[str, Any]]) -> float:
    items = closed_trades(trades)
    gross_profit = sum(t.pnl_net for t in items if t.pnl_net > 0)
    gross_loss = abs(sum(t.pnl_net for t in items if t.pnl_net < 0))
    if gross_loss <= 1e-12:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_expectancy(trades: Iterable[Dict[str, Any]]) -> float:
    items = closed_trades(trades)
    if not items:
        return 0.0
    return sum(t.pnl_net for t in items) / len(items)
```

### Add integrity check
At every summary print:
- compare dashboard PF vs canonical PF
- if delta > tolerance, print a warning

```python
pf_dashboard = metrics.get("profit_factor", 0.0)
pf_canonical = compute_canonical_pf(trades)

if abs(pf_dashboard - pf_canonical) > 0.05:
    logger.warning(
        "[METRICS_MISMATCH] dashboard_pf=%.4f canonical_pf=%.4f",
        pf_dashboard, pf_canonical
    )
```

---

## Priority 2 — Bootstrap expiry discipline

### Problem
Bootstrap permissive mode helps escape deadlock, but low-quality pairs still pass too easily.

### Goal
Bootstrap must **expire by rule**, not by vague time.

### Suggested logic
Use a stricter maturity state machine:

- `BOOTSTRAP_HARD`
- `BOOTSTRAP_SOFT`
- `NORMAL`
- `QUALITY_LOCKED`

### Suggested thresholds
Move pair/regime from bootstrap only if:
- `n >= 15`
- and `conv >= 0.10`
- and `ev > 0`
or if global:
- uptime >= 60 min
- total trades >= 150
- health >= 0.08

### Example code

```python
def get_pair_stage(n: int, conv: float, ev: float) -> str:
    if n < 8:
        return "BOOTSTRAP_HARD"
    if n < 15 or conv < 0.10:
        return "BOOTSTRAP_SOFT"
    if ev <= 0:
        return "QUALITY_LOCKED"
    return "NORMAL"
```

Use stage to control:
- score threshold
- AF multiplier
- whether fast-fail is soft or hard
- whether negative EV is absolutely rejected

### Recommended enforcement
- `BOOTSTRAP_HARD`: allow tiny exploratory trades only
- `BOOTSTRAP_SOFT`: allow reduced confidence trades
- `QUALITY_LOCKED`: no new trades until EV improves
- `NORMAL`: full rule set

---

## Priority 3 — Stop over-trading bad pair/regime cells

### Problem cells from log
The following look weak:
- `BNB/BEAR_TREND WR 12%`
- `DOT/BEAR_TREND WR 0%`
- `BTC/BULL_TREND WR 40%`
- `BTC/BEAR_TREND WR 40%`
- `SOL/BEAR_TREND EV -0.0003`
- `XRP/BEAR_TREND WR 14%`

### Goal
Do not fully disable exploration, but stop spending meaningful capital on obviously bad cells.

### Implementation
Add a cell quality penalty table updated from canonical stats.

```python
def pair_quality_penalty(n: int, wr: float, ev: float, conv: float) -> float:
    if n >= 8 and wr <= 0.20:
        return 0.20
    if n >= 10 and ev < 0:
        return 0.25
    if n >= 12 and conv >= 0.10 and ev <= 0:
        return 0.0
    if n < 8:
        return 0.50
    return 1.0
```

Then in sizing:

```python
size *= pair_quality_penalty(n, wr, ev, conv)
```

### Recommended behavior
- do not kill immature cells too early
- but once enough evidence exists, sharply reduce or fully block them

---

## Priority 4 — Exit system monetization patch

### Problem
The bot is not monetizing edge.
Too many trades end as scratch/stagnation even when overall WR is high.

### Goal
Convert more “almost good” entries into realized edge.

### Recommended changes

#### A) Add partial ladder
Instead of mostly:
- partial 25%
- then scratch/stagnation

Use:
- TP1 = 25% at 0.7 ATR
- TP2 = 25% at 1.1 ATR
- leave runner with tightened stop

#### B) Tighten scratch logic only after minimum hold or failed impulse
Do not scratch too early if:
- signal quality high
- coherence high
- trend regime favorable

#### C) Different stagnation logic by regime
- `BULL/BEAR`: allow more time before stagnation exit
- `RANGE`: exit earlier

### Example pseudo-code

```python
def manage_position(pos, px, atr, regime, signal_quality):
    pnl_r = unrealized_r_multiple(pos, px)

    if not pos.tp1_done and pnl_r >= 0.7:
        take_partial(pos, 0.25)
        move_stop_to_break_even(pos)
        pos.tp1_done = True

    if pos.tp1_done and not pos.tp2_done and pnl_r >= 1.1:
        take_partial(pos, 0.25)
        tighten_trailing_stop(pos, trail_mult=0.8)
        pos.tp2_done = True

    min_hold = 90 if regime in {"BULL_TREND", "BEAR_TREND"} else 45
    if pos.age_sec < min_hold and signal_quality >= 0.65:
        return

    if should_stagnate_exit(pos, regime=regime, atr=atr):
        close_position(pos, reason="STAGNATION_EXIT")
```

### Expected effect
- fewer trades die at near-flat result
- more trades crystallize partial gains
- PF should improve even if WR slightly drops

---

## Priority 5 — Near-miss driven TP calibration

### Strong signal from logs
- `partial25_near_miss = 20910`
- `micro_near_miss = 8528`

This is highly valuable.

### Interpretation
The market often gets close to your target but not enough to fill.

### Implement
Use rolling near-miss statistics to adapt TP multipliers.

### Example idea
If near-miss rate on TP1 is too high:
- slightly reduce TP1 threshold
- but only for strong setups

```python
def adaptive_tp1_mult(base_mult: float, near_miss_rate: float, regime: str) -> float:
    mult = base_mult
    if near_miss_rate > 0.30:
        mult -= 0.10
    if regime == "RANGING":
        mult -= 0.05
    return max(0.45, mult)
```

### Important
Do **not** globally lower TP for everything.
Apply only when:
- signal quality high
- spread acceptable
- feature quality not degraded

---

## Priority 6 — Fix fake confidence / miscalibration

### Problem
Log shows:
- `p=46.2%`
- `WR=74.4%`
- deviation `28.2pp`

That is severe miscalibration.

### Goal
Probability `p` must reflect empirical hit rate better.

### Implementation
Calibrate probabilities from recent closed trades.

### Example
Use reliability buckets:

```python
def calibrate_probability(raw_p: float, buckets: list[tuple[float, float, float]]) -> float:
    # buckets: [(lo, hi, empirical_wr), ...]
    for lo, hi, wr in buckets:
        if lo <= raw_p < hi:
            return wr
    return raw_p
```

Example buckets:
- 0.40–0.50 -> 0.58
- 0.50–0.60 -> 0.67
- 0.60–0.70 -> 0.72

Then:
- use calibrated p in score
- use calibrated p in display
- log both raw and calibrated probability

```python
logger.info(
    "p_raw=%.3f p_cal=%.3f score=%.3f",
    raw_p, calibrated_p, score
)
```

---

## Priority 7 — Feature pruning / weighting

### Problem
Current feature WR snapshot is weak and uniform:
- most features around `43%`

This often means one of these:
- feature attribution is too naive
- features are highly correlated
- bad features are not being downweighted enough

### Implement
Add simple online feature weights with shrinkage.

```python
def update_feature_weight(old_w: float, empirical_wr: float, lr: float = 0.05) -> float:
    edge = empirical_wr - 0.50
    new_w = old_w + lr * edge
    return min(1.5, max(0.5, new_w))
```

### Better rule
Only update feature weight when:
- feature was materially present
- trade had decisive outcome
- enough sample exists

### Recommended immediate action
Downweight features that remain:
- `< 0.45 WR`
- with `n >= 50`
- for multiple cycles

---

## Priority 8 — Pre-live audit should mirror live path more closely

### Problem
Audit is now passing, which is good.
But audit still seems very synthetic compared to live flow.

### Improve audit by including:
- real block reason histogram
- real pair maturity states
- actual size penalties from live
- exit audit score
- metrics mismatch check

### Add to audit summary
- `% weak EV accepts`
- `% bootstrap accepts`
- `% quality-locked rejects`
- canonical PF on replay sample
- scratch rate estimate

Example:

```python
audit_summary["weak_ev_accepts"] = weak_ev_accepts / max(total, 1)
audit_summary["bootstrap_accepts"] = bootstrap_accepts / max(total, 1)
audit_summary["quality_locked_rejects"] = quality_locked_rejects / max(total, 1)
```

---

# CODE PATCH SUGGESTIONS

## Patch A — harden EV-only while preserving bootstrap exploration

```python
def effective_ev_for_take(ev: float, stage: str, wr: float, conv: float) -> float:
    if ev > 0:
        return ev
    if stage == "BOOTSTRAP_HARD":
        return max(ev, 0.005)  # tiny synthetic floor for minimal exploration
    if stage == "BOOTSTRAP_SOFT" and wr >= 0.55 and conv < 0.10:
        return 0.010
    return ev


def should_reject_negative_ev(ev_eff: float) -> bool:
    return ev_eff <= 0.0
```

Use:
- real EV in logs
- effective EV only for temporary bootstrap routing
- never hide original EV

---

## Patch B — canonical trade labeling

```python
def canonical_trade_label(pnl_net: float, exit_type: str) -> str:
    if exit_type in {"SCRATCH_EXIT", "STAGNATION_EXIT"}:
        return "SCRATCH" if abs(pnl_net) <= 0 else ("WIN" if pnl_net > 0 else "LOSS")
    if pnl_net > 0:
        return "WIN"
    if pnl_net < 0:
        return "LOSS"
    return "FLAT"
```

This prevents dashboard/report disagreement.

---

## Patch C — regime-aware scratch timing

```python
def scratch_hold_seconds(regime: str, coherence: float) -> int:
    base = {
        "BULL_TREND": 90,
        "BEAR_TREND": 90,
        "RANGING": 45,
        "QUIET_RANGE": 35,
        "HIGH_VOL": 60,
    }.get(regime, 60)

    if coherence >= 0.75:
        base += 20
    elif coherence <= 0.55:
        base -= 10

    return max(20, base)
```

---

## Patch D — reject chronically bad cells after enough evidence

```python
def hard_cell_block(n: int, wr: float, ev: float, conv: float) -> bool:
    if n >= 12 and ev < 0 and conv >= 0.10:
        return True
    if n >= 10 and wr <= 0.20:
        return True
    return False
```

This would block cells like:
- BNB/BEAR if poor stats persist
- DOT/BEAR if still near 0% WR
- BTC bull/bear if negative EV persists after maturity

---

# RECOMMENDED NEXT PATCH ORDER

## Patch 1
**Canonical metrics unification**
- one PF
- one WR
- one expectancy
- one scratch definition

## Patch 2
**Bootstrap state machine**
- hard / soft / normal / quality-locked

## Patch 3
**Cell quality penalty / hard block**
- stop allocating to statistically weak cells after enough evidence

## Patch 4
**Exit monetization**
- TP ladder
- regime-aware stagnation
- delayed scratch for strong signals

## Patch 5
**Probability calibration**
- raw p -> calibrated p from empirical reliability buckets

## Patch 6
**Feature pruning**
- downweight persistently weak features

---

# FINAL ASSESSMENT

## Current state
The system is now:

- **operationally improved**
- **no longer deadlocked**
- **able to pass audit**
- **able to open trades**

But it is still:

- **not economically strong**
- **telemetry-inconsistent**
- **over-scratchy**
- **under-converged**
- **still too tolerant of weak pair/regime cells**

## Best interpretation
The current patch solved the **plumbing problem**.

Now you must solve the **economics problem**.

That means the next iteration should focus much less on:
- making more things pass

and much more on:
- making accepted trades meaningfully profitable
- removing metric ambiguity
- killing bad cells after evidence accumulates
- monetizing near-miss structure

---

# ONE-SENTENCE VERDICT

**V10.13u looks like the first version that is operationally alive again, but it is still not analytically trustworthy nor economically production-ready until canonical metrics, exit monetization, and pair/regime quality enforcement are fixed.**
