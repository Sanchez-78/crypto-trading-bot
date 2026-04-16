# Claude Code Prompt — CryptoMaster V10.13i Harvest Non-Firing + LOSS_CLUSTER Diagnosis Patch

Apply an incremental diagnostic patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove core protections.
Do NOT make broad tuning changes yet.
This patch is for precise diagnosis of why the latest live behavior regressed.

## GOAL

Recent live behavior shows that the latest OFI + harvest work did not produce the intended outcome.

### Confirmed live evidence
Current logs show:

- `LOSS_CLUSTER: 53`
- `OFI_TOXIC_HARD: 47`
- `[V10.13g EXIT] TP=0 SL=2 micro=0 be=0 partial=(0,0,0) trail=0 scratch=0 stag=0 harvest=0 t_profit=8 t_flat=42 t_loss=6`
- `Harvest rate: 0.0% (0/58)`
- `Profit Factor 0.67x`
- `Expectancy -0.00000012`

This means:

1. The V10.13g harvest cascade is not firing in live runtime.
2. `LOSS_CLUSTER` is now one of the dominant blockers.
3. OFI is still significant, but no longer the only problem.
4. Performance regressed after the recent tuning sequence.

This patch is NOT for another blind optimization.
It is to expose the exact runtime reason why:
- harvest paths never activate
- LOSS_CLUSTER is so high
- profitable trades are not being converted into harvested exits

---

## REQUIRED OUTCOME

After this patch:

1. Live logs must show exactly why each V10.13g harvest path is not firing.
2. Live logs must show exactly how `LOSS_CLUSTER` is being triggered and maintained.
3. We must be able to tell whether trades are:
   - never reaching harvest thresholds,
   - reaching them but being preempted by another exit branch,
   - misclassified after closing,
   - or blocked by ordering / state bugs.
4. No broad strategy changes yet — diagnosis first.
5. Safety protections must remain intact.

---

# TARGET FILES TO INSPECT AND PATCH

At minimum inspect and patch the real active code among:

- `src/services/smart_exit_engine.py`
- `src/services/trade_executor.py`
- `src/services/learning_event.py`
- `src/services/signal_filter.py`
- `src/services/realtime_decision_engine.py`
- `bot2/main.py`
- any file where `LOSS_CLUSTER` is computed or applied

Patch only the files actually responsible for:
- harvest exit activation
- close reason classification
- LOSS_CLUSTER accumulation / cooldown logic
- live reporting

---

## TASK 1 — MAP THE REAL HARVEST EXIT PATH

Identify the real live path for a profitable trade after entry:

open position →
profit evolution →
smart exit checks in actual order →
close execution →
close reason classification →
learning metrics aggregation →
dashboard summary

Return this mapping clearly.

Important:
We need the real production order of checks.
The main question is:
**why do all V10.13g harvest counters stay at zero in live logs?**

---

## TASK 2 — ADD NON-FIRING DIAGNOSTICS TO HARVEST CASCADE

In the real active smart-exit path, instrument the new V10.13g harvest checks so that we can see why they do not fire.

For each open trade, expose diagnostic state such as:

- current unrealized PnL
- TP distance / TP progress fraction
- whether micro TP threshold was reached
- whether breakeven trigger was reached
- whether partial 25/50/75 thresholds were reached
- whether trailing activation threshold was reached
- which earlier branch preempted them
- whether the trade went straight to timeout/other close path before harvest checks mattered

At minimum produce a compact debug/status line like:

```python
print(
    f"[V10.13i HARVEST] sym={sym} pnl={pnl:.6f} "
    f"tp_prog={tp_progress:.2f} micro={micro_hit} be={be_hit} "
    f"p25={p25_hit} p50={p50_hit} p75={p75_hit} trail={trail_armed} "
    f"exit_branch={exit_branch}"
)
```

Use actual live variables and real architecture.

Goal:
Find whether thresholds are:
- never reached
- reached but ignored
- reached but overwritten by another exit branch

---

## TASK 3 — TRACE CLOSE REASON CLASSIFICATION

Inspect the real close pipeline and determine:

- what exit reasons are emitted by `smart_exit_engine`
- what exit reasons survive into `trade_executor`
- what reasons are finally stored in learning metrics / dashboard summaries
- whether reason mapping collapses multiple harvest exits into some other bucket

### Required change
Add temporary precise visibility so we can tell:

- raw close reason from smart exit engine
- final persisted close reason
- dashboard aggregated close reason

This is critical because the patch may be working partially but getting lost in downstream classification.

---

## TASK 4 — DIAGNOSE `LOSS_CLUSTER`

Map the real `LOSS_CLUSTER` path:

trade closes →
trade result categorized →
cluster counters updated →
symbol/regime blocked →
live signal blocked later

Return that mapping clearly.

Then instrument it so logs show:

- which symbols are currently cluster-blocked
- why they became blocked
- what sequence of outcomes caused the block
- remaining cooldown time
- whether new close reasons from V10.13g are being treated as losses or toxic outcomes incorrectly

At minimum expose something like:

```python
print(
    f"[V10.13i CLUSTER] sym={sym} reg={reg} "
    f"reason={close_reason} result={result} "
    f"cluster_score={cluster_score:.2f} blocked={blocked} rem={cooldown_rem:.1f}s"
)
```

Goal:
Determine whether:
- cluster logic is too aggressive,
- cooldown is too long,
- or exit reclassification is accidentally poisoning cluster state.

---

## TASK 5 — CHECK FOR MISCLASSIFICATION OF NEW EXIT TYPES

Specifically verify whether these new V10.13g reasons are handled correctly downstream:

- `MICRO_TP`
- `PARTIAL_TP_25`
- `PARTIAL_TP_50`
- `PARTIAL_TP_75`
- `BREAKEVEN_STOP`
- `TRAIL_PROFIT`
- `HARVEST_PROFIT`

Questions to answer:
- Are they treated as wins, flats, or losses?
- Are they ignored by learning metrics?
- Are they accidentally mapped into timeout/loss buckets?
- Do they increment LOSS_CLUSTER indirectly?

Do NOT guess — trace the actual code path.

---

## TASK 6 — ADD A COMPACT DIAGNOSTIC SUMMARY

At the end of each live cycle, add one concise summary line such as:

```python
print(
    f"[V10.13i DIAG] harvest_live={harvest_candidates} "
    f"harvest_fired={harvest_fired} "
    f"cluster_blocks={loss_cluster_blocks} "
    f"ofi_hard={ofi_hard_blocks} "
    f"raw_reasons={raw_reason_counts}"
)
```

Use actual active variables.

Goal:
Make it obvious whether:
- harvest opportunities exist but never fire
- cluster blocks dominate the post-exit state
- OFI is still the main issue or no longer the main issue

---

## TASK 7 — DO NOT CHANGE STRATEGY YET

This patch is diagnostic-first.

Do NOT:
- broadly retune thresholds
- remove LOSS_CLUSTER
- remove OFI protection
- remove timeout logic
- lower all guards blindly
- redesign exit logic again

Only add the minimum safe instrumentation and, if necessary, tiny bug fixes required so the diagnostics are truthful.

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. We can see exactly why V10.13g harvest paths are not firing.
2. We can see the raw vs persisted exit reason path.
3. We can see exactly how `LOSS_CLUSTER` is formed.
4. We can tell whether new exit reasons are being misclassified.
5. Safety protections remain intact.
6. The next tuning step can be based on evidence instead of guesswork.

---

## RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. exact harvest path mapping
4. exact LOSS_CLUSTER path mapping
5. short root cause summary
6. short expected runtime behavior after patch
7. any assumptions if real call graph differs

Do NOT return pseudo-code only.
Return real integrated Python code.
