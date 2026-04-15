# Claude Code Prompt — CryptoMaster V10.12e Deadlock Fix Patch

Apply an incremental patch to the existing Python crypto trading bot project.
Do NOT rewrite the whole project from scratch.
Do NOT simplify architecture.
Do NOT remove existing protections unless strictly necessary.
Preserve current modules, logging style, state objects, and integration points as much as possible.

Goal:
The previous V10.12d controlled-unblock patch was only partially integrated.
TIMING and OFI pressure improved, but the bot is still deadlocked:
- `0 zachyceno`
- `0 po filtru`
- `0.0% projde filtrem`
- repeated `STALL > 900s`
- repeated `NO_SIGNALS`
- `Positions: 0`

The remaining dominant blockers are now:
- `SKIP_SCORE`
- `LOSS_CLUSTER`

This means unblock logic exists in code, but is not actually wired into the final decision path strongly enough.

Implement a precise V10.12e follow-up patch that fixes the real integration bugs.

---

## OBSERVED POST-PATCH STATE

After V10.12d:
- `TIMING` is no longer the main blocker
- `OFI_TOXIC` is reduced
- but live pipeline is still dead

Observed block reasons:
- `SKIP_SCORE: 226`
- `LOSS_CLUSTER: 168`
- `OFI_TOXIC: 23`

Observed runtime:
- watchdog reports critical idle
- micro-trades / exploration are supposedly enabled
- but no entries happen
- signal pass rate remains 0%

This strongly implies:
1. unblock thresholds are not being used in the final score gate
2. adaptive cooldown reduction is not reaching the effective cluster rejection point
3. there is no guaranteed fallback path for taking bounded unblock trades
4. logs are too weak to verify adjusted decision variables

---

## REQUIRED OUTCOME

Implement **V10.12e Deadlock Fix** with these goals:

1. Ensure unblock mode is truly used inside the final decision gate.
2. Ensure score threshold actually changes during unblock mode.
3. Ensure cluster cooldown is truly shortened during idle stall.
4. Add a bounded fallback TAKE path so pipeline cannot remain at 0 forever.
5. Add decision logs that expose adjusted score, thresholds, unblock flag, cooldown state, and final reason.
6. Keep all risk protections active.
7. Preserve small sizing and rate limiting for unblock entries.

---

## PATCH REQUIREMENTS

### 1) Fix score gate wiring

Find the real final score rejection path.
It likely looks similar to:

```python
if score < SCORE_THRESHOLD:
    return reject("SKIP_SCORE")
```

Replace static threshold usage with actual unblock-aware threshold resolution:

```python
threshold = current_score_threshold(state)

if score < threshold:
    return reject("SKIP_SCORE")
```

Requirements:
- use the final score value actually used for decisions
- use the real state object
- do not leave parallel old threshold checks active elsewhere
- if multiple score gates exist, consolidate or ensure all use the same unblock-aware threshold

Important:
The current code appears to define adaptive thresholds but not fully apply them to the true final decision point.

---

### 2) Ensure unblock mode is active inside decision flow

The existence of watchdog messages is not enough.
Make sure `is_unblock_mode(state)` influences the actual decision pipeline, not just monitoring.

At minimum, unblock mode must affect:
- score threshold
- EV threshold
- cooldown behavior
- final acceptance fallback
- size multiplier

If there is a split between:
- feature generation
- candidate generation
- final gate
- executor

then unblock state must be passed into the real final gate.

Do not leave unblock logic isolated in helper functions that never affect real decisions.

---

### 3) Fix LOSS_CLUSTER integration

Current logs show `LOSS_CLUSTER` still blocking too much, even in prolonged stall.

This means the adaptive cooldown helper is likely not reaching the actual reject logic.

Find the true cluster reject condition and ensure idle reduction is applied before rejection.

Implement behavior equivalent to:

```python
cooldown_remaining = compute_cluster_cooldown_remaining(...)

if is_unblock_mode(state):
    cooldown_remaining = min(cooldown_remaining, 120)
```

Then use the adjusted remaining cooldown in the reject decision.

If architecture is based on absolute timestamps:
- shorten the effective lockout window during unblock mode
- do not merely compute a shorter theoretical cooldown that is never used

Requirements:
- during critical idle, no symbol should remain locked for many minutes
- preserve cluster protection
- keep bounded cooldown, do not fully remove it

If safer in your architecture:
- in unblock mode, allow a cluster-blocked signal to pass only if EV and score are strong enough, while still applying micro-size

That is acceptable, but must remain bounded and logged.

---

### 4) Add bounded unblock fallback TAKE path

This is the most important deadlock breaker.

If unblock mode is active, add a final bounded fallback acceptance path for signals that are not great, but good enough to prevent infinite deadlock.

Implement logic equivalent to:

```python
if is_unblock_mode(state):
    if ev >= 0.020 and score >= 0.110:
        return take_unblock("UNBLOCK_FALLBACK")
```

Requirements:
- only during unblock mode
- must still respect:
  - spread checks
  - RR validation
  - exposure limits
  - max unblock trades/hour
  - max unblock positions
- must use reduced position size
- must be clearly logged as fallback unblock entry

This fallback is specifically to ensure the system cannot stay permanently at 0 pass-through when watchdog already declares pipeline dead.

Do NOT make this fallback unconditional.
Do NOT bypass risk engine.

---

### 5) Preserve unblock size limits

Keep existing unblock size reduction behavior, such as:
- 0.25x when critically idle
- 0.35x in lighter unblock conditions

Ensure fallback unblock entries also use reduced size.

Verify final size path includes:
- base size
- existing risk multipliers
- OFI penalty if any
- unblock size multiplier

Do not allow fallback trades to open at full size.

---

### 6) Preserve unblock rate limiting

Keep and verify:
- max 6 unblock trades per hour
- max 2 concurrent unblock positions

Ensure the fallback unblock path is also subject to these limits.

Suggested reject reasons:
- `UNBLOCK_RATE_LIMIT`
- `UNBLOCK_POS_LIMIT`

---

### 7) Add explicit decision logging

Current logs do not expose enough detail to verify whether unblock is actually working.

Add one compact decision log line at the real final decision point showing:

- unblock mode true/false
- raw EV
- adjusted EV
- raw score
- adjusted score
- score threshold
- EV threshold
- cooldown remaining before/after adjustment
- whether fallback path was used
- size multiplier
- final decision

Example style:

```python
decision=SKIP_SCORE unblock=True ev=0.026->0.026 score=0.108->0.108 thr_score=0.120 thr_ev=0.015 cooldown=340->120 fallback=False size=0.25
```

or

```python
decision=TAKE unblock=True ev=0.021 score=0.113 thr_score=0.120 fallback=True size=0.25
```

Requirements:
- use actual final values
- avoid duplicate spammy logs
- keep one authoritative decision log line per candidate decision

---

### 8) Avoid fake threshold displays

The runtime display currently shows suspicious values like:
- `EV prah 0.000`

That is misleading if actual gating is using something else.

Fix status/dashboard output so it displays the real current thresholds:
- normal mode thresholds when normal
- unblock thresholds when unblock
- ideally also show whether unblock mode is active

This is required because current output obscures the true decision state.

---

## SAFETY RULES

Do NOT:
- remove risk guards
- remove spread checks
- remove RR validation
- remove exposure caps
- remove cooldowns entirely
- remove OFI handling entirely
- make fallback trades full size
- make fallback trades unlimited

Do:
- make unblock logic real
- break the deadlock
- keep bounded, defensive behavior

---

## EXPECTED POST-PATCH BEHAVIOR

After V10.12e:
- pipeline should no longer remain permanently at `0 po filtru`
- `SKIP_SCORE` should decrease materially
- `LOSS_CLUSTER` should no longer freeze symbols for long during critical idle
- unblock mode should actually result in a small number of accepted micro-trades
- watchdog should stop repeating infinite deadlock messages
- logs should make it obvious whether fallback is used

A healthy result is NOT massive trading.
A healthy result is:
- low but nonzero pass-through
- bounded micro-trades
- visible unblock decisions
- preserved safety limits

---

## IMPLEMENTATION TARGET

Inspect and patch the real files responsible for:
- final decision gating
- score thresholding
- EV thresholding
- cluster cooldown enforcement
- unblock mode state propagation
- final acceptance logic
- executor rate limits
- status/dashboard threshold display
- decision logging

Most likely at least:
- realtime_decision_engine.py
- signal_filter.py
- trade_executor.py
- any dashboard/status/logging file if separate

Reuse existing architecture.
Modify real integration points.
Do not add dead helper code that is never called.

---

## RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. summary of the deadlock root cause
4. summary of exactly how V10.12e fixes it
5. any assumptions where actual project names differ

Do not return pseudo-code only.
Return real modified Python code integrated into the existing project.
