# Claude Code Prompt — CryptoMaster V10.13a Audit/Live Path Divergence Fix

Apply an incremental patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove protections unless explicitly stated.
Patch only the real decision-routing and signal-generation integration points.

## GOAL

The infrastructure/runtime blockers are mostly resolved:
- Redis fallback works
- fake unix-time STALL bug is resolved
- self-heal scoping bug is resolved

But the live trading pipeline is still effectively deadlocked.

### Confirmed live evidence
Live runtime shows:
- `0 zachyceno  0 po filtru  10 blokovano  0 provedeno`
- per-symbol `zadny signal`
- repeated `NO_SIGNALS`
- cycle snapshot block reasons like:
  - `SKIP_SCORE`
  - `OFI_TOXIC`

### Confirmed audit evidence
`pre_live_audit` shows:
- many `decision=TAKE`
- only a few `SKIP_SCORE`
- older-style decision path output such as:
  - `RDE[v10.10b]: ev=0.050 thr=-0.300 ...`
  - `decision=TAKE ev=0.0300 ...`

This proves there is a mismatch between:
- the path used by `pre_live_audit`
- the path used by live runtime

The system is not failing because of Redis or STALL anymore.
It is failing because live signal routing / decision routing is divergent.

---

## ROOT CAUSE HYPOTHESIS

One or more of these are true:

1. Live signal generation path does not call the same evaluator as audit path.
2. Live path blocks signals before they reach the same RDE gate used by audit.
3. Live path uses different thresholds or different state sources than audit.
4. Dashboard/live reporting says `zadny signal` without surfacing the true per-symbol block reason.
5. Multiple parallel decision systems are active:
   - `realtime_decision_engine.py`
   - `decision_engine.py`
   - `signal_engine.py`
   - `signal_generator.py`
   - `brain.py`
   - `pre_live_audit.py`
   - `bot2/main.py`

---

## REQUIRED OUTCOME

After this patch:

1. Live path and audit path must use the same decision/evaluation route, or clearly documented intentional differences.
2. Per-symbol live output must show the true block reason, not only `zadny signal`.
3. Live path must expose whether a candidate was:
   - not generated
   - blocked by score
   - blocked by OFI
   - blocked by cooldown
   - blocked by spread / RR / other guard
4. Threshold reporting in live status must reflect the real active path.
5. Audit and live must not disagree silently.

---

# TARGET FILES TO INSPECT AND PATCH

At minimum inspect and patch the real active routing flow among:

- `src/services/signal_generator.py`
- `src/services/signal_engine.py`
- `src/services/decision_engine.py`
- `src/services/realtime_decision_engine.py`
- `src/services/brain.py`
- `src/services/pre_live_audit.py`
- `bot2/main.py`

Patch only the files that are actually in the active path.

---

## TASK 1 — MAP THE REAL LIVE PATH VS AUDIT PATH

Before changing logic, identify the exact function path used by:

### A. Live runtime
From:
- market data / symbol loop
- signal generation
- filtering
- decision
- execution handoff

### B. Pre-live audit
From:
- audit input generation
- audit evaluation
- decision
- execution simulation

Return that mapping in code comments or explanation.

Goal:
Find where the two paths diverge.

---

## TASK 2 — UNIFY OR ALIGN DECISION PATH

If audit and live currently use different evaluators or different score gates:
- unify them onto one authoritative evaluator where practical
- or route both through the same `evaluate_signal()` / decision function
- or if full unification is too risky, ensure both use the same thresholds and same reason codes

Important:
Do NOT do a broad rewrite.
Do the smallest change that makes live and audit decisions comparable.

### Required behavior
For the same input candidate, audit and live should not silently disagree without logging why.

---

## TASK 3 — SURFACE TRUE LIVE BLOCK REASON PER SYMBOL

Current live UI/log says:
- `BTC zadny signal`
- `ETH zadny signal`

This is too weak diagnostically.

Replace or augment that with explicit last decision reason per symbol, for example:

```text
BTC  SKIP_SCORE
ETH  OFI_TOXIC
ADA  NO_CANDIDATE
BNB  COOLDOWN
```

If a richer format is possible:

```text
BTC  SKIP_SCORE  ev=0.030 score=0.174 thr=0.180
ETH  OFI_TOXIC   flow=-0.92 size_pen=0.50
ADA  NO_CANDIDATE
```

At minimum, for each symbol in the live dashboard / summary:
- show whether no candidate existed
- or which final block reason killed it

This is critical.

---

## TASK 4 — FIX THRESHOLD / STATUS DIVERGENCE

Current live dashboard shows:
- `EV prah 0.000`

But audit path shows thresholds like:
- `thr=-0.300`
- or score threshold behavior that clearly differs

Patch live status/dashboard so it reports the threshold from the actual active decision path.

At minimum:
- real EV threshold
- real score threshold
- whether unblock mode is active
- candidate counts
- block reason counts

Do not show placeholder or stale thresholds.

---

## TASK 5 — ADD ONE AUTHORITATIVE LIVE CYCLE SUMMARY

At the end of each live cycle, add one compact summary line such as:

```python
print(
    f"[cycle] symbols={symbols_count} candidates={candidates_count} "
    f"passed={passed_count} executed={executed_count} "
    f"top_block={top_block_reason} "
    f"ev_thr={ev_thr:.3f} score_thr={score_thr:.3f}"
)
```

Or equivalent using the actual active variables.

This must make it obvious whether:
- no candidates were generated
- candidates existed but all died at score gate
- OFI or cooldown dominated
- audit/live are still inconsistent

---

## TASK 6 — KEEP SAFETY, IMPROVE OBSERVABILITY

Do NOT remove:
- RR validation
- spread checks
- OFI guard
- exposure limits
- cooldown protection
- risk manager
- self-heal logic

This patch is about:
- route alignment
- observability
- making the real reason visible
- eliminating silent divergence

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. Live path and audit path are mapped and their divergence is explicitly fixed or narrowed.
2. Live per-symbol status no longer shows only `zadny signal`; it shows the real reason.
3. Live dashboard threshold values reflect the actual active decision path.
4. One authoritative cycle summary exists.
5. If the pipeline is still blocked, the logs make clear exactly which reason dominates.
6. Audit and live outputs become meaningfully comparable.

---

## RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. the exact live path vs audit path mapping
4. short root cause summary
5. short expected runtime behavior after patch
6. any assumptions if real call graph differs

Do NOT return pseudo-code only.
Return real integrated Python code.
