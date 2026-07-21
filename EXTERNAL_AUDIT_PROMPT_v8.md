# External Audit Prompt v8 — M5 Cost Arithmetic: Early Kill-Switch Decision

You are the independent external auditor of the CryptoMaster HF-Quant paper-trading project. Your
v6 report (verdict C) mandated the M1–M5 maker-execution experiment; M1 is complete and live, the
corrected M2 model runs clean on live enriched data, and observation-only collection continues
(REAL trading remains an absolute NO-GO). We now ask you to rule on ONE decisive question, plus two
secondary ones.

## Context (verifiable in the repo)
- `RESEARCH_M5_COST_ARITHMETIC.md` — the memo under review.
- `MAKER_EXECUTION_ROADMAP.md` — M1 complete (coverage integrity, spread, admission, aggTrade all
  deployed and runtime-verified: 10,938 post-deploy observations, 100% enriched, clean cutover).
- First real OOS read (v2 model, conservative/executable scenario, GO hard-locked off):
  test_exp **+0.14 bp** per admissible signal at an ASSUMED 4.0 bp round-trip; 52 OOS fills;
  fill rate 1.2%; single symbol; ~97% single regime. Midpoint ceiling: +0.017 bp at 1.0 bp.
- Verified venue fees (2026-07): Binance spot VIP0 10 bp/side; with BNB discount **7.5 bp/side**
  (≈15 bp maker round-trip). VIP9 (2 bp maker, ≈4 bp round-trip) requires >$2B monthly volume —
  unattainable. No confirmed structural zero-fee spot pairs; promos are revocable and off-dataset.

## Q1 (decisive): early §8 kill switch on M5 arithmetic?
Your §8: *"If the base/conservative model fails → retire DEV_FADE definitively."* The affordable
round-trip implied by the data (≤ ~1–2 bp after your +2–3 bp reserve) is an order of magnitude
below the attainable tier (~15 bp). The recorded excursion paths bound gross edge from above
(sub-1 bp unconditional; ~4–7 bp per fill), so additional data cannot bridge a 15 bp wall.
**Do you confirm retiring DEV_FADE now on M5 arithmetic, without waiting out the ~30-day data
budget?** If you refute, state specifically: (a) which attainable ≤ ~2 bp execution path we
missed (venue, tier, rebate program, or pair set with durable zero fees and adequate liquidity),
or (b) why the gross-edge upper bound argument is wrong.

## Q2 (only if continuing): admission_fraction gate definition
The pre-registered coverage gate requires admission_feature_fraction ≥ 0.80. Computed over ALL
121k+ historical observations it needs ~4 weeks (legacy rows are fixed at ~84k; enriched accrue
~11k/day). The model's evaluation window (most-recent 15k) will be ~100% enriched within days.
Should the gate be evaluated over (a) the full history, or (b) the evaluation window actually used
for the walk-forward? We did NOT change the gate unilaterally; it stands at (a) until you rule.

## Q3 (pivot guidance): if DEV_FADE is retired
Six signal classes already failed the ~18 bp taker wall; maker execution now fails on attainable
fees. Within the standing constraints (paper only; REAL = NO-GO; Binance spot data via WebSocket;
single retail-tier account), what — if anything — do you consider a credible remaining path to the
goal (WR > 50% AND positive paper P&L, honestly, without metric-gaming)? Candidates we see:
longer-horizon strategies where 15 bp matters less (hours+ holds, fundamentally different data
needs), migrating the experiment to a venue/pair set with structurally lower costs, or an honest
"goal not attainable under current constraints" finding. Rank them or reject them all.

## Ground rules (unchanged)
Be adversarial; refute us where the evidence allows. Cite our artifacts by name. Do not soften the
verdict for continuity's sake: if the honest answer is "stop", say stop. REAL trading stays NO-GO
regardless of your answer.
