# CryptoMaster Log Analysis — Claude Code Input

## Task

Analyze the attached trading bot log and identify the real root causes behind poor performance, weak learning, and inconsistent decision quality.

Do not give generic advice.  
Perform a **deep technical analysis** of the runtime behavior visible in the log and infer the most likely code-level problems in the current bot implementation.

Focus on:
- decision pipeline
- EV gating
- cold-start / bootstrap behavior
- learning signal generation
- persistence / model state recovery
- exit quality
- confidence / calibration mismatch
- consistency between logs, state, and monitoring outputs

---

## Key findings already extracted from the log

### 1. Broken or incomplete state recovery
The bot loads trade history, but still reports:

- `No persisted model state — starting fresh`

At the same time it reports bootstrap stats based on historical trades.

This strongly suggests:
- trade history is being restored
- but the **full model state is not**
- therefore the bot restarts in a partially reset condition

Possible missing restored state:
- EV history
- confidence calibration
- feature/regime statistics
- bandit/meta state
- learning monitor state
- model weights
- rolling quality statistics

This can create a fake bootstrap where the bot has some historical trades but not the learned context needed to interpret them correctly.

---

### 2. EV gate is too permissive in recovery / cold-start
The log shows trades being accepted even with clearly negative EV, for example:

- `EV = -0.2125`
- threshold around `-0.300`
- decision = `TAKE`

This is dangerous.

Recovery logic should help unblock deadlock, but it should **not** allow obviously bad negative-edge trades just because the threshold is dynamically relaxed.

Investigate whether:
- dynamic EV threshold becomes too negative in cold-start
- recovery mode overrides too many protections
- final TAKE decision ignores minimum absolute EV sanity checks
- weighted score / confidence is masking negative EV incorrectly

Desired behavior:
- recovery mode may relax filters slightly
- but should still reject materially negative EV trades

---

### 3. Learning loop appears effectively dead
The log repeatedly shows:

- `LEARNING: NO LEARNING SIGNAL DETECTED`
- `Health: 0.000 [BAD]`

This suggests the execution layer is producing trades, but the learning layer is not receiving or accepting valid outcome signals.

Investigate the full path:

1. position opens
2. position closes
3. close reason and net pnl are classified
4. learning event is emitted
5. learning monitor updates symbol/regime stats
6. updated state is persisted
7. decision engine consumes updated stats

Look for failures such as:
- trade close events not reaching learning pipeline
- timeout exits not generating learning events
- pnl classification producing neutral/invalid outcomes
- filters rejecting all learning updates
- persistence writes failing silently
- restored state being overwritten on startup

---

### 4. Exit distribution is unhealthy
Observed distribution:

- TP: 0%
- SL: 18%
- trail: 4%
- timeout: 78%

This is a major structural problem.

A system where most trades end by timeout is usually not generating clean learning signals.

Possible causes:
- hold time too long or badly tuned
- TP too far
- SL too wide or too passive
- trailing not activating properly
- entries too late / poor timing
- signal quality too weak at entry
- exits are based on fallback clock instead of actual edge realization

Investigate whether timeout is dominating because of entry quality, exit design, or both.

---

### 5. Confidence / probability is badly miscalibrated
The log indicates something close to:

- predicted probability around `46.2%`
- actual WR around `2.0%`
- deviation around `44.2 pp`

That is a severe calibration failure.

Investigate:
- how `p` is computed
- whether `p` is derived from stale/default priors
- whether bootstrap confidence is inflated
- whether winrate proxy is computed on wrong sample
- whether regime/symbol sample counts are ignored
- whether confidence is used in final decision despite poor calibration

This likely causes the bot to over-trust weak or bad setups.

---

### 6. The filter is paradoxically both too strict and too weak
The bot appears to pass only a tiny fraction of captured opportunities, roughly around `0.6–1.6%`.

So the system is:
- very selective overall
- but still sometimes accepts clearly bad trades in recovery mode

This is a bad combination:
- too few samples for healthy learning
- but low-quality exceptions still get through

Investigate whether the pipeline currently suffers from:
- over-filtering in normal mode
- over-relaxation in recovery mode
- insufficient middle-ground adaptation

The system may be oscillating between:
- deadlock
- emergency unblocking
- poor trade quality
- no useful learning

---

### 7. Inconsistent state reporting across components
The log suggests inconsistencies between:
- decision-time EV
- learning monitor EV
- open-position EV display
- summary metrics

For example, trades may be accepted using a non-zero EV, while open positions later display EV near `0.0000`.

Investigate whether different layers are using:
- different EV definitions
- stale cached values
- uninitialized defaults
- persistence snapshots from different times

Need clear separation and naming for:
- raw EV
- confidence-adjusted EV
- policy EV
- displayed EV
- persisted EV

If these are mixed, operators cannot trust monitoring and debugging becomes misleading.

---

## What Claude Code should do

### Phase 1 — Log forensics
Read the log carefully and reconstruct:

- startup sequence
- model restore sequence
- signal generation path
- decision gating path
- trade open/close lifecycle
- learning update lifecycle
- summary metric generation

Extract concrete evidence, not guesses.

For every major conclusion:
- quote the relevant log fragments
- explain what they imply
- separate root causes from downstream symptoms

---

### Phase 2 — Code-level root cause hypotheses
Based on the runtime evidence, identify the most likely faulty modules and functions.

Expected hot areas include:
- `realtime_decision_engine.py`
- `learning_monitor.py`
- `trade_executor.py`
- `execution.py`
- persistence / Firebase / state restore logic
- model state bootstrap / loading logic

For each suspected module:
- explain why it is implicated
- describe the likely bug or design flaw
- describe how that bug would produce the observed log behavior

---

### Phase 3 — Required fixes
Propose concrete implementation fixes, prioritized by impact.

Priority order should likely be:

1. restore full model state correctly
2. stop TAKE on materially negative EV
3. repair learning-signal generation chain
4. reduce timeout dominance
5. recalibrate confidence/probability
6. unify EV/state reporting across subsystems

For each fix provide:
- exact intent
- likely file/module to change
- logic to add/remove/change
- risks/regressions to watch for

---

### Phase 4 — Validation plan
Define how to verify that the fixes actually work in production.

Include:
- expected log signatures after fix
- metrics that should improve
- anti-regression checks
- startup validation checklist
- learning health checklist
- timeout distribution targets
- calibration sanity checks
- signal pass-rate sanity checks

---

## Output format required from Claude Code

Return the result in this exact structure:

# Runtime Diagnosis
# Root Causes
# Code-Level Suspects
# Fix Plan
# Validation Plan
# Highest-Risk Hidden Failure Modes

Be precise, technical, and critical.  
Do not soften conclusions.  
Do not provide generic trading advice.  
Treat this as production debugging of a live event-driven trading system.

---

## Extra instruction

If the log suggests that the currently deployed code is not the same as the expected patched version, explicitly call that out and explain why.
