# Current State & Handoff (2026-07-20)

One-screen resumable summary. Details in `AUDIT_CHANGES_LOG.md`, `MAKER_EXECUTION_ROADMAP.md`,
`RESEARCH_COSTWALL_FINDINGS.md`, `CryptoMaster_EXTERNAL_AUDIT_REPORT_v6.md`.

## Safety (unchanged, absolute)
- **REAL trading = NO-GO.** Paper only. Bot in **observe mode** (`PAPER_DATA_COLLECTION_ONLY=1`),
  **0 open positions** (confirmed by deploy zero-position gate), live_real off.
- Live server SHA **`d7b7039`** (deployed 2026-07-20 via gated apply, READY converged);
  dashboard API `:5001` up (open ship-dark unit, auto-rollback armed).

## The goal & where it stands
Goal: WR>50% + positive paper P&L, honestly. **Six strategy classes were rigorously cost-wall-
tested and all fail the ~18 bp/leg wall** (DEV_FADE, breakout, tsmom, z-revert, cross-sectional
momentum, tail residual reversal — two apparent leads were beta/artifacts; an external advisor's
best idea died at the premise). **The binding constraint is execution COST, not signal.**

## Active path: lower cost via maker execution (auditor v6-blessed M1–M5)
- ✅ **M1.1** coverage integrity — merged (#118) + **LIVE**
- ✅ **M1.2** executable spread capture — merged (#120) + **LIVE**
- ✅ **M1.3a** admission context — merged (#122) + **LIVE**
- ✅ **M1.3b** aggTrade WS subscription — merged (#127) + **LIVE** (d7b7039) → **M1 COMPLETE**
- ✅ **M2** maker-fill model — merged (#124); runner merged (#126); **memory-bound OOM fix
  merged (#128)**. Pipeline **verified end-to-end** on the live sqlite (run 29776673209, clean).
- ⬜ **M2 re-run → M3–M5 → verdict** (data-bound: needs weeks of multi-regime enriched data)

## First real M2 coverage read (2026-07-20, run 29776673209)
`n_obs_ok=110,891` · `has_spread=True` · `admission_fraction=0.244` (<0.80 — most rows are
pre-M1.3a legacy) · regimes ~97% BULL_TREND · conservative OOS fills=52 (<200) · symbol-share=1.0
→ **coverage_ok_for_GO=False, GO=False (correctly, multiply locked off).** The tiny positive
conservative expectancy is NOT edge — 52 fills, single symbol, <1% fill rate. **Constraint is now
purely data/time:** accumulate enriched, multi-regime, multi-symbol observations in observe mode.

## Immediate next actions (in order)
1. **Wait for data.** Let the bot accumulate enriched (spread+admission+aggTrade), multi-regime
   observations. Periodically re-trigger `hetzner-run-maker-model-v2.yml` to watch coverage climb
   (admission_fraction toward ≥0.80, regime balance, conservative fills toward ≥200).
2. When coverage clears the §8 GO bar (or fails it on adequate data): **M3–M5** (pre-registered
   policies, purged nested walk-forward, realistic venue costs) → GO/NO-GO verdict.
3. If GO bar unmet within the bounded budget (~30 days / 500 valid range-like effective obs) →
   archive DEV_FADE and pivot, per auditor §8. **REAL stays NO-GO throughout.**

## Honest odds
Modest prior. Most likely outcome is a **rigorous, executable-data NO-GO** — but that is a
definitive answer on the actual constraint (cost), and the auditor's bounded budget then says
retire DEV_FADE / pivot. Discipline throughout: every code/deploy change reviewer + trading-safety
gated (reviewers caught 5 real bugs across this arc — incl. the M2 OOM loader — all fixed); no
load-bearing deliverable merged unreviewed; no metric-gaming.
