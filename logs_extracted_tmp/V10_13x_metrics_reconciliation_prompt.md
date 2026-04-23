# V10.13x Metrics Reconciliation — Implementation Prompt

## Role

You are a senior Python backend/quant engineer working on a live crypto trading bot. Implement the following refactor carefully, preserving existing good behavior while establishing **one canonical metrics source of truth**.

Do not redesign the whole bot. Do not change trade strategy semantics unless explicitly required below. Focus on **metrics correctness, reconciliation, observability, and log truthfulness**.

---

## Objective

Repair the metrics layer so that all displayed and persisted performance numbers are mathematically consistent and derived from the same canonical closed-trade dataset.

Current problems to fix:

- Trade counts do not reconcile across layers.
- Net PnL does not reconcile with per-symbol / per-regime sums.
- Exit attribution shows counts only, not economic contribution.
- Learning health is opaque and hard to debug.
- Some critical diagnostics are duplicated, filtered, or invisible.
- Dashboard / learning / persistence layers each compute overlapping metrics independently.

Your goal is to make metrics **truthful, auditable, and explainable**.

---

## Non-Negotiable Principles

1. **One canonical closed-trade aggregation path**
   - Summary metrics, per-symbol metrics, per-regime metrics, exit attribution, and health inputs must all derive from the same canonical closed-trade stats object.

2. **No silent metric divergence**
   - If two layers would disagree, log a reconciliation warning.

3. **Do not break execution**
   - This patch is primarily accounting / observability / reporting. Avoid changing order execution, risk sizing, or signal generation except where needed to label or persist metrics correctly.

4. **Human logs and machine logs must both be usable**
   - Human display should be concise and non-duplicated.
   - Machine-readable diagnostics should still exist and be visible in production logs.

5. **Preserve already working parts**
   - Keep good regime/pair breakdowns, bootstrap diagnostics, feature WR reporting, and existing integrity checks where still valid.

---

## Critical Existing Problem Examples

- Dashboard can show something like:
  - `Obchody 124`
  - but breakdown totals sum to thousands.
- Total net PnL can be negative while all per-symbol rows look positive.
- Exit summary shows counts but not whether those exits actually make or lose money.
- `health=0.004 [BAD]` appears with too little decomposition.
- The same learning diagnostic can print multiple times in the same cycle.
- Some diagnostic paths use `log.info()` and do not surface in production journal output.

---

## Implementation Phases

### Phase 1 — Canonical Foundation
Build the canonical closed-trade stats function and make it the single source of truth.

### Phase 2 — Reconciliation Recovery
Repair trade counts and PnL reporting everywhere user-visible.

### Phase 3 — Transparency
Add scoped WR labels, economic exit attribution, and health component decomposition.

### Phase 4 — Deduplication
Reduce repeated diagnostics and ensure important logs are visible.

### Phase 5 — Preservation and Validation
Verify that nothing good was lost and that all reconciliation rules hold.

---

## Files to Modify

### Primary
1. `src/services/metrics_engine.py`
2. `src/services/learning_event.py`
3. `src/services/learning_monitor.py`
4. `src/services/exit_attribution.py`
5. `bot2/main.py`
6. `src/services/firebase_client.py`

### Reference / Read Before Editing
- `src/services/dashboard.py`
- `src/services/dashboard_live.py`

---

## Required Deliverables

1. Implement the patch directly in code.
2. Keep code style consistent with the project.
3. Add concise inline comments for non-obvious logic only.
4. Print a short implementation summary after changes.
5. Explicitly list:
   - modified files
   - new helper functions
   - reconciliation rules enforced
   - any assumptions made

---

## FIX 1 — Canonical Closed-Trade Stats

### File
`src/services/metrics_engine.py`

### Requirement
Create a single canonical function that computes all core metrics from a list of **closed trades only**.

### Add
```python
def compute_canonical_trade_stats(trades: List[dict]) -> dict:
    ...
```

### Requirements for this function

Input:
- A list of closed trade dicts.
- Must tolerate missing fields defensively.
- Ignore open trades.

Outcome classification policy:
- `WIN` if `profit > +0.0001`
- `LOSS` if `profit < -0.0001`
- `FLAT` otherwise

Return structure must include at least:
```python
{
    "trades_total": int,
    "wins": int,
    "losses": int,
    "flats": int,
    "winrate_all_closed": float,      # wins / total closed
    "winrate_decisive": float,        # wins / max(1, wins + losses)
    "net_pnl": float,
    "gross_profit": float,
    "gross_loss_abs": float,
    "avg_profit": float,
    "profit_factor": float,
    "expectancy": float,
    "per_symbol": {
        sym: {
            "count": int,
            "wins": int,
            "losses": int,
            "flats": int,
            "net_pnl": float,
            "avg_pnl": float,
        }
    },
    "per_regime": {
        regime: {
            "count": int,
            "wins": int,
            "losses": int,
            "flats": int,
            "net_pnl": float,
            "avg_pnl": float,
        }
    },
    "per_exit_type": {
        exit_type: {
            "count": int,
            "wins": int,
            "losses": int,
            "flats": int,
            "net_pnl": float,
            "avg_pnl": float,
            "pct_of_total": float,
        }
    },
    "exit_contribution": {
        exit_type: {
            "net_pnl": float,
            "pct_of_total_pnl": float,
        }
    },
    "reconciliation": {
        "verified": bool,
        "alerts": list[str],
    }
}
```

### Canonical rules
- All summary counts must derive from the same trade list.
- Per-symbol totals must sum back to total.
- Per-regime totals must sum back to total.
- Per-exit totals must sum back to total.
- All percentages must be based on canonical totals, not ad hoc local counters.

### Required guard checks
Use tolerant checks, never hard-crash production because of a display mismatch.

Required validations:
```python
wins + losses + flats == trades_total
abs(sum_symbol_pnl - net_pnl) < tolerance
abs(sum_regime_pnl - net_pnl) < tolerance
abs(sum_exit_pnl - net_pnl) < tolerance
sum_symbol_count == trades_total
sum_regime_count == trades_total
sum_exit_count == trades_total
```

If any fail:
- set `reconciliation["verified"] = False`
- append readable alerts
- emit a warning log

Do not use raw `assert` in live runtime for these checks.

---

## FIX 2 — Trade Count Reconciliation

### File
`bot2/main.py`

### Requirement
Replace all dashboard trade count displays that mix incompatible sources.

### Rule
Wherever the dashboard prints trade totals or outcome breakdown, use:

```python
canonical = compute_canonical_trade_stats(closed_trades)
```

### User-visible format
Replace broken output like:
```text
Obchody 124 (OK 3173 X 2993 ~ 3758)
```

With truthful output:
```text
Obchody    124  (OK 46  X 6  ~ 72)
```

Where:
- `OK + X + ~ == Obchody` exactly
- all counts come from canonical closed trades only

If there is a legacy counter elsewhere:
- do not mix it into the same displayed line
- label it explicitly if still needed, e.g.:
  - `historical_events_seen`
  - `signals_captured`
  - `execution_attempts`

---

## FIX 3 — PnL Reconciliation

### Files
- `bot2/main.py`
- `src/services/firebase_client.py`
- any helper call sites necessary

### Requirement
Displayed total PnL must reconcile with per-symbol and per-regime PnL.

### Rules
- Total displayed net PnL = `canonical["net_pnl"]`
- Per-symbol rows must derive from `canonical["per_symbol"]`
- Per-regime rows must derive from `canonical["per_regime"]`
- Exit contribution must derive from `canonical["per_exit_type"]`

### Add periodic reconciliation log
Make it visible in production. Use `warning` or `print`, not `info` if info is filtered.

Format example:
```text
[V10.13x RECON] trades=124 wins=46 losses=6 flats=72
[V10.13x RECON] net=-0.00011821 sym_sum=-0.00011821 regime_sum=-0.00011821 exit_sum=-0.00011821 status=OK
```

If mismatch:
```text
[V10.13x RECON] status=MISMATCH alerts=[...]
```

Emit periodically, for example once per ~60 seconds or only when values change materially.

---

## FIX 4 — Winrate Scope Labeling

### File
`bot2/main.py`

### Requirement
Every WR metric shown to the user must declare its scope.

### Examples
Use explicit names like:
- `WR_all_closed`
- `WR_decisive`
- `WR_recent_50`
- `WR_execution_window`
- `WR_regime_BEAR`
- `WR_symbol_BTC`

Do not print ambiguous standalone `WR: 51.5%` unless the scope is on the same line.

Example:
```text
Winrate_all_closed   51.5%  (all closed trades, including flats)
Winrate_decisive     45.8%  (wins / wins+losses, flats excluded)
WR recent 24         45.8%  (recent decisive sample)
```

Same principle applies to calibration displays.

---

## FIX 5 — Economic Exit Attribution

### File
`src/services/exit_attribution.py`

### Requirement
Exit attribution must show economic contribution, not only counts.

### Use canonical stats
For each exit type, compute:
- count
- wins
- losses
- flats
- net_pnl
- avg_pnl
- share of total trades
- share of total PnL

### Required output behavior
Keep current count-style audit if useful, but add canonical economic truth.

Example:
```text
[V10.13x EXIT_ATTR] SCRATCH_EXIT count=84 net=+0.000412 avg=+0.0000049 wins=32 losses=40 flats=12 pct_trades=61.3% pct_pnl=28.4%
```

### Important
This patch must answer:
- Is `SCRATCH_EXIT` economically positive or negative?
- Which exit types contribute most of the realized PnL?
- Which exit types dominate count but not profit?

### Also add
A compact human summary ordered by absolute PnL contribution descending.

---

## FIX 6 — Single Canonical Aggregation Path

### Files
- `src/services/learning_event.py`
- `bot2/main.py`
- `src/services/firebase_client.py`

### Requirement
Existing parallel metric engines may still exist, but user-visible and persisted summary metrics must be sourced from the canonical stats object.

### Rule
Do not allow these layers to each recompute their own slightly different totals.

If a local module still needs special-purpose counters, keep them separate and explicitly named.

### Required naming cleanup
Avoid using generic names like:
- `wr`
- `profit`
- `trades`
without scope or source context nearby.

Prefer:
- `canonical_wr_decisive`
- `canonical_net_pnl`
- `canonical_trades_total`

---

## FIX 7 — Health Component Decomposition

### File
`src/services/learning_monitor.py`

### Requirement
Replace opaque health output with a component-based breakdown.

### New contract
`lm_health()` should return a structured object, not only a scalar.

Suggested shape:
```python
{
    "final": float,
    "status": str,
    "components": {
        "edge": float,
        "convergence": float,
        "calibration": float,
        "stability": float,
        "penalty": float,
    },
    "explain": str,
}
```

### Component expectations
You may adapt exact implementation to current codebase, but the final score must be decomposed into interpretable parts such as:
- **edge**: realized / learned positive edge strength
- **convergence**: percent of mature pairs with acceptable convergence
- **calibration**: prediction-vs-realization agreement
- **stability**: recent-vs-historical consistency
- **penalty**: bootstrap / insufficient-data / instability penalty

### Logging requirement
Emit a visible line like:
```text
[V10.13x HEALTH] final=0.024 BAD | edge=0.08 conv=0.03 calib=0.01 stab=0.02 penalty=-0.12
```

### Human output requirement
Also print one readable sentence:
```text
Health je nízký hlavně kvůli slabé konvergenci a bootstrap penalizaci.
```

Do not print the same health block multiple times in the same cycle.

---

## FIX 8 — Log Visibility and De-duplication

### Files
- `src/services/learning_monitor.py`
- any logging call sites involved in repeated learning diagnostics

### Requirements

#### A. Important logs must be visible
If logs such as `[V10.13w LM_CLOSE]` are important for production debugging, do not rely on `log.info()` only if info is filtered. Use either:
- `log.warning(...)`
- or `print(...)`
- or a project-consistent visible logger wrapper

#### B. Deduplicate repeated cycle diagnostics
Within a single cycle, print the learning summary once.

Eliminate repeated blocks like:
```text
[!] LEARNING: ...
[!] LEARNING: ...
[!] LEARNING: ...
```

Use:
- one human-readable summary per cycle
- separate machine logs only where they add distinct information

#### C. Avoid spam
Do not flood logs with repeated identical canonical decision / learning summary lines within seconds unless values actually changed.

A tiny helper cache for last-emitted message per topic is acceptable.

---

## FIX 9 — Preserve Existing Good Functionality

Keep and preserve if already working:
- bootstrap diagnostics
- pair/regime breakdowns
- feature WR reporting
- current integrity checks, but extend them
- existing exit count audit, enhanced with economics
- current dashboard style where possible

Do not remove useful operational context.

---

## Additional Required Improvements

### 1. Make `score_raw` truthful
If canonical decision logging currently prints `score_raw=0.0000` while upstream logs show non-zero score, repair that mismatch or relabel it to the actual metric being shown.

Do not leave misleading zero placeholders.

### 2. Distinguish event counters from closed-trade counters
There are multiple concepts in logs:
- signals captured
- decision attempts
- executions
- closed trades
- closed decisive trades

These must not be merged into one unlabeled number.

### 3. Handle flats consistently
If flats are included in all-closed WR, that must be clearly labeled.
If decisive WR excludes flats, that must also be clearly labeled.

### 4. Firebase persistence
If health components or canonical summaries are persisted, keep schema backward-compatible where possible.
If schema extension is needed, make it additive and safe.

Do not silently overwrite unrelated structures.

---

## Validation Plan

### Test 1 — Trade count reconciliation
Pass only if:
```text
trades_total == wins + losses + flats
```
for all user-visible summaries.

### Test 2 — PnL reconciliation
Pass only if:
```text
abs(total_net_pnl - sum(per_symbol_net_pnl)) < tolerance
abs(total_net_pnl - sum(per_regime_net_pnl)) < tolerance
abs(total_net_pnl - sum(per_exit_type_net_pnl)) < tolerance
```

### Test 3 — Exit attribution truth
Pass only if:
- exit counts sum to total closed trades
- exit PnL sums to total net PnL
- at least one output clearly shows whether `SCRATCH_EXIT` is net positive or net negative

### Test 4 — Health transparency
Pass only if:
- health final value is shown
- components are shown
- one readable explanation is shown

### Test 5 — WR labeling
Pass only if:
- no ambiguous unlabeled WR remains in user-facing output

### Test 6 — Log deduplication
Pass only if:
- no repeated identical learning summary is printed multiple times in one cycle

### Test 7 — Backward safety
Pass only if:
- trade execution still runs
- no execution/risk logic regressions introduced
- no crashes if canonical stats receive empty trade lists

---

## Implementation Constraints

- Prefer small helper functions over giant monolith edits.
- Be defensive with missing fields.
- Keep imports minimal.
- Avoid adding heavy dependencies.
- Use project conventions.
- Do not invent fake precision or fabricated metrics.
- If a metric cannot be computed reliably from available data, state that in log output instead of guessing.

---

## Suggested Execution Order

1. Read current metric producers in:
   - `metrics_engine.py`
   - `learning_event.py`
   - `learning_monitor.py`
   - dashboard output sections
2. Implement `compute_canonical_trade_stats()`
3. Wire dashboard summary to canonical stats
4. Wire per-symbol / per-regime / exit tables to canonical stats
5. Add reconciliation warnings
6. Add health decomposition
7. Deduplicate logs
8. Run quick validation
9. Print short change summary

---

## Final Output Required From You

After implementation, print:

1. **Modified files**
2. **New helpers added**
3. **Reconciliation guarantees now enforced**
4. **Any remaining known limitations**
5. **Short verification summary**

Example:
```text
Implemented V10.13x.
Modified: ...
Helpers added: ...
Reconciliation guarantees: ...
Known limitations: ...
Verification: trade counts reconcile, PnL reconciles, exit attribution now economic, health decomposed.
```

---

## Important Note

This patch is about **truth recovery**.  
Do not optimize strategy behavior first.  
Make the bot's accounting and diagnostics trustworthy first, then future tuning can be based on real numbers.
