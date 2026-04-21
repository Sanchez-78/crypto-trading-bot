# CryptoMaster — Claude Code Implementation Prompt

## Role
You are a senior Python trading-systems engineer performing a correctness-first implementation pass on a live event-driven crypto trading bot.

Do not do broad refactors. Do not redesign the whole bot. Do not remove existing strategy logic unless it is provably broken.

Your goal is to **fix the learning pipeline observability and correctness** so the runtime can prove that:
1. trades really close,
2. the close event reaches learning,
3. learning updates state,
4. state is persisted,
5. state is reloaded correctly,
6. dashboard/report output reflects the true state.

Work in small, verifiable changes.

---

## Context from runtime logs
Current runtime behavior strongly suggests a mismatch between **trade closing**, **learning updates**, and **reported learning status**.

Observed patterns from logs:
- `completed_trades` increases: 102 → 103
- trade persistence happens: `Firebase: saved 1 trades (batch write)`
- exit audit fires: `[V10.13g EXIT]`, `[V10.13m EXIT_AUDIT]`
- there are real winners / partial exits / scratch exits
- but runtime still prints: `[!] LEARNING: NO LEARNING SIGNAL DETECTED`
- learning `Health` stays ~`0.001 [BAD]`
- most `conv` values remain `0.0`
- many pair/regime stats have nonzero `n` and reasonable WR, but EV remains tiny / near zero
- features all show the same WR (`59%`) which strongly suggests aggregation/reporting corruption or fallback/default reuse
- version markers are mixed in runtime:
  - `RDE[v10.10b]`
  - `coherence[v10.12]`
  - `[V10.13r]`
  - `[V10.13g EXIT]`
  - `[V10.13m EXIT_AUDIT]`

This means the bot is not “dead”; it is producing closes and persisting trades. The likely problem is that the **learning signal path is broken, bypassed, or not observable**, and reporting may also be inconsistent.

---

## Primary objective
Implement a **traceable learning pipeline** from close event to persisted learning state.

Specifically prove the full path:

`trade close -> close classification -> lm_update call -> learning state mutation -> persistence write -> hydrate/reload -> monitor/report`

---

## What to fix first

### 1. Add explicit lifecycle instrumentation
Instrument the exact path of a closed trade.

Add structured logs/counters for these stages:
- `CLOSE_DETECTED`
- `CLOSE_CLASSIFIED`
- `LEARNING_SIGNAL_EMITTED`
- `LM_UPDATE_ENTER`
- `LM_UPDATE_APPLIED`
- `LM_STATE_PERSIST_REQUEST`
- `LM_STATE_PERSIST_OK`
- `LM_STATE_RELOAD_OK`
- `LEARNING_MONITOR_RENDER`

Requirements:
- each stage must include at least: `symbol`, `regime`, `trade_id` or stable surrogate key, `reason`, `pnl`, `net_pnl`, `duration_s`
- if any stage is skipped, log exactly why
- no vague messages like “no learning signal detected” without a reason code

Add a **reason enum / label** for missing learning updates, e.g.:
- `position_not_finalized`
- `close_event_missing`
- `trade_not_persisted`
- `lm_update_not_called`
- `lm_update_rejected_invalid_payload`
- `regime_missing`
- `symbol_missing`
- `duplicate_close_suppressed`
- `reload_failed`
- `report_source_empty`

The current generic message:
- `[!] LEARNING: NO LEARNING SIGNAL DETECTED`

must be replaced with something actionable, e.g.:
- `[LEARNING_PIPELINE] no update this cycle: lm_update_not_called`

---

### 2. Make `lm_update()` provably reachable
Find the actual close path in the current codebase.

Likely locations include:
- `trade_executor.py`
- close/finalize/exit handlers
- timeout / scratch / partial / trail logic
- persistence layer around closed trades
- `learning_monitor.py`

Your task:
- locate **every** terminal close path
- ensure **all final trade closures** call one common post-close hook
- ensure that hook emits the learning payload exactly once per fully closed trade

Implement a single canonical function, for example:
- `on_trade_closed_for_learning(...)`

This function should:
- validate payload completeness
- normalize outcome fields
- call `lm_update(...)`
- persist updated state if needed
- emit structured trace logs

Important:
- partial exits must **not** be counted as full completed trades unless the position is actually closed
- full close after partials must still emit exactly one final learning event
- scratch / micro / timeout / BE / trail exits must all map into explicit normalized terminal outcomes

---

### 3. Separate exit accounting from learning accounting
The logs show many exit audit counters, but learning still looks dead.
That suggests exit telemetry and learning telemetry are not using the same truth source.

Fix this by defining a canonical closed-trade object/schema.

Create or normalize a final trade record containing at minimum:
- `trade_id`
- `symbol`
- `side`
- `regime`
- `entry_price`
- `exit_price`
- `opened_at`
- `closed_at`
- `duration_s`
- `gross_pnl`
- `fees`
- `net_pnl`
- `return_pct`
- `exit_reason_raw`
- `exit_reason_normalized`
- `was_partial_sequence`
- `was_timeout`
- `was_scratch`
- `was_trail`
- `was_tp`
- `was_sl`
- `features_active`
- `score`
- `ws`
- `p`
- `ev_at_entry`

Then use this same canonical record for:
- persistence,
- learning,
- dashboard summary,
- exit audit,
- learning monitor.

Do not allow each subsystem to infer outcome differently from raw position state.

---

### 4. Fix the “NO LEARNING SIGNAL DETECTED” logic
This line is currently misleading because trades are clearly closing.

Rewrite the logic so that the message reflects the true condition.

Correct behavior:
- if no trade closed in cycle: say so explicitly
- if trade closed but learning hook did not run: error/warn with reason
- if trade closed and learning ran: print success counters
- if learning ran but state unchanged: print why (e.g. duplicate, invalid payload, protected cold-start rule)

Add cycle-level counters:
- `closed_trades_this_cycle`
- `learning_updates_this_cycle`
- `learning_update_failures_this_cycle`
- `duplicate_learning_events_this_cycle`
- `persist_writes_this_cycle`

Then print a compact line such as:
- `[LEARNING_PIPELINE] cycle closed=1 updated=1 persisted=1 dup=0 fail=0`

---

### 5. Audit persistence / hydrate correctness
We need to prove learning survives restarts.

Inspect current persistence of:
- pair/regime stats
- convergence values
- feature stats
- bandit values
- model state / advice / meta state

Tasks:
- identify exactly where learning state is written
- identify exactly where it is reloaded on boot
- ensure field names match between write/read paths
- ensure no silent fallback overwrites restored state with zeros/defaults
- ensure missing Redis does not wipe learning if Firestore is canonical (or vice versa)

Add startup/reload logs like:
- `[LM_HYDRATE] loaded pairs=13 features=8 source=firestore`
- `[LM_HYDRATE] loaded BTCUSDT_BULL_TREND n=10 ev=0.0003 bandit=0.431`

Add validation guards:
- if hydrated state is empty but persisted trades exist, warn loudly
- if reload default-values overwrite richer persisted state, fail loudly in logs

---

### 6. Fix convergence/reporting semantics
Current logs show contradictory signals:
- “KALIBROVAN ✓ 100% (103 obchodu celkem)”
- but most pair/regime entries still show `conv:-- (n/20)` or `conv:0.0`

That suggests mixed definitions of convergence.

Implement two explicitly separate metrics:
1. **global calibration maturity**
   - based on total completed trades or global evidence
2. **pair/regime convergence**
   - based on local sample size and possibly stability

Do not label the whole system “calibrated 100%” if local pair/regime convergence is still mostly immature.

Rename/report clearly, for example:
- `Global calibration: READY`
- `Local pair convergence: PARTIAL`

And for each pair/regime:
- `conv_progress = min(n / target_n, 1.0)`
- optional `conv_score` if you also include stability/variance logic

But the display must not flatten everything to zero unless that is truly intended.

---

### 7. Fix suspicious feature reporting
Current feature report shows every feature at `59%`:
- bounce 59
- pullback 59
- mom 59
- wick 59
- breakout 59
- trend 59
- is_weekend 59
- vol 59

That is highly suspicious.

Audit the feature-stat calculation path.

Check for these bugs:
- shared accumulator reused for all features
- default fallback copied into every feature
- wrong denominator
- report loop reading aggregate WR instead of per-feature WR
- feature key normalization bug
- stale cached object reused across keys

Fix so each feature prints its own true stats:
- activations
- wins
- losses
- WR
- optional expectancy

If data is insufficient, print `insufficient_data`, not fake equal values.

---

### 8. Unify runtime version reporting
Current logs contain mixed markers from multiple versions.

Do not attempt a large architecture change here, but do enough to prove what code is actually running.

Implement a single canonical runtime version source, e.g.:
- `src/core/version.py`

Expose:
- engine version string
- git commit hash if available
- feature flags / patch flags

At boot print exactly once, clearly:
- `[BOOT] V10.13x commit=<hash> features=[...]`

Also make all major subsystems reference the canonical version helper instead of hardcoded strings where practical.

If full replacement is too invasive for now, at minimum add boot-time proof of actual runtime version and identify remaining hardcoded legacy labels.

---

## Constraints
- Preserve existing live bot behavior unless the behavior is clearly incorrect
- No speculative optimization tuning yet
- No threshold tuning first
- No strategy redesign first
- No removal of EV, bandit, coherence, or exit audit systems
- Prioritize correctness, observability, and exact-once learning semantics

---

## Deliverables

### A. Code changes
Implement the fixes directly in code.

### B. Root cause summary
Provide a concise summary:
- what was broken
- why logs were misleading
- which exact paths were not connected or were inconsistent
- what was changed

### C. Proof checklist
After implementation, provide a checklist against these acceptance criteria:

1. **Close reaches learning**
   - one real closed trade produces one learning update

2. **Exact-once semantics**
   - same closed trade does not double-update learning

3. **Persistence works**
   - learning state is written and later reloaded

4. **Reporting reflects truth**
   - no false `NO LEARNING SIGNAL DETECTED` when a close happened

5. **Convergence semantics are clear**
   - global maturity and local pair convergence are separated

6. **Feature stats are not fake-flat**
   - per-feature stats differ unless data truly makes them equal

7. **Runtime version is provable**
   - boot log shows canonical version/commit

### D. Minimal validation plan
Give exact log lines / runtime signals to verify after deployment.

---

## Suggested implementation order
1. find all close/finalize paths
2. add canonical post-close learning hook
3. add structured lifecycle logs/counters
4. fix misleading “no learning signal” reporting
5. audit persistence/hydration path
6. fix convergence semantics
7. fix feature reporting
8. unify runtime version reporting

---

## Important coding rules
- Prefer small helper functions over giant rewrites
- Reuse existing state objects where safe
- Do not invent fake data to satisfy UI/reporting
- If a metric cannot be computed reliably, expose `unknown` / `insufficient_data`
- Use deterministic logic only
- Keep logging compact but explicit

---

## Expected end state
After your patch, runtime should make it obvious whether learning is actually functioning.

A healthy example should look conceptually like:
- trade closes
- close normalized to canonical terminal record
- learning hook runs exactly once
- `lm_update` logs applied mutation
- state persistence succeeds
- next render shows changed pair/regime stats
- startup after restart hydrates same state back
- no misleading “no learning signal detected” line

---

## Final instruction
Apply the changes directly and then provide:
1. root cause,
2. modified files,
3. exact acceptance criteria status,
4. post-deploy log lines I should expect.
