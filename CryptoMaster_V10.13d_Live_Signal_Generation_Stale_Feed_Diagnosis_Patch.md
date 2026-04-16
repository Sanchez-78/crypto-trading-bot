# Claude Code Prompt — CryptoMaster V10.13d Live Signal Generation / Stale-Feed Diagnosis Patch

Apply an incremental patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove core protections.
Patch only the real active runtime integration points now identified from live logs.

## GOAL

The system is now operational, calibrated, and no longer primarily blocked by:
- Redis
- fake STALL timestamps
- FAST_FAIL dominance
- OFI over-blocking

However, live runtime is still stalled upstream.

### Confirmed live evidence
Recent live logs show:

- `Signaly 0 zachyceno 0 po filtru 0 blokovano 1309 provedeno`
- `Posledni obchod 15h+ zpet`
- watchdog: `No trades for 600s → boosting exploration`
- learning: `NO LEARNING SIGNAL DETECTED`
- dashboard per-symbol status still effectively behaves like “no new candidate”
- audit can still pass candidates
- live market prices often appear nearly static in displayed output (`+0.000%` on many symbols in the same cycle)

This means the current main problem is no longer downstream rejection.
It is now likely in one or more of:

1. live signal generation not producing candidates
2. stale / slow market data updates
3. candidate creation path not firing in live loop
4. generator prerequisites too strict before a candidate even exists
5. dashboard not surfacing “why no candidate exists”

---

## REQUIRED OUTCOME

After this patch:

1. Live runtime must clearly show whether candidates are being generated at all.
2. If no candidate is generated, the reason must be observable.
3. If market data is stale, that must be detectable in logs/status.
4. Candidate creation counts must be visible before RDE/filtering.
5. Dashboard/live summary must distinguish:
   - no fresh data
   - no candidate created
   - candidate created but filtered
   - candidate passed but not executed

---

# TARGET FILES TO INSPECT AND PATCH

At minimum inspect and patch the real active code among:

- `src/services/market_stream.py`
- `src/services/market_data.py`
- `src/services/market_data_service.py`
- `src/services/signal_generator.py`
- `src/services/signal_engine.py`
- `src/services/feature_extractor.py`
- `src/services/feature_engine.py`
- `src/services/brain.py`
- `bot2/main.py`
- any dashboard/live status file that shows `Signaly ...` and per-symbol state

Patch only the files actually responsible for:
- live market data freshness
- candidate creation
- pre-filter candidate tracking
- live summary display

---

## TASK 1 — MAP LIVE SIGNAL CREATION PATH

Identify the real active live path for candidate creation:

from market update →
feature refresh →
signal generation →
candidate object creation →
filtering / RDE →
execution handoff

Return this mapping clearly in your explanation.

Important:
We need the path BEFORE RDE filtering.
The key question is:
**why are `generated = 0` / `zachyceno = 0` in live mode?**

---

## TASK 2 — ADD PRE-FILTER CANDIDATE VISIBILITY

Add explicit counters/logging for:

- fresh ticks received
- symbols updated this cycle
- feature extraction success count
- candidates created before filtering
- candidates dropped before filtering, with reasons

At end of each live cycle, print something like:

```python
print(
    f"[V10.13d] ticks={ticks} updated={updated} features_ok={features_ok} "
    f"candidates={candidates_created} prefilter_drops={prefilter_drops} "
    f"filtered={filtered} executed={executed}"
)
```

Use the actual active variables and real code path.

Goal:
Make it obvious whether the pipeline is failing:
- before feature extraction
- before candidate creation
- at filter/RDE stage
- at execution stage

---

## TASK 3 — SURFACE PREFILTER DROP REASONS

If a symbol receives fresh data but no candidate is created, expose the true reason.

Examples:
- `NO_PRICE_CHANGE`
- `NO_FEATURES`
- `INDICATORS_NOT_READY`
- `SIGNAL_THRESHOLD_NOT_MET`
- `MARKET_DATA_STALE`
- `SYMBOL_SKIPPED`
- `NO_CANDIDATE_PATTERN`

At minimum, the per-symbol live summary should show a useful reason instead of generic silence.

Example target output:
```text
BTC  NO_CANDIDATE_PATTERN
ETH  INDICATORS_NOT_READY
ADA  MARKET_DATA_STALE
BNB  SKIP_SCORE
```

This must distinguish:
- no candidate created
vs
- candidate created but later rejected

---

## TASK 4 — DETECT STALE MARKET DATA

Add explicit market data freshness diagnostics.

For each symbol or globally, track:
- last price update timestamp
- last tick age
- whether price changed this cycle
- whether feature inputs are fresh enough for signal generation

If data is stale, expose it in logs/dashboard.

Example:
```python
stale_sec = now - last_update_ts
if stale_sec > stale_threshold:
    reason = "MARKET_DATA_STALE"
```

Do NOT invent fake signals from stale data.
Just make freshness visible.

---

## TASK 5 — FIX LIVE DASHBOARD SIGNAL COUNTS

Current live status can say:
- `0 zachyceno 0 po filtru 0 blokovano 1309 provedeno`

This is misleading because it mixes:
- current-cycle signal state
- historical executed totals

Patch the dashboard/status so the displayed signal counts are clearly separated into:

### Current cycle / recent window
- generated_now
- filtered_now
- blocked_now
- executed_now

### Historical totals
- total_executed
- total_closed_trades
- calibration total

Do not mix “current cycle 0” with a historical `1309 provedeno` in a way that hides what is actually happening now.

---

## TASK 6 — KEEP THESE SAFETY PROPERTIES

Do NOT remove:
- RR validation
- spread checks
- OFI protection
- cooldown protections
- risk manager
- watchdog/self-heal
- execution checks

This patch is about:
- diagnosing upstream stall
- exposing missing candidate creation
- detecting stale feed / stale features
- making live pipeline observable before filtering

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. Live logs clearly show whether fresh ticks are arriving.
2. Live logs clearly show whether candidates are being created before filtering.
3. If candidates are not created, the true reason is visible.
4. Market data staleness is observable.
5. Dashboard signal counts distinguish current-cycle vs historical totals.
6. The system no longer hides upstream stall behind generic `zadny signal`.

---

## RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. exact live signal creation path mapping
4. short root cause summary
5. short expected runtime behavior after patch
6. any assumptions if real call graph differs

Do NOT return pseudo-code only.
Return real integrated Python code.
