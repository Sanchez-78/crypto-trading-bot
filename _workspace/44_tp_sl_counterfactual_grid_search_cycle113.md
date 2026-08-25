# 44 — TP/SL counterfactual grid search (cycle 113): tempting signal found, does NOT survive split-sample

## Status: INVESTIGATED, NO live change made. Negative-but-valuable result — documented to prevent future re-discovery without the split check.

## Trigger

User pushback on cycles 111/112 ("wr nizke a pl negativni" — WR low and
P&L negative) — correctly refusing to accept "no new bug, keep waiting"
without deeper investigation. This cycle does the concrete thing cycle
111 flagged as the legitimate next step: a bounded, evidence-first
counterfactual TP/SL grid search on CURRENT live data, using
`cache.sqlite`'s per-trade `mfe_gross_bps`/`mae_gross_bps`/
`time_to_mfe_ms`/`time_to_mae_ms` columns to simulate alternate TP/SL
geometries retrospectively (no new backtest infra needed).

## Method

For each closed trade (72h window, n=1656, all admission paths pooled):
simulate whether a hypothetical `(tp_bps, sl_bps)` pair would have closed
as TP, SL, or TIMEOUT, using the recorded MFE/MAE extremes and their
timestamps as a proxy for ordering when both thresholds were reached
within the hold period. TIMEOUT-simulated trades keep their actual
realized `pnl_pct`. A flat 4bps round-trip cost (confirmed live this
session) is charged on every TP/SL outcome.

**Disclosed limitation:** MFE/MAE are hold-period *extremes*, not a full
tick-by-tick path — for a hypothetical threshold smaller than the
recorded extreme, the actual crossing time is earlier than the recorded
`time_to_mfe_ms`/`time_to_mae_ms`, so the tie-break heuristic (compare
extreme timestamps) is an approximation, not exact. Reasonable for this
screening purpose; not sufficient for a final go/no-go without a real
tick-level replay.

## Result 1 — narrower TP (8-35bps) with various SL: all worse than live

Every combination tested in the 8-35bps TP × 8-20bps SL range produced
**worse** PF and mean_bps than the current actual live outcomes (PF
0.736, mean -3.24bps/trade, WR 43.2% over the same 1656-trade window).
Confirms cycle 111's finding from a different angle: shrinking TP does
not help, it makes things worse (SL-hit-rate rises faster than TP-hit-rate
as TP shrinks, since realized moves cluster near flat).

## Result 2 — wide TP (60-100bps) + very tight SL (5-6bps): a tempting signal

Best result: `tp=100 sl=5` → PF 1.16, mean +0.93bps/trade, **but WR only
29.9%** (12 TP hits / 990 SL hits / 654 TIMEOUT, out of 1656). Several
neighboring combos also show PF > 1.0, mean_bps > 0. Symbol concentration
checked: 37 trades with MFE≥70bps spread across 3 symbols (ADAUSDT 19,
SOLUSDT 13, ETHUSDT 5), both BUY and SELL sides represented — not a
single-symbol/single-direction fluke by that measure alone.

## Result 3 — split-sample check: the signal does NOT survive

Split the 72h window into two 36h halves and re-ran the same combos:

| tp/sl | first half (n=846) | second half (n=810) |
|---|---|---|
| 100/5 | PF 1.305, mean +1.74bps, WR 31.6% | PF 1.012, mean **+0.07bps**, WR 28.1% |
| 80/5 | PF 1.287, mean +1.64bps | PF 1.007, mean +0.04bps |
| 60/5 | PF 1.236, mean +1.35bps | PF **0.956**, mean **-0.26bps** |
| 35/10 | PF 1.034, mean +0.24bps | PF **0.756**, mean **-1.84bps** |

**Every combo's edge collapses or reverses in the second half.** This is
the same "2024 bull beta" / thin-sample signature that refuted the
price-only donchian/xsec momentum leads earlier in this project's
research arc (`RESEARCH_LONGHORIZON_FINDINGS.md`) — a result that looks
positive on a naive full-window read but is actually concentrated in one
sub-period, not a durable structural property.

## Conclusion

**No live TP/SL change made or recommended this cycle.** The wide-TP/
tight-SL pattern is a real, reproducible artifact of this specific 72h
window but fails the minimum robustness bar (split-sample stability) this
project has consistently applied to every other lead in its research arc.
Also worth noting even if it HAD survived: WR at these settings is ~30%,
not >50% — an asymmetric fat-tail payoff shape is close to structurally
incompatible with the stated goal's literal WR>50% component, which is
itself a finding worth remembering for any future strategy design in this
direction (a fat-tail PF-positive strategy and a WR>50% strategy may be
different, not-simultaneously-achievable objectives).

**This does not contradict cycle 111's conclusion — it strengthens it**
with fresh, cycle-appropriate evidence: TP/SL geometry retuning, in
either direction (narrower or the tempting wider-TP/tighter-SL shape),
does not produce a robust win on current signal-generation output. The
bottleneck remains signal generation, not exit geometry.

## Recommended follow-up (not this cycle)

If a future cycle wants to pursue the wide-TP/tight-SL shape specifically
(distinct from a "fix WR" framing — it would need its own WR-vs-PF goal
reconciliation with the operator first), it needs: a longer OOS window
(days-to-weeks, not 72h), a formal bootstrap CI (this project's
established block-bootstrap method), and an explicit decision on whether
the project's WR>50% goal criterion is compatible with a fat-tail payoff
shape at all before building anything.
