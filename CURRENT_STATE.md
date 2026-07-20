# Current State & Handoff (2026-07-20)

One-screen resumable summary. Details in `AUDIT_CHANGES_LOG.md`, `MAKER_EXECUTION_ROADMAP.md`,
`RESEARCH_COSTWALL_FINDINGS.md`, `CryptoMaster_EXTERNAL_AUDIT_REPORT_v6.md`.

## Safety (unchanged, absolute)
- **REAL trading = NO-GO.** Paper only. Bot in **observe mode** (`PAPER_DATA_COLLECTION_ONLY=1`),
  **0 open positions**, live_real off.
- Live server SHA **`332acba`**; dashboard API `:5001` up (open ship-dark unit, auto-rollback armed).

## The goal & where it stands
Goal: WR>50% + positive paper P&L, honestly. **Six strategy classes were rigorously cost-wall-
tested and all fail the ~18 bp/leg wall** (DEV_FADE, breakout, tsmom, z-revert, cross-sectional
momentum, tail residual reversal — two apparent leads were beta/artifacts; an external advisor's
best idea died at the premise). **The binding constraint is execution COST, not signal.**

## Active path: lower cost via maker execution (auditor v6-blessed M1–M5)
- ✅ **M1.1** coverage integrity — merged (#118) + **LIVE**
- ✅ **M1.2** executable spread capture — merged (#120) + **LIVE**
- ✅ **M1.3a** admission context — merged (#122) + **LIVE**  → enriched data now accruing
- ⏸️ **M2** maker-fill model scaffold — **built, PR #124, RE-REVIEW PENDING (do not merge)**.
  Reviewer REJECTED v1 (fake bootstrap + dead exit-B code); all findings fixed + full §8 GO bar
  added; 7 tests green; **re-review interrupted by the session limit (resets 15:00 UTC).**
- ⬜ **M1.3b** aggTrade WS subscription (for the executable "base" fill scenario)
- ⬜ **M2 run → M3–M5 → verdict** (data-bound: needs weeks of multi-regime enriched data)

## Immediate next actions (in order)
1. **After 15:00 UTC:** re-review PR #124 (confirm both blockers resolved + GO can't fire on
   thin/legacy/single-regime data) → on APPROVE, merge → deploy → add a read-only runner to run
   `maker_fill_model_v2.py` server-side against the live `shadow_excursion.sqlite` (coverage read;
   GO stays hard-locked off until data is large + multi-regime).
2. **M1.3b** (aggTrade) — the last M1 enrichment, its own reviewed PR.
3. Let enriched data accumulate; re-run M2 as coverage grows.

## Honest odds
Modest prior. Most likely outcome is a **rigorous, executable-data NO-GO** — but that is a
definitive answer on the actual constraint (cost), and the auditor's bounded budget then says
retire DEV_FADE / pivot. Discipline throughout: every code/deploy change reviewer + trading-safety
gated (reviewers caught 4 real bugs across this arc, all fixed); no load-bearing deliverable merged
unreviewed; no metric-gaming.
