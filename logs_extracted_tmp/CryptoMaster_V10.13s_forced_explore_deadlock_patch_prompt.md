# CryptoMaster V10.13s — Forced-Explore Deadlock / Idle-Unblock Patch Prompt

## ROLE
You are a senior quant/backend engineer working inside an existing live Python crypto trading bot.  
Your job is **not** to redesign the whole bot.  
Your job is to **safely remove the current idle deadlock** while preserving existing architecture, telemetry, and learning flow.

Work incrementally.  
Prefer minimal high-impact patches.  
Do not break existing logic outside the described blockers.

---

## CURRENT VERIFIED PROBLEM

The bot is no longer primarily blocked by `ECONOMIC_GATE`.  
That was partially improved.

The current dominant blocker is:

- `FORCED_EXPLORE_GATE`
- repeated `FORCED_EXPLORE_BLOCKED`
- root reason: `spread_quality:spread_too_flat=0.0047`

Observed runtime pattern:

1. No normal trades pass.
2. Idle / stall grows.
3. Watchdog / self-heal boosts exploration.
4. Forced signal is generated.
5. Forced signal is blocked by FE gate / spread flatness.
6. No trade opens.
7. Idle grows again.
8. Loop repeats indefinitely.

This is now the main deadlock.

---

## VERIFIED EVIDENCE FROM LOGS

### Runtime symptoms
- `Posledni obchod 3h 22m zpet`
- `STALL > 900s`
- `SELF_HEAL: STALL (no trades 900s) → boosting exploration`
- `[WATCHDOG] No trades for 600s → boosting exploration`
- `[WATCHDOG] Critical idle (15min) → enabling micro-trades`

### But recovery still fails
- `decision=SKIP_FE_GATE ... FORCED_EXPLORE_BLOCKED (spread_quality:spread_too_flat=0.0047)`

### Dominant block reason
- `block_reasons: {"FORCED_EXPLORE_GATE": 4882/4883, "QUIET_RSI": 1}`

### Audit still fully blocked
- `Passed to execution: 0`
- `Blocked: 20`
- `[CI FAIL] blocked_ratio=1.000 > 0.80`

### Additional inconsistencies still present
- Dashboard PF: `0.65x`
- Economic PF: `4.15`
- Audit lines show `emergency=True`
- Summary says `emergency mode : 0`

---

## PRIMARY OBJECTIVE

Fix the system so that:

1. **Idle recovery path can actually open some controlled trades**
2. **Forced-explore is no longer self-contradictory**
3. **Watchdog escalation changes admission policy, not only signal generation**
4. **Audit clearly separates normal / forced / recovery outcomes**
5. **Telemetry is consistent and canonical**

Do this with **minimal, controlled, production-safe changes**.

---

## HARD CONSTRAINTS

- Preserve existing architecture and event flow.
- Keep all existing logs unless replacing them with better canonical logs.
- Do not delete economic gate.
- Do not delete FE gate.
- Do not globally relax all filters.
- Recovery path must remain **small-size and bounded-risk**.
- Do not increase Firestore read/write cost materially.
- Prefer config/constants over magic numbers buried in code.
- Keep changes modular and easy to revert.

---

## WHAT TO IMPLEMENT

# 1) SPLIT ADMISSION POLICY BY TRADE INTENT

Create explicit admission behavior for:
- normal trade
- forced explore trade
- idle recovery / micro trade

Current problem: forced trades appear to use gate logic that makes idle recovery impossible.

## Required behavior
Normal trades remain strict.

Forced / recovery trades must:
- use smaller size
- use shorter hold
- use tighter risk budget
- allow flatter spreads than normal flow
- remain bounded by a hard max spread
- be rate-limited

### Target rule
A gate that protects normal flow must **not fully kill** the recovery flow it is supposed to unblock.

---

# 2) ADD SEPARATE SPREAD POLICY FOR FORCED / IDLE PATHS

Current blocker is repeatedly:
- `spread_too_flat=0.0047`

This is wrong for idle-unblock behavior.  
Flat spread should not hard-block the very mechanism designed to break inactivity.

Implement separate logic similar to:

```python
def evaluate_spread_policy(ctx):
    spread_bps = ctx.spread_bps
    forced = ctx.is_forced_explore
    micro = ctx.is_micro_trade
    idle_sec = ctx.idle_seconds

    # strict normal flow
    if not forced and not micro:
        if spread_bps > NORMAL_MAX_SPREAD_BPS:
            return block("spread_too_wide")
        if spread_bps < NORMAL_MIN_SPREAD_BPS:
            return block("spread_too_flat")
        return allow()

    # forced flow before hard idle
    if forced and idle_sec < IDLE_HARD_SEC:
        if spread_bps > FORCED_MAX_SPREAD_BPS:
            return block("forced_spread_too_wide")
        if spread_bps < FORCED_MIN_SPREAD_BPS:
            return block("forced_spread_too_flat")
        return allow()

    # forced flow during hard idle
    if forced and idle_sec >= IDLE_HARD_SEC:
        if spread_bps > FORCED_HARD_IDLE_MAX_SPREAD_BPS:
            return block("forced_idle_spread_too_wide")
        # intentionally do NOT hard block flat spread here
        return allow_with_flag("flat_spread_tolerated")

    # micro-trade path
    if micro:
        if spread_bps > MICRO_MAX_SPREAD_BPS:
            return block("micro_spread_too_wide")
        return allow_with_flag("micro_relaxed_spread")

    return allow()
```

Important:
- do **not** blindly copy numbers above
- infer numbers from current bot behavior/config
- keep them configurable
- keep canonical log reasons

---

# 3) WATCHDOG / SELF-HEAL MUST ESCALATE POLICY, NOT JUST SIGNAL COUNT

Current behavior:
- watchdog boosts exploration
- self-heal boosts exploration
- no actual admission rules materially change enough
- deadlock remains

Implement staged idle escalation:

## Suggested modes
- `NORMAL`
- `UNBLOCK_SOFT`
- `UNBLOCK_MEDIUM`
- `UNBLOCK_HARD`

### Example transition
- `idle >= 600s` → `UNBLOCK_SOFT`
- `idle >= 1200s` → `UNBLOCK_MEDIUM`
- `idle >= 1800s` → `UNBLOCK_HARD`

## Required meaning of escalation
Each level must modify **admission + execution parameters**, not just exploration probability.

### UNBLOCK_SOFT
- mildly relax score threshold
- allow top forced candidates only
- size reduction active

### UNBLOCK_MEDIUM
- relax forced flat-spread blocking
- shorten hold time
- enable faster BE / scratch behavior

### UNBLOCK_HARD
- allow micro-trades
- disable flat-spread hard block for forced/micro paths
- cap attempts per time window
- smallest position sizing

---

# 4) FORCED / RECOVERY TRADES MUST BE SMALL AND FAST

Do not unblock with normal-size trades.

Required forced/recovery execution profile:
- size multiplier reduced
- shorter max hold
- earlier break-even
- faster scratch exit
- lower TP target allowed
- lower capital impact
- frequency capped

Illustrative direction only:

```python
if ctx.is_forced_explore:
    size_mult *= 0.25
    max_hold_sec = min(max_hold_sec, 90)
    tp_mult = min(tp_mult, FORCED_TP_CAP)
    sl_mult = min(sl_mult, FORCED_SL_CAP)
    force_early_be = True
    scratch_after_sec = min(scratch_after_sec, 30)

if ctx.is_micro_trade:
    size_mult *= 0.15
    max_hold_sec = min(max_hold_sec, 60)
    force_early_be = True
    use_fast_scratch = True
```

Make this production-safe and configurable.

---

# 5) ADD RATE LIMITS TO RECOVERY PATH

To avoid runaway churn:

Implement rate limits for forced and micro entries.

Examples:
- max forced entries per symbol per 10 min
- max total forced entries per 15 min
- max micro entries globally while idle mode active
- cooldown after N failed forced attempts

Need canonical telemetry for:
- `forced_attempts`
- `forced_passed`
- `forced_blocked`
- `forced_opened`
- `micro_attempts`
- `micro_opened`

---

# 6) SPLIT AUDIT INTO NORMAL / FORCED / RECOVERY BRANCHES

Current audit summary is too coarse:
- `Passed to execution: 0`
- `Blocked: 20`

This hides whether:
- normal flow is dead
- recovery flow is dead
- both are dead

Implement audit/report split:

- `normal_candidates`
- `normal_passed`
- `normal_blocked`
- `forced_candidates`
- `forced_passed`
- `forced_blocked`
- `recovery_candidates`
- `recovery_passed`
- `recovery_blocked`

Also split top block reasons by branch.

Goal: audit must reveal **which path is failing**.

---

# 7) FIX TELEMETRY INCONSISTENCIES

## 7a) Emergency mode inconsistency
Observed:
- per-trade lines: `emergency=True`
- summary: `emergency mode : 0`

Need a single canonical source for emergency state in summaries.

## 7b) Profit factor inconsistency
Observed:
- dashboard PF = `0.65x`
- economic PF = `4.15`

These must be reconciled.
Likely one path:
- excludes scratch/flat trades
- or uses different sample window
- or uses gross vs net
- or uses different authoritative source

Fix by defining:
- canonical PF formula
- sample universe
- whether scratch/flat included/excluded
- whether gross or net pnl
- one authoritative computation function reused by dashboard + economic layer

Do not leave multiple conflicting PFs unless explicitly labeled differently.

---

# 8) CANONICAL BLOCK REASONS

Current logs mix:
- `SKIP_ECONOMIC`
- `SKIP_FE_GATE`
- `FORCED_EXPLORE_BLOCKED`
- watchdog/self-heal narratives

Standardize block reason output so each rejected candidate has:
- branch (`normal|forced|micro`)
- stage (`economic|rde|fe|exec_quality|risk|timeout|spread`)
- machine-readable reason
- optional human-readable explanation

Recommended structure:

```python
{
  "branch": "forced",
  "stage": "fe_gate",
  "reason": "spread_too_flat",
  "value": 0.0047,
  "threshold": 0.0050,
  "idle_sec": 11428,
  "mode": "UNBLOCK_HARD"
}
```

---

# 9) PRESERVE SAFETY OF NORMAL FLOW

Very important:
- normal production flow must remain strict
- only recovery flow gets controlled relaxation
- do not globally weaken the strategy

That means:
- normal trade thresholds stay mostly untouched
- relaxations are scoped by branch + idle state
- size/risk reductions compensate for relaxed admission

---

# 10) ADD MINIMAL TESTS / SANITY CHECKS

Add focused tests or replay assertions for:

## Spread policy
- normal trade blocked on too-flat spread
- forced trade can pass under hard idle even when normal would block
- micro trade blocked only on too-wide spread

## Escalation policy
- idle 0 → NORMAL
- idle 700 → UNBLOCK_SOFT
- idle 1300 → UNBLOCK_MEDIUM
- idle 1900 → UNBLOCK_HARD

## Audit split
- branch counts appear correctly
- block reasons correctly attributed

## Telemetry consistency
- emergency summary reflects actual candidate-level usage
- PF source is identical between summary modules

---

## IMPLEMENTATION ORDER

1. Identify actual files/functions responsible for:
   - forced explore gating
   - spread_quality evaluation
   - watchdog/self-heal escalation
   - audit summary
   - PF / emergency summary generation

2. Add branch-aware context flags:
   - `is_forced_explore`
   - `is_micro_trade`
   - `idle_mode`
   - `idle_seconds`

3. Implement separate spread/admission policy by branch.

4. Implement idle escalation modes with explicit policy deltas.

5. Add forced/micro risk profile reductions.

6. Add rate limiting for forced/micro entries.

7. Split audit outputs by branch.

8. Fix PF and emergency summary inconsistencies.

9. Run replay / local audit and confirm:
   - not all recovery candidates are hard-blocked
   - some recovery candidates pass
   - size remains very small
   - summary metrics are internally consistent

---

## SUCCESS CRITERIA

Patch is successful when logs show all of the following:

### Required
- idle recovery no longer loops forever with 0 openings
- `FORCED_EXPLORE_BLOCKED` is no longer near-100% for hard-idle cases
- audit no longer shows every recovery candidate blocked
- canonical summaries stop contradicting candidate-level logs
- PF is consistent across dashboard/economic summary

### Strongly preferred
- recovery trades open rarely but actually open
- recovery positions are smaller and shorter-lived than normal trades
- watchdog / self-heal produces meaningful state changes, not only repeated messages
- block reason reporting becomes more diagnostic

---

## WHAT NOT TO DO

- Do not globally disable spread checks.
- Do not remove FE gate entirely.
- Do not bypass risk engine.
- Do not increase position size to solve inactivity.
- Do not silence logs instead of fixing the root cause.
- Do not rewrite unrelated strategy modules.
- Do not hide contradictions in summary; fix them.

---

## DELIVERABLE FORMAT

Return:

### 1. Analysis
- exact root cause map
- file/function targets
- why deadlock happens

### 2. Patch plan
- ordered change list
- rationale
- rollback safety

### 3. Implementation
- concise code changes
- minimal but sufficient diffs

### 4. Validation
- expected log changes
- replay/audit results
- remaining risks

### 5. Optional improvements
Only after main fix is complete, propose additional high-ROI improvements.

---

## HIGH-ROI IMPROVEMENT IDEAS TO CONSIDER AFTER MAIN FIX

These are optional unless trivial:

### A. Recovery quota by regime
Prefer recovery trades in regimes with at least some historical signal quality.

### B. Recovery candidate ranking
Use a tiny ranker:
- coherence
- ws
- ev
- regime prior
- spread quality
to choose 1 best forced candidate instead of many weak ones.

### C. Recovery cooldown memory
If one symbol/regime repeatedly fails recovery entry, temporarily deprioritize it.

### D. Stronger telemetry
Add:
- `idle_mode`
- `recovery_branch`
- `forced_rate_limited`
- `spread_relaxed`
to cycle snapshot.

### E. Better canonical dashboard
Show separately:
- normal trade flow health
- recovery flow health
- idle-unblock activity

---

## FINAL PRIORITY ORDER

1. Fix forced-explore deadlock
2. Make watchdog escalation actually change admission policy
3. Allow small controlled recovery trades
4. Split audit by branch
5. Fix emergency summary inconsistency
6. Fix PF inconsistency
7. Then only optionally improve ranking/telemetry

---

## NOTE

The current system likely does **not** primarily suffer from “no signal generation”.  
It suffers from **recovery-path mechanical overblocking**.

So do not solve this by merely generating more signals.  
Solve it by making the recovery branch actually executable under controlled risk.
