# 43 — TIMEOUT dominance re-confirmed as "no directional edge", not a geometry bug (cycle 111)

## Status: INVESTIGATED, evidence-backed, NO new actionable bug found. Consistent with prior cycle-23 grid-search finding — not re-litigated, freshly re-confirmed on a clean post-P1.1AV/AW cohort.

## Trigger

Standing autonomous loop, cycle 111. `_workspace/37`+STATE-02 session's Full
Status Report had flagged TIMEOUT dominance (64% lifetime) as "investigate,
not parametric retuning" — this cycle performs that investigation on a
clean cohort (12h window, entirely after both duplicate-trade fixes
deployed: `b921d54` P1.1AV, `3a294cd` P1.1AW).

## Live data (`cache.sqlite`, `mfe_gross_bps`/`mae_gross_bps` columns, 12h window, n=201)

| exit_reason | n | avg pnl_pct | avg hold_s | avg MFE (bps) | avg MAE (bps) |
|---|---|---|---|---|---|
| TIMEOUT | 157 (78%) | -0.029 | 387 | **+7.8** | -6.8 |
| TP | 16 (8%) | +0.475 | 144 | +51.5 | -0.6 |
| SL | 28 (14%) | -0.456 | 146 | +1.4 | -41.6 |

## Interpretation

For the 78% of trades that TIMEOUT, price moves an average of only **~8
basis points** favorably across the ENTIRE hold window (avg 387s) — nowhere
close to the 35-47bps TP zone (per `TP_COST_FLOOR_CLAMPED` observed live:
`tp_zone_bps=35 -> 47`). The 8% of trades that DO hit TP move ~51bps on
average, in less than half the hold time (144s vs 387s) — a qualitatively
different, much stronger move. There is no evidence of a "just barely
missing TP" pattern (which would show MFE clustering just under the TP
line); MFE for TIMEOUT trades clusters far below it, consistent with price
action that is close to flat/noise for the majority of admitted entries.

**This is not new** — it re-confirms, on a fresh, clean, post-duplicate-fix
cohort, the same finding the project's cycle-23 grid-search already
established: *no TP/SL geometry is profitable on the current signal path*
(see `project_trading_logic_deep_analysis` in memory / historical
`_workspace` notes). Shrinking the TP zone to make it "reachable" would not
create edge — it would just relabel some of the current TIMEOUT-flat noise
as small wins/losses roughly symmetrically, likely leaving expectancy
unchanged or worse once the ~4bps round-trip cost is subtracted from a
smaller TP.

## Why this cycle does NOT attempt a TP/SL retune

1. Cycle 23's grid search already disproved TP/SL geometry retuning as a
   fix on the current signal path — re-attempting it without new evidence
   that the underlying signal itself has changed would repeat a
   already-answered experiment.
2. The actual lever with a plausible path to genuine edge is signal
   generation, not exit geometry — which is exactly what the project's
   ongoing "Evidence-First Strategy Expansion v2" effort (P0.8+ strategies,
   order-flow imbalance/microprice, dynamic_trend_exit_v1, the funding-carry
   research thread just closed NO-GO last cycle) is for. That is a
   multi-cycle R&D effort already in progress elsewhere in the project, not
   a same-cycle patch.
3. No new bug was found this cycle (no admission deadlock, no duplicate
   trades, no data corruption, quota healthy, service stable). This is a
   confirmed economic/edge gap, not a defect — matching this session's
   standing rule not to patch without genuine root-cause evidence, and not
   to re-litigate an already-answered experiment.

## Current live snapshot (2026-08-25 ~08:29 UTC)

- Recent-100: WR 24.0%, PF 0.615 (pct) / 0.384 (usd), net P&L -3.93%/-0.76 USD
- Lifetime (10390 trades): PF 0.654, expectancy -0.0277
- Service: active, 0 errors, 2 open positions, closed_today=100
- Firebase quota: healthy (18/50000 reads, 279/20000 writes)
- Goal (WR>50% + positive P&L): **NOT reached**

## Recommended next step

Continue the standing 30-min monitoring cadence. No fix authorized this
cycle in the absence of a new bug-class finding. If a future cycle wants to
challenge cycle 23's grid-search conclusion (e.g. because market regime has
shifted since it ran), that should be its own dedicated, evidence-first
cycle — re-run a bounded TP/SL grid search on CURRENT data before touching
any live parameter, not a same-cycle reaction to this note.
