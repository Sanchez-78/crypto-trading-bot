# Claude Code Prompt — CryptoMaster V10.13c SKIP_SCORE / OFI_HARD Calibration Patch

Apply an incremental patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove core protections unless explicitly converted into bounded soft penalties below.
Patch only the real active runtime integration points now identified from live logs.

## GOAL

The system is now operational, but still weak and overly restrictive in live mode.

Current live evidence shows:

- `FAST_FAIL` is no longer the dominant blocker
- dominant live block reasons are now:
  - `SKIP_SCORE`
  - `OFI_TOXIC_HARD`
- `STALL` values are realistic and no longer fake
- bot has large historical trade volume (`1309` trades), but:
  - profit factor is only `0.73x`
  - expectancy is slightly negative
  - last trade may be 14h+ ago
- self-heal activates after real inactivity
- dashboard still shows suspicious threshold display:
  - `EV prah 0.000`
- audit/live observability still looks partially inconsistent

This patch is NOT about Redis or fake timestamps anymore.
It is about calibrating the remaining live blockers and fixing threshold observability.

---

## LIVE EVIDENCE SUMMARY

Recent live logs show:

- `block_reasons` shifted from:
  - `FAST_FAIL`, `OFI_TOXIC`, `SKIP_SCORE`
to:
  - `SKIP_SCORE`
  - `OFI_TOXIC_HARD`
- real STALL values around:
  - `929s`, `939s`, `949s`
- repeated:
  - `SELF_HEAL: STALL`
  - `SELF_HEAL: NO_SIGNALS`
- dashboard still reports:
  - `EV prah 0.000`
- live trading history exists and is large:
  - `1309` trades
  - winrate ~`54.6%`
  - PF ~`0.73x`
  - expectancy ~slightly negative

This means:
- runtime path is alive
- upstream over-blocking was partially improved
- remaining blockers are now narrower and measurable

---

## REQUIRED OUTCOME

After this patch:

1. `SKIP_SCORE` should stop over-killing borderline viable candidates.
2. `OFI_TOXIC_HARD` should remain only for truly toxic order-flow cases.
3. More candidates should survive into bounded downstream evaluation.
4. Dashboard/status must show the real active thresholds.
5. Live logs must make clear whether score gating or OFI hard-blocking dominates.
6. Safety protections must remain intact.

---

# TARGET FILES TO INSPECT AND PATCH

At minimum inspect and patch the real active code among:

- `src/services/realtime_decision_engine.py`
- `src/services/ofi_guard.py`
- `src/services/signal_filter.py`
- `src/services/signal_generator.py`
- `src/services/decision_engine.py`
- `bot2/main.py`
- any dashboard/live status file showing `EV prah 0.000`

Patch only the files actually responsible for live score gating, OFI hard blocking, and threshold display.

---

## TASK 1 — CALIBRATE `SKIP_SCORE`

Find the exact live score gate used in the active runtime path.

Determine:
- what `score` represents in the live path
- what threshold is actually used
- whether the threshold is static, unblock-aware, or stale
- whether score is being reduced redundantly by multiple upstream penalties

### Required change
Reduce over-blocking from `SKIP_SCORE` without removing the gate.

Preferred approach:
- preserve hard score floor for obviously weak setups
- soften the treatment of borderline setups
- allow more borderline cases to proceed with bounded penalties

Acceptable pattern:
```python
if score < hard_floor:
    reject("SKIP_SCORE_HARD")
elif score < soft_threshold:
    score *= 0.95
    size_mult *= 0.70
    reason = "SKIP_SCORE_SOFT"
else:
    pass
```

Use the real architecture — do not blindly paste this exact pattern.

### Important
Do NOT turn score gating off.
The goal is:
- fewer false kills
- not uncontrolled overtrading

---

## TASK 2 — CALIBRATE `OFI_TOXIC_HARD`

Find the exact active `OFI_TOXIC_HARD` source.

Determine:
- what OFI measure is being used
- what threshold triggers the hard block
- whether moderate adverse OFI is still being treated too aggressively
- whether OFI penalties overlap with other guards redundantly

### Required change
Keep truly toxic OFI as hard reject.
Convert moderate OFI into soft penalty where safe.

Acceptable pattern:
```python
if extreme_ofi:
    reject("OFI_TOXIC_HARD")
elif moderate_ofi:
    score *= 0.85
    size_mult *= 0.50
    reason = "OFI_TOXIC_SOFT"
else:
    pass
```

Again:
- adapt to the real code
- do not remove OFI safety
- do not make OFI permissive enough to become dangerous

---

## TASK 3 — EXPLICITLY SPLIT HARD VS SOFT REASONS

After patching, logs and metrics should distinguish:

- `SKIP_SCORE_HARD`
- `SKIP_SCORE_SOFT`
- `OFI_TOXIC_HARD`
- `OFI_TOXIC_SOFT`

If current metrics system can only store one reason string, adapt the nearest compatible implementation.

This is required so future validation can show:
- whether hard rejections fell
- whether soft penalties increased
- whether more signals survive downstream

---

## TASK 4 — FIX LIVE THRESHOLD DISPLAY

Current dashboard/status still shows:
- `EV prah 0.000`

Patch the live status/dashboard layer so it reports the threshold from the actual active decision path.

At minimum display:
- real EV threshold
- real score threshold
- whether unblock mode is active
- top block reason this cycle
- generated / passed / executed counts if available

Do not show stale or placeholder values.
The displayed thresholds must come from the same logic used for actual live decisions.

---

## TASK 5 — ADD COMPACT LIVE SUMMARY FOR SCORE / OFI DOMINANCE

At the end of each live cycle, add one compact summary line such as:

```python
print(
    f"[V10.13c] generated={generated} passed={passed} executed={executed} "
    f"top_block={top_block} score_hard={score_hard} score_soft={score_soft} "
    f"ofi_hard={ofi_hard} ofi_soft={ofi_soft} "
    f"ev_thr={ev_thr:.3f} score_thr={score_thr:.3f} unblock={unblock}"
)
```

Use actual live runtime variables.

Goal:
Make it obvious whether:
- score gating still dominates
- OFI hard blocking still dominates
- live thresholds are sane
- pass-through improved or not

---

## TASK 6 — KEEP THESE SAFETY PROPERTIES

Do NOT remove:
- RR validation
- spread hard checks
- exposure limits
- max positions
- cooldown protections
- risk manager
- watchdog/self-heal
- emergency hard rejects for truly dangerous setups

This patch is about:
- narrowing hard-block use
- converting borderline score/OFI cases into bounded soft penalties
- improving live observability
- improving pass-through modestly, not recklessly

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. `SKIP_SCORE` hard rejections materially decrease.
2. `OFI_TOXIC_HARD` hard rejections materially decrease or become more selective.
3. Some borderline cases are visible as soft penalties instead of hard kills.
4. Live dashboard no longer shows fake threshold values like `EV prah 0.000`.
5. Logs clearly distinguish score hard/soft and OFI hard/soft.
6. Safety protections remain intact.
7. Live pass-through improves without obvious uncontrolled degradation.

---

## RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. exact source mapping for `SKIP_SCORE` and `OFI_TOXIC_HARD`
4. short root cause summary
5. short expected runtime behavior after patch
6. any assumptions if real call graph differs

Do NOT return pseudo-code only.
Return real integrated Python code.
