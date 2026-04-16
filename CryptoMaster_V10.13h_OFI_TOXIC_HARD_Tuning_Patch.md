# Claude Code Prompt — CryptoMaster V10.13h OFI_TOXIC_HARD Tuning Patch

Apply an incremental patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove core protections.
Patch only the real active runtime integration points responsible for OFI hard-blocking and OFI-based sizing/score penalties.

## GOAL

The system is now operational and improving:
- warmup fallback works
- live candidates are generated
- exits are improving
- profit factor has moved above 1.0
- expectancy is slightly positive

However, one major live hard blocker remains visible:

- `OFI_TOXIC_HARD`

Recent logs still show `OFI_TOXIC_HARD` accumulating as the dominant explicit hard block reason in some cycles.

This patch is about narrowing true hard OFI rejection to only genuinely toxic cases, while converting moderate OFI adversity into bounded soft penalties.

---

## CONFIRMED LIVE EVIDENCE

Recent live logs show:

- live trading is functioning
- signals are being generated
- thresholds look realistic
- exit behavior improved after V10.13f / V10.13g
- but `OFI_TOXIC_HARD` still appears as a meaningful blocker
- one recent snapshot showed:
  - `"block_reasons": { "OFI_TOXIC_HARD": 63 }`

This means:
- OFI protection is still actively shaping flow
- but it may still be too aggressive for borderline setups
- the next tuning target is OFI discrimination quality

---

## ROOT CAUSE HYPOTHESIS

One or more of these are true:

1. OFI hard threshold is too low
2. OFI is being measured on noisy short-term flow and overreacts
3. moderate adverse OFI is being treated as hard-toxic instead of soft-risk
4. OFI hard rejection overlaps redundantly with score/edge filters
5. some OFI-hurt trades could survive safely with score/size penalties instead of full rejection

---

## REQUIRED OUTCOME

After this patch:

1. `OFI_TOXIC_HARD` should become more selective.
2. Moderate adverse OFI should become `OFI_TOXIC_SOFT` or equivalent bounded penalty.
3. Hard OFI rejection should remain for genuinely toxic flow.
4. Live logs and metrics must clearly show hard vs soft OFI outcomes.
5. Safety protections must remain intact.

---

# TARGET FILES TO INSPECT AND PATCH

At minimum inspect and patch the real active code among:

- `src/services/ofi_guard.py`
- `src/services/realtime_decision_engine.py`
- `src/services/signal_filter.py`
- `src/services/signal_generator.py`
- `src/services/trade_filter.py`
- `src/services/decision_engine.py`
- `bot2/main.py`
- any dashboard/live status file that aggregates block reasons

Patch only the files actually responsible for active OFI decisioning and OFI reporting.

---

## TASK 1 — MAP THE REAL LIVE OFI PATH

Identify the real active live OFI flow:

from market/order-flow input →
OFI measurement →
threshold comparison →
hard reject or soft penalty →
downstream score/size impact →
logging/reporting

Return this mapping clearly in your explanation.

Important:
We need the actual production path, not an assumed one.

---

## TASK 2 — FIND THE TRUE `OFI_TOXIC_HARD` TRIGGER

Determine:

- what exact OFI statistic is used
- what threshold currently creates hard rejection
- whether sign/direction handling is correct
- whether thresholding is regime-aware
- whether hard OFI rejection is being applied too early
- whether the same trade would already be filtered later by score/EV

### Required change
Keep true hard rejection for genuinely toxic OFI.

But convert borderline OFI cases into bounded soft penalties instead of hard kills.

Example target behavior:
```python
if extreme_adverse_ofi:
    reject("OFI_TOXIC_HARD")
elif moderate_adverse_ofi:
    score *= 0.85
    size_mult *= 0.60
    reason = "OFI_TOXIC_SOFT"
else:
    pass
```

Do NOT blindly paste that exact structure.
Adapt to the real implementation.

---

## TASK 3 — MAKE OFI THRESHOLDING MORE SELECTIVE

If the current hard threshold is too aggressive, tune it upward or make it conditional.

Acceptable improvements include:
- requiring stronger adverse OFI before hard reject
- using regime-aware OFI tolerance
- using confidence/score/edge context before deciding hard vs soft
- applying hard OFI only when both OFI and another toxicity condition agree

Do NOT remove OFI protection.
The goal is:
- narrower hard blocking
- more soft degradation
- preserved safety

---

## TASK 4 — ADD EXPLICIT HARD VS SOFT OFI REASONS

After patching, the system should distinguish clearly between:

- `OFI_TOXIC_HARD`
- `OFI_TOXIC_SOFT`

If useful, you may add finer-grained compatible labels such as:
- `OFI_TOXIC_EXTREME`
- `OFI_TOXIC_SOFT`
- `OFI_TOXIC_SIZE_ONLY`

But keep the naming clear and minimal.

This is required so future logs show whether hard rejections actually decreased.

---

## TASK 5 — SURFACE OFI IMPACT IN LIVE SUMMARY

Patch reporting/dashboard so it reflects active OFI behavior.

At minimum expose:
- OFI hard count
- OFI soft count
- whether OFI penalties are active this cycle
- real current thresholds if practical

Example summary line:
```python
print(
    f"[V10.13h OFI] hard={ofi_hard_n} soft={ofi_soft_n} "
    f"ev_thr={ev_thr:.3f} score_thr={score_thr:.3f}"
)
```

Use actual live variables.

Goal:
Make it obvious whether:
- OFI hard still dominates
- OFI soft is now absorbing borderline cases
- pass-through improved safely

---

## TASK 6 — KEEP THESE SAFETY PROPERTIES

Do NOT remove:
- hard stop loss
- spread checks
- RR validation
- risk manager protections
- exposure / max position controls
- watchdog/self-heal
- audit/execution checks
- emergency hard exits / catastrophic filters

This patch is about:
- narrowing OFI hard rejection
- converting moderate OFI adversity into bounded penalties
- improving observability of OFI decisions
- improving candidate survival where safe

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. `OFI_TOXIC_HARD` becomes more selective over time.
2. Some borderline OFI cases are visibly converted into `OFI_TOXIC_SOFT`.
3. Safety protections remain intact.
4. Live logs clearly separate hard vs soft OFI outcomes.
5. Pass-through improves without obvious uncontrolled degradation.

---

## RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. exact live OFI path mapping
4. short root cause summary
5. short expected runtime behavior after patch
6. any assumptions if real call graph differs

Do NOT return pseudo-code only.
Return real integrated Python code.
