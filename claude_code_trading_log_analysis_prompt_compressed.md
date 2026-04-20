# Claude Code Prompt — Compressed Trading Bot Log Analysis

You are a senior Python quant/backend engineer. Analyze the provided trading bot log and corresponding codebase. Do not give generic advice. Identify concrete root causes, verify them in code, and implement precise fixes.

## Goal
Explain why the bot underperforms or stalls, especially around:
- timeout-dominant exits
- weak or broken learning feedback
- bootstrap/cold-start failure
- over-filtered decision flow
- mismatch between signal quality, execution, and learning updates

## Required output
Produce exactly these sections:
1. **Observed failures from log**
2. **Root cause map**
3. **Code locations to inspect**
4. **Concrete fixes to implement**
5. **Expected behavioral changes after patch**
6. **Risk/regression checklist**
7. **Final patch summary**

## Analysis rules
- Base conclusions on real log evidence first, then confirm in code.
- Prefer deterministic fixes.
- Do not remove useful protections unless they are clearly causing deadlock.
- Preserve event-driven architecture.
- Preserve adaptive/meta logic, but prevent it from starving the system.
- If multiple causes exist, rank by production impact.

## Main hypotheses to verify

### 1) Timeout dominance is destroying learning quality
Check whether most trades close by timeout instead of TP/SL/trailing.
Verify:
- hold time too long or too short for regime volatility
- TP too far vs actual micro-move distribution
- SL/TP derived from ATR but not aligned with real move statistics
- timeout exits produce low-information outcomes
- timeout classification or PnL labeling contaminates learning

Inspect:
- trade_executor.py
- timeout/close classification logic
- TP/SL/trailing calculation path
- learning_monitor.py outcome ingestion

Implement if confirmed:
- tighter regime-aware hold time
- more reachable TP levels
- clearer timeout labeling
- learning updates based on net realized PnL, not exit type alone

### 2) Learning loop exists but receives poor signal
Verify whether learning is updated from:
- actual net trade outcome
- regime + symbol bucket
- execution quality / realized slippage / timeout context
- enough trades per bucket

Check for failure patterns:
- updates happen but EV remains near zero
- all buckets starve due to low sample count
- bandit/meta state never escapes neutral
- learning uses noisy timeout-heavy labels
- confidence scaling suppresses adaptation too hard

Inspect:
- learning_monitor.py
- policy_layer.py
- execution.py
- any bandit / meta-controller logic

Implement if confirmed:
- stronger bootstrap priors
- minimum exploration for under-sampled profitable-looking buckets
- confidence scaling that reduces size, not total participation
- better separation of execution failure vs strategy failure

### 3) Cold start / bootstrap logic is too harsh
Verify whether early EV thresholds, score thresholds, ws gates, or confidence penalties block trading before enough data exists.

Look for:
- n-dependent gating that is still too strict at n<10, n<20, n<50
- cold-start threshold appears relaxed in logs but still impossible in combined pipeline
- policy multiplier or meta-controller re-suppresses already-relaxed candidates
- exploration priors missing for unseen symbol/regime pairs

Implement if confirmed:
- bootstrap priors per regime
- floor participation for promising low-sample candidates
- separate “can trade small” from “can trade full size”
- use softer penalties instead of hard rejection when data is sparse

### 4) Decision pipeline is over-filtered
Reconstruct the full rejection path from log to order execution.
Determine whether candidates die because too many individually reasonable filters combine into zero throughput.

Check interaction of:
- EV threshold
- weighted score threshold
- timing filter
- spread filter
- frequency / cooldown
- streak / velocity penalties
- coherence adjustment
- policy multiplier
- portfolio/risk guard
- execution quality modifier

Implement if confirmed:
- convert some hard blocks into bounded penalties
- add idle-unblock logic
- lower thresholds only during prolonged inactivity
- log final per-candidate reject reason chain clearly

### 5) Execution and learning are misaligned
Verify whether trades with decent predicted edge are later penalized because execution-quality or cost model is applied too late.

Check:
- predicted edge vs post-cost edge
- slippage/spread penalties timing
- whether learning blames strategy for execution friction
- whether execution-quality score affects size, selection, or both

Implement if confirmed:
- cost-aware decision before final accept
- explicit split: signal quality vs execution quality vs realized outcome
- persist execution diagnostics into learning records

### 6) Persistence/state continuity may be broken
Verify whether model state, EV history, cooldowns, or learning state reset after restart or partial failure.

Check:
- Redis optional fallback behavior
- Firestore loading/saving of model_state, metrics, weights, advice
- whether startup begins effectively from zero too often
- whether logs show old code signatures or mismatched deployment state

Implement if confirmed:
- reliable persisted warm start
- safe fallback to in-memory without silent learning loss
- startup report showing loaded state counts and active version signature

## What to inspect in logs
Extract and summarize:
- close distribution: TP / SL / trail / timeout
- EV values by symbol/regime
- score/ws values of rejected vs accepted trades
- cold-start threshold messages
- coherence adjustments
- streak/velocity/timing penalties
- evidence of long no-trade periods
- evidence that learning stats do not move despite many trades

## What to inspect in code
Prioritize these files if present:
- src/services/realtime_decision_engine.py
- src/services/trade_executor.py
- src/services/learning_monitor.py
- src/services/execution.py
- src/services/policy_layer.py
- src/services/risk_engine.py
- src/services/execution_quality.py
- src/services/regime_predictor.py
- firebase_client.py
- state/persistence loaders

## Implementation expectations
When you find a confirmed issue:
- explain exact cause
- show exact code change
- explain why this fix is safer than naive threshold reduction
- avoid hand-wavy “tune this later” advice

## Patch style
- Keep patches production-oriented
- Preserve logging and improve observability
- Add comments only where logic is non-obvious
- Avoid random exploration; use bounded deterministic exploration

## Success criteria
A successful patch should lead to:
- fewer timeout exits
- more informative TP/SL distribution
- non-dead learning buckets
- controlled cold-start participation
- fewer zero-signal / zero-trade periods
- clearer attribution of failure source
- stable persisted learning across restarts

## Final instruction
Do the analysis as if this is a live production bot already running on real infrastructure. Be critical, specific, and implementation-focused. If something in the log suggests the deployed version differs from the intended version, call it out explicitly.
