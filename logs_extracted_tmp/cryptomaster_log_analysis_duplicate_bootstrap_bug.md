# CryptoMaster Log Analysis — Duplicate Candidate / Bootstrap Flood / Counter Inconsistency

## Context

This analysis is based on the provided runtime log excerpt from the live trading bot during cold start / training mode. The goal is to identify the highest-priority correctness issues visible directly from logs, without guessing beyond what the evidence supports.

---

## Executive Summary

The primary issue shown in this log is **not learning failure**, but **repeated generation and acceptance of effectively identical candidate signals during cold start**, combined with **inconsistent dashboard counters and inconsistent regime labeling across components**.

### Highest-confidence findings

1. **Duplicate or near-duplicate candidates are being generated and accepted repeatedly.**
2. **Cold-start thresholds are permissive enough that repeated low-information setups are accepted.**
3. **Dashboard counters do not match actual execution behavior.**
4. **Regime labels appear inconsistent between decision logs, dashboard output, and execution engine state.**
5. **`NO LEARNING SIGNAL DETECTED` is visible, but in this excerpt it is likely secondary to the entry duplication/bootstrap issue, not the root cause.**

---

## Evidence from Logs

### 1. Repeated identical candidate decisions

The log shows many repeated decision blocks with only tiny price differences or none at all, for example:

- `SOL $85.9550 | [fake_breakout] ... decision=TAKE`
- `ETH $2,329.1450 | [fake_breakout] ... decision=TAKE`
- `ETH $2,329.1550 | [fake_breakout] ... decision=TAKE`
- `ETH $2,329.2350 | [fake_breakout] ... decision=TAKE`
- `BNB $637.8850 | [fake_breakout] ... decision=TAKE`
- `BNB $637.8950 | [fake_breakout] ... decision=TAKE`

Repeated values:

- `EV=0.050`
- `p=0.50`
- `rr=1.25`
- `ws=0.500`
- `score=0.185`
- `n=0`
- `t15=0`
- `spread=0.000`
- same pattern tags and same feature bundles

This strongly suggests one of the following:

- no candidate deduplication exists,
- deduplication exists but is broken,
- the same setup is being re-evaluated many times per cycle without guard rails,
- the decision path is invoked repeatedly for identical microstate changes.

### 2. Cold-start acceptance is extremely permissive

Observed repeatedly:

- `thr=-0.285`
- `[V10.13r] SCORE_THRESHOLD_COLD_START: relaxed to 0.1728`
- `score=0.185`
- `decision=TAKE`

Interpretation:

- the score threshold is relaxed enough that marginal setups are accepted,
- combined with `n=0`, this allows repeated bootstrap entries before the system has any learning evidence,
- repeated `TAKE` decisions become likely unless explicit anti-repeat guards exist.

### 3. Execution state confirms actual over-entry, not just noisy logging

Later dashboard state shows:

- `Positions: 5`
- open positions in BTC, BNB, SOL, ETH, XRP
- runtime only `0h 0m 33s`
- `Zadne uzavrene obchody – robot se zahriva...`

This means the problem is not only verbose logging. The engine is actually opening multiple positions during very early cold start.

### 4. Dashboard counters appear inconsistent with execution reality

Same snapshot reports:

- `Signaly (THIS CYCLE) 0 kandidati`
- `cele: 614 zachyceno  0 provedeno`

Yet the same overall state also shows:

- many `decision=TAKE` lines,
- 5 open positions,
- active execution engine state.

This implies at least one of these is true:

- `provedeno` does not mean actual executed trades,
- dashboard counters are reading stale or different state,
- candidate/execution counters are incremented in different paths,
- UI aggregation is disconnected from the true execution path.

### 5. Regime labeling appears inconsistent

Examples:

- dashboard: `BTC KUPUJ ... BULL`
- execution engine: `BTCUSDT RANGING`

and:

- dashboard decision line: `XRP PRODEJ ... BEAR`
- execution engine position line: `XRPUSDT BULL_TREND`

This suggests regime may differ across:

- decision-time classification,
- stored position metadata,
- execution panel rendering,
- or later mutation of the position state.

That is dangerous because regime affects:

- sizing,
- learning bucket assignment,
- analytics,
- strategy weighting.

---

## What Is Probably *Not* the Primary Root Cause Here

### `NO LEARNING SIGNAL DETECTED`

This is visible, but in this specific cold-start excerpt it is not enough to conclude the learning path itself is broken.

Why:

- there are `0 closed trades` in the shown snapshot,
- the monitor explicitly says it is waiting for closed trades / pair minimums,
- no completed trade path is visible in this specific excerpt.

So in this slice of logs, the safer conclusion is:

- learning has not yet had enough closed-trade material to emit a useful signal,
- but the more urgent bug is that bootstrap execution is already noisy and potentially low-quality.

---

## Root Cause Hypothesis

### Root Cause A — Missing or broken candidate deduplication

Most likely the system lacks a strong fingerprint-based dedup guard before execution.

A correct system should reject repeated candidates that are effectively the same setup within a short time window.

Expected fingerprint dimensions:

- symbol
- side / action
- regime
- setup tag / reason
- rounded entry zone
- active feature set
- candle bucket / decision window

### Root Cause B — Cold-start mode is too permissive without bootstrap caps

Relaxed cold-start scoring may be intentional, but it must be paired with:

- max new positions per minute,
- symbol-side cooldown,
- duplicate setup suppression,
- total bootstrap exposure cap.

Without those, relaxed thresholds become a position flood amplifier.

### Root Cause C — Observability counters are not attached to canonical execution events

Counters like:

- captured
- candidates
- executed
- opened
- blocked

likely do not come from one canonical event stream.

This makes the dashboard misleading during diagnosis.

### Root Cause D — Regime is not frozen consistently at decision/open time

The regime shown in one component may be computed live while another component shows stored or recomputed regime.

That creates inconsistent analytics and wrong learning attribution.

---

## Priority Assessment

## P1 — Fix immediately

1. **Add duplicate-candidate guard before execution**
2. **Block same-symbol same-side re-entry within short cooldown**
3. **Limit bootstrap opens per time window**
4. **Unify execution counters with true canonical events**
5. **Freeze regime on open and use the same regime everywhere downstream**

## P2 — Fix next

6. Add explicit skip reason: `DUPLICATE_CANDIDATE_SKIP`
7. Add `candidate_id`, `cycle_id`, and `decision_id` to logs
8. Tighten cold-start relaxations if duplicate flood persists
9. Separate “evaluated”, “eligible”, “taken”, and “opened” in dashboard

---

## Recommended Correctness Guards

### 1. Candidate fingerprint deduplication

```python
fingerprint = (
    symbol,
    action,
    setup_tag,
    regime,
    round(entry_price, price_bucket_precision),
    tuple(sorted(active_features)),
)

if fingerprint in recent_candidate_fingerprints(last_seconds=20):
    return skip("DUPLICATE_CANDIDATE")
```

### 2. Same symbol + same side open guard

```python
if has_open_position_same_side(symbol, action):
    return skip("ALREADY_OPEN_SAME_SIDE")
```

### 3. Symbol cooldown after recent open

```python
if opened_same_symbol_recently(symbol, seconds=30):
    return skip("SYMBOL_COOLDOWN")
```

### 4. Bootstrap frequency cap

```python
if cold_start and opened_trades_last_60s >= MAX_BOOTSTRAP_OPENS_PER_MIN:
    return skip("BOOTSTRAP_FREQ_CAP")
```

### 5. Freeze regime at open time

```python
position["decision_regime"] = detected_regime
position["open_regime"] = detected_regime
```

Then all downstream rendering and learning should default to the stored open regime unless there is a clearly separate field for current live regime.

---

## Required Observability Fixes

The dashboard should distinguish these counters explicitly:

- `signals_seen`
- `candidates_built`
- `candidates_after_filters`
- `decision_take`
- `execution_attempted`
- `execution_opened`
- `execution_rejected`
- `duplicate_skipped`
- `cooldown_skipped`
- `same_side_skipped`

Right now, the logs imply these concepts are being mixed together.

---

## Acceptance Criteria for the Fix

A fix should not be considered complete until logs prove all of the following:

### A. Duplicate suppression works

For repeated same-setup events in a short window, logs should show:

- first candidate may be taken,
- later identical candidates show `DUPLICATE_CANDIDATE_SKIP`.

### B. Bootstrap no longer floods positions

In first minute of runtime:

- number of newly opened positions is bounded,
- same symbol/side is not repeatedly reopened,
- exposure growth is controlled.

### C. Counters match reality

If dashboard says `execution_opened = 5`, there must be 5 actual opens.
If dashboard says `this cycle candidates = 0`, there must not be new `decision=TAKE` lines for that cycle.

### D. Regime is consistent

For each open position, the regime shown in:

- decision log,
- stored position,
- execution panel,
- learning bucket

must be explainably consistent.

---

## Best One-Sentence Diagnosis

**The bot is not primarily failing because learning is absent; it is failing because cold-start decision logic is permissive enough to accept repeated near-identical setups, while deduplication, counters, and regime consistency are not reliably enforced.**

---

## Suggested Claude Code Task Framing

Use this as a correctness-first bugfix task:

> Investigate and fix duplicate candidate generation / acceptance during cold start. Add candidate fingerprint deduplication, same-symbol same-side cooldown guards, bootstrap frequency caps, canonical execution counters, and regime consistency from decision to position storage to dashboard. Do not tune strategy alpha yet. First prove correctness with logs.

