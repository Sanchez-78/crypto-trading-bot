# CryptoMaster — V10.13h + V10.13i Consolidated Runtime Patch Brief

## Goal

This document is a single Claude-ready handoff covering:

- **V10.13h** — OFI selective tuning
- **V10.13i** — adaptive hard-block zone management
- **Current live-log evidence**
- **What is actually working**
- **What is still broken**
- **Single best next implementation direction**

This file is meant to be dropped into the existing project as the next implementation/analysis instruction.

---

## Executive summary

The system is no longer fully deadlocked. Recent live logs show:

- signals are being generated again
- trades are opening again
- `OFI_TOXIC_HARD` appears materially reduced versus earlier overblocking
- `LOSS_CLUSTER` is now a major blocker alongside OFI
- websocket reconnect logic is working
- however, **profit capture is still poor**
- **TP/trail harvest remains effectively zero**
- **profit factor is still weak**
- **the log stream still shows old RDE formatting (`RDE[v10.10b]`)**
- **V10.13i adaptive hard-block behavior is not yet clearly observable in runtime output**

So the current state is:

**Pipeline alive again, but not yet healthy or profitable.**

---

## Confirmed runtime evidence from latest logs

### 1. Pipeline is alive again

Recent logs show active candidate generation and execution flow:

- `Signaly (THIS CYCLE)  3 kandidati`
- open positions exist simultaneously
- recent trades count increases from `1455` to `1456`
- symbols produce real decisions, not only `zadny signal`
- forced exploration also fires:
  - `Generated FORCED signal LONG`

This confirms the bot is no longer in the previous “0 candidates forever” state.

---

### 2. OFI hard blocking is lower, but still present

Latest cycle snapshot shows:

```json
"block_reasons": {
  "OFI_TOXIC_HARD": 16,
  "LOSS_CLUSTER": 28,
  "OFI_TOXIC_SOFT": 1
}
```

This is much better than the earlier regime where OFI hard-blocking dominated.  
So **V10.13h likely improved selectivity**, at least partially.

But it also shows a new imbalance:

- `OFI_TOXIC_HARD` is no longer the main freeze source
- `LOSS_CLUSTER` is now the larger blocker
- `OFI_TOXIC_SOFT` is still too rare to prove healthy soft-routing

Meaning:

**The OFI fix helped, but the system did not transition enough blocked cases into useful soft penalties.**

---

### 3. Exit/harvest logic is still not working in practice

Live exit summary still shows:

```text
[V10.13g EXIT] TP=0 SL=2 micro=0 be=0 partial=(0,0,0) trail=0 scratch=0 stag=0 harvest=0 t_profit=8 t_flat=40 t_loss=6
→ Harvest rate: 0.0% (0/56)
```

And elsewhere:

- `Uzavreni       TP 0%  SL 3%  trail 0%  timeout 0%`

This is the most important negative runtime signal right now.

Even after V10.13g harvest cascade design, **the live system is still not harvesting profits**.

Implication:

- either the new smart exit paths are not truly reached in live execution
- or thresholds are too strict / mismatched with real move size
- or close reason mapping is incomplete
- or live positions rarely achieve the activation conditions before closing elsewhere

---

### 4. Profitability remains weak

Latest live metrics:

- `Profit Factor  0.70x`
- `Expectancy     -0.00000011`
- total PnL remains negative
- some pairs are strongly underperforming, especially:
  - `DOT  8  0%`
  - `SOL  21  43%`
  - BTC also negative net contribution despite acceptable WR

This means the current system can trade, but **trade quality and exit quality are still not production-grade**.

---

### 5. Runtime still exposes legacy decision formatting

The logs still repeatedly show:

```text
RDE[v10.10b]: ev=...
decision=TAKE ...
```

This matters because it means:

- current runtime observability is still anchored to older decision logging
- V10.13i adaptive zone behavior is **not visible enough**
- there is no explicit proof in live logs that adaptive hard-floor widening is active

So even if the code is deployed, **the runtime evidence is still insufficiently explicit**.

---

## V10.13h — OFI selective tuning summary

### Intent

Reduce false-positive OFI hard rejections by narrowing hard-blocking to only ultra-extreme imbalance and routing more cases into soft penalty handling.

### Intended change

- hard OFI threshold tightened from roughly `0.90` to `0.95`
- moderate toxic OFI cases should become soft-penalty cases
- this should increase pass-through without removing safety

### What live logs suggest

Probable partial success:

- `OFI_TOXIC_HARD` is no longer the overwhelming blocker
- some soft OFI path exists:
  - `OFI_TOXIC_SOFT: 1`

### What is still missing

- soft OFI counts are still too low
- there is not enough evidence that borderline OFI cases are being regularly rescued into execution
- loss-cluster now dominates, so OFI is no longer the only bottleneck

### Claude conclusion for V10.13h

Treat V10.13h as **helpful but incomplete**.  
Do **not** revert it.  
Instead, keep it and improve surrounding block arbitration and logging.

---

## V10.13i — Adaptive hard-block zone management summary

### Intent

Make hard/soft boundaries adaptive based on:

- idle time
- health
- recovery state

So that during unhealthy or stalled periods:

- hard floors become less aggressive
- soft zones widen
- more borderline signals receive penalties instead of hard rejection

### Intended result

When system health is bad or idle is high:

- fewer `SKIP_SCORE_HARD` / `FAST_FAIL_HARD` type deadlocks
- more trades pass through soft penalties
- recovery occurs through controlled leniency

### What live logs currently prove

Not enough.

The logs do show:

- poor health:
  - `Health: 0.003 [BAD]`
- live candidate generation
- reduced OFI hard blocks versus prior state

But the logs do **not** explicitly show adaptive zone config such as:

- active hard floor
- active soft ceiling
- adaptive mode state
- blocker-specific multiplier
- whether a signal was rescued from hard to soft due to V10.13i

### Claude conclusion for V10.13i

Assume V10.13i may be deployed, but **its runtime effect is not yet observable enough**.  
The next patch must add explicit diagnostics for adaptive zone state.

---

## Highest-value diagnosis from current logs

The main issue is no longer “no signals at all.”

The main issue is now:

### **The bot trades, but converts too little of that flow into retained profit.**

Evidence:

- candidates exist
- positions open
- trades close
- WR is around mid-50s
- yet PF is only `0.67x–0.70x`
- expectancy remains negative
- harvest/TP/trail all remain near zero

This combination strongly suggests:

1. **entry side is no longer the main blocker**
2. **exit side is underperforming in live conditions**
3. **some filters still block too aggressively in the wrong places**
4. **DOT and some bear/bull regime buckets are poisoning portfolio expectancy**
5. **observability is still too weak to validate adaptive blockers**

---

## What Claude should do next

Implement **one focused patch only**:

# V10.13j — Exit Realization + Adaptive Block Telemetry Patch

This patch should do four things and nothing else.

---

## Part A — Prove whether V10.13g harvest logic is actually executing

Instrument `smart_exit_engine.py` and trade close path so every triggered exit reason is logged at the moment of evaluation.

Add explicit live logs like:

```text
[EXIT_EVAL] sym=BTCUSDT pnl=+0.000004 tp_prog=0.18 micro=no be=no p25=no p50=no p75=no trail=no scratch=no stag=no chosen=NONE
[EXIT_EVAL] sym=ETHUSDT pnl=+0.000007 tp_prog=0.29 micro=yes chosen=MICRO_TP
```

Need to know:

- whether live positions ever reach these conditions
- whether conditions fire but another path overrides them
- whether close reasons are getting remapped incorrectly later

### Required output fields

For every open position during exit evaluation:

- `sym`
- `side`
- `pnl`
- `duration_s`
- `tp_progress`
- `mfe`
- `micro_tp_hit`
- `breakeven_hit`
- `partial25_hit`
- `partial50_hit`
- `partial75_hit`
- `trail_hit`
- `scratch_hit`
- `stagnation_hit`
- `chosen_reason`

Without this, V10.13g cannot be trusted.

---

## Part B — Add live telemetry for V10.13i adaptive zones

At the decision point in `realtime_decision_engine.py`, print the actual adaptive zone state whenever a blocker is evaluated.

Need log format like:

```text
[HBLOCK] sym=SOLUSDT blocker=SKIP_SCORE score=0.154 health=0.003 idle=342s zone=SEVERE hard_floor=0.030 soft_ceiling=0.180 result=SOFT penalty=0.41
```

And for hard reject:

```text
[HBLOCK] sym=DOTUSDT blocker=SKIP_SCORE score=0.014 health=0.003 idle=342s zone=SEVERE hard_floor=0.030 soft_ceiling=0.180 result=HARD_REJECT
```

This is mandatory because current logs still hide whether V10.13i is doing anything.

---

## Part C — Add pair-level quarantine for clearly toxic symbols

Current pair table shows one obvious outlier:

- `DOT  8 trades, 0% WR, strong negative contribution`

Claude should add a lightweight quarantine rule:

- if a symbol-regime bucket has:
  - `n >= 6`
  - `WR <= 0.20`
  - negative EV
- then size multiplier becomes `0.25x` or it is temporarily blocked for 30–60 minutes

This should be soft and reversible, not permanent.

Reason:

A few toxic pairs can destroy expectancy even when overall WR is acceptable.

---

## Part D — Make harvest thresholds regime-adaptive

The current fixed harvest levels are likely mismatched to real move size.

Claude should adapt harvest thresholds by regime:

### Suggested initial mapping

#### BULL / BEAR trend
- micro TP: `0.12%`
- partial 25/50/75 unchanged
- trailing activation: `0.35%`

#### RANGE / QUIET
- micro TP: `0.06%–0.08%`
- breakeven trigger earlier
- trailing activation: `0.20%`

Reason:

Ranging/quiet conditions often never reach current trend-sized profit triggers.

This is the most likely explanation for:

- `TP=0`
- `trail=0`
- `harvest=0`
despite real profitable time-in-trade occurring.

---

## Exact implementation rules for Claude

1. Do **not** rewrite the whole bot.
2. Do **not** touch risk manager unless required for logging fields.
3. Do **not** remove V10.13h or V10.13i.
4. Keep changes incremental and localized.
5. Prioritize runtime observability over theory.
6. Every new behavior must produce explicit logs.
7. Return full modified files, not diffs only.
8. Preserve backward compatibility with existing metrics dicts.

---

## Acceptance criteria for the next runtime validation

Claude’s next patch is successful only if fresh logs show all of the following:

### Exit observability
- `[EXIT_EVAL] ... chosen=...` lines appear
- at least one of `micro`, `be`, `partial`, or `trail` fires in live runtime

### Adaptive zone observability
- `[HBLOCK] ... zone=... hard_floor=... soft_ceiling=... result=...` lines appear
- at least one signal is shown entering SOFT zone because of adaptive logic

### Trade quality improvements
Within follow-up runtime:
- harvest rate rises above `0%`
- TP or trail no longer remains stuck at zero forever
- PF trends upward from `0.67x–0.70x`
- toxic pair suppression prevents worst offenders from dominating losses

---

## Short final verdict

### Good news
- The pipeline is alive again.
- V10.13h likely reduced OFI overblocking.
- The bot is trading again.
- Websocket recovery works.

### Bad news
- V10.13g harvest is not delivering in real runtime.
- V10.13i is not observable enough to validate.
- Profit factor and expectancy are still too weak.
- Some pairs/regimes are clearly toxic and need dynamic suppression.

### Best next move
**Do not add another broad strategy patch.**  
Add a focused **V10.13j Exit Realization + Adaptive Block Telemetry Patch**.

That is the highest-value next step.

---

## Claude handoff prompt

Use the following instruction:

> Implement V10.13j as an incremental runtime-observability and exit-realization patch for the existing CryptoMaster project. Keep V10.13h and V10.13i intact. Add explicit live logs for smart exit evaluation and adaptive hard-block zone evaluation, add reversible pair-level quarantine for clearly toxic symbol-regime buckets, and make harvest thresholds regime-adaptive. Return complete modified files. Prioritize proving what the live bot is actually doing over adding more strategy complexity.

