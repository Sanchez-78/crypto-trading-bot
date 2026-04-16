# Claude Code Prompt — CryptoMaster V10.13b FAST_FAIL / OFI Over-Block Fix

Apply an incremental patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove core protections unless explicitly converted into bounded soft penalties below.
Patch only the real active runtime integration points.

## GOAL

The system is no longer primarily broken by Redis or fake STALL timestamps.
It is now operational but heavily over-filtered.

Live evidence now shows:

- bot has historical trades and open positions
- watchdog/self-heal runs on realistic idle values
- but new live signal flow is still strongly suppressed

Current dominant block reasons from live runtime:

- `FAST_FAIL`: 6683
- `OFI_TOXIC`: 2465
- `SKIP_SCORE`: 185

This means:
- `SKIP_SCORE` is no longer the main blocker
- the true upstream killers are now `FAST_FAIL` and `OFI_TOXIC`

Your task is to reduce over-blocking while preserving safety.

---

## LIVE EVIDENCE SUMMARY

Current live state includes:

- 34 trades completed
- 2 open positions
- winrate around 72.4%
- profit slightly negative
- exits are still timeout-heavy (~83% timeout)
- live cycle snapshots show:
  - `FAST_FAIL` dominating
  - `OFI_TOXIC` second
  - `SKIP_SCORE` much smaller
- dashboard/status still appears to show suspicious threshold reporting such as:
  - `EV prah 0.000`

This patch is NOT about STALL or Redis anymore.
It is about reducing upstream over-blocking and improving observability.

---

## REQUIRED OUTCOME

After this patch:

1. `FAST_FAIL` should stop acting as an over-aggressive hard-kill for most borderline setups.
2. `OFI_TOXIC` should remain protective, but only hard-block truly toxic cases.
3. More setups should survive to later gates in a bounded way.
4. Dashboard/live logs must show real active thresholds and dominant block reasons.
5. Safety protections must remain intact.

---

# TARGET FILES TO INSPECT AND PATCH

At minimum inspect and patch the real active code among:

- `src/services/signal_generator.py`
- `src/services/signal_engine.py`
- `src/services/signal_filter.py`
- `src/services/ofi_guard.py`
- `src/services/realtime_decision_engine.py`
- `src/services/trade_filter.py`
- `src/services/decision_engine.py`
- `bot2/main.py`
- any live dashboard/status file that prints `EV prah 0.000`

Patch only the files actually responsible for live blocking and display.

---

## TASK 1 — IDENTIFY THE REAL `FAST_FAIL` SOURCE

Find the exact live code path that produces `FAST_FAIL`.

For that source, determine:
- what condition triggers it
- whether it is pre-signal, pre-RDE, or post-RDE
- whether it is currently hard reject only
- whether it overlaps with other guards redundantly

Return that mapping in your explanation.

### Required change
Convert `FAST_FAIL` from a broad hard reject into one of these bounded behaviors:

### Preferred behavior
- truly catastrophic cases remain hard reject
- borderline cases become soft penalties:
  - confidence reduction
  - score reduction
  - size reduction
  - delayed downstream gating

For example conceptually:
```python
if catastrophic_fast_fail:
    reject("FAST_FAIL_HARD")
elif borderline_fast_fail:
    apply score multiplier
    apply size multiplier
    reason = "FAST_FAIL_SOFT"
else:
    continue
```

Do NOT use this exact code blindly.
Adapt to the real architecture.

---

## TASK 2 — SOFTEN `OFI_TOXIC` WITHOUT REMOVING IT

`OFI_TOXIC` is the second-largest blocker.
Keep protection, but stop killing too many borderline signals.

### Required behavior
- only strong adverse OFI with clearly toxic flow should hard reject
- moderate adverse OFI should become:
  - score penalty
  - size penalty
  - optional warning / reason code
- benign or small adverse OFI should not kill the signal

### Acceptable structure
```python
if extreme_ofi_toxic:
    reject("OFI_TOXIC_HARD")
elif moderate_ofi_toxic:
    score *= 0.80
    size_mult *= 0.50
    reason = "OFI_TOXIC_SOFT"
else:
    pass
```

Again:
- adapt to the real code
- do not remove OFI logic
- do not make it permissive enough to become dangerous

---

## TASK 3 — ADD REASON SPLIT BETWEEN HARD AND SOFT BLOCKS

Right now block counts likely collapse too much into broad labels.

After patching:
- hard rejects should have explicit reasons like:
  - `FAST_FAIL_HARD`
  - `OFI_TOXIC_HARD`
- softened cases should use:
  - `FAST_FAIL_SOFT`
  - `OFI_TOXIC_SOFT`

This is important so future logs show whether the patch truly reduced hard kills.

If existing metrics system only supports one string reason, adapt the nearest compatible implementation.

---

## TASK 4 — FIX LIVE THRESHOLD DISPLAY

Current live status shows suspicious values like:
- `EV prah 0.000`

Patch the live dashboard/status layer to show the threshold from the actual active decision path.

At minimum show:
- real EV threshold
- real score threshold
- unblock mode on/off
- dominant block reason this cycle
- candidate count / passed count

The displayed threshold must come from the same live code path used by actual decisions.

No placeholder or stale display values.

---

## TASK 5 — ADD COMPACT LIVE BLOCK SUMMARY

At end of each live cycle, print one compact summary line such as:

```python
print(
    f"[V10.13b] generated={generated} passed={passed} executed={executed} "
    f"top_block={top_block} fast_fail={fast_fail_count} "
    f"ofi_hard={ofi_hard_count} ofi_soft={ofi_soft_count} "
    f"ev_thr={ev_thr:.3f} score_thr={score_thr:.3f}"
)
```

Use actual variables from the live runtime path.

Goal:
Make it obvious whether:
- FAST_FAIL is still dominant
- OFI is still dominant
- more signals are reaching downstream gates
- thresholds are realistic

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
- emergency hard rejects for genuinely dangerous setups

This patch is about:
- reducing redundant early kills
- converting borderline hard rejects into bounded soft penalties
- exposing real reasons
- improving live pass-through modestly, not recklessly

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. `FAST_FAIL` hard rejections materially decrease.
2. `OFI_TOXIC` hard rejections materially decrease, with some cases converted to soft penalties.
3. More live candidates survive upstream gating.
4. Dashboard/status no longer shows fake threshold values like `EV prah 0.000`.
5. Logs clearly distinguish hard vs soft block reasons.
6. Safety protections remain intact.
7. Live pass-through improves without obvious uncontrolled overtrading.

---

## RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. exact source mapping for `FAST_FAIL` and `OFI_TOXIC`
4. short root cause summary
5. short expected runtime behavior after patch
6. any assumptions if real call graph differs

Do NOT return pseudo-code only.
Return real integrated Python code.
