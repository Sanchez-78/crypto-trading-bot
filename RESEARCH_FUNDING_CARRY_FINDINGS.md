# Funding-Carry — Findings (2026-07-21) — FIRST robustness-surviving lead

**Context:** ten price-only strategy families failed rigorous OOS + cost testing; the apparent
long-horizon edge was 2024 beta (`RESEARCH_LONGHORIZON_FINDINGS.md`). Pivot to a DIFFERENT
information set: perpetual **funding**. Delta-neutral carry (long spot / short perp, equal notional)
harvests funding while cancelling price direction — structurally near-market-neutral, so it should
make money in up AND down markets if real. Scripts: `scripts/research/funding_carry_screen.py`
(v1, funding-term only) and `funding_carry_v2.py` (monthly rebalance + basis + robustness).
Data: Binance funding history + spot/perp daily klines (data.binance.vision), 7 USDT majors.

## Result — v2 passes the skeptic battery that refuted every prior lead
Monthly-rebalanced delta-neutral carry, coins included iff trailing-3mo funding > 0.20 bp/8h,
transition-cost only (no churn), WITH basis (spot_ret − perp_ret). TEST OOS 2025-01..2026-06:

| check | base 30bp | stress 40bp | pass? |
|---|---|---|---|
| mean net / month | +18.5 bp | +16.3 bp | — |
| win_rate (months positive) | **0.733** | 0.733 | ✅ (goal WR>50%) |
| bootstrap CI[5,95] of monthly mean | **[+5.9, +31.0]** | [+3.5, +28.9] | ✅ lower > 0 |
| up-market vs down-market net | +1378 / **+187** | +1323 / **+182** | ✅ positive in BOTH (market-neutral, not beta) |
| max single-symbol profit share | 0.26 | 0.26 | ✅ |
| net by year | 2025 +1500, 2026 +63 | — | ✅ not one-year-only |
| approx annual yield | ~2.0% | ~1.7% | (modest) |

This is the FIRST signal in the whole arc that is positive after realistic costs, has a CI lower
bound above zero, is market-neutral (wins in down-markets too), and is symbol/time diversified.
It structurally differs from the refuted momentum leads: carry is a funding yield, not a directional
bet, which is exactly why it survives the up/down-market split.

## Honest caveats — this is a LEAD, not a validated edge (do not repeat the maker over-claim)
1. **Modest magnitude:** ~2%/yr net. Cash-enhancement / market-neutral yield, not a large return.
2. **Basis is boundary-only:** measured at monthly spot/perp daily closes; intra-month delta-neutral
   tracking error, spot-perp slippage, and roll mechanics are not yet modeled. These can erode carry.
3. **Thin sample:** 15 monthly points; the bootstrap CI, while positive, is over few observations.
4. **Regime dependence:** 2025 funding was richly positive; in a prolonged negative-funding regime
   the breakeven filter empties the basket → flat (no loss, but no yield). 2026 already thinner (+63).
5. **Instrument scope:** carry REQUIRES a perpetual short leg (futures), not spot-only. In PAPER
   simulation that is fine (no real money), but the live bot today runs a single-leg spot fader —
   pursuing carry needs a delta-neutral perp-leg paper simulator (a real architecture step), and the
   auditor/operator should bless expanding the instrument set. REAL = absolute NO-GO regardless.

## Why this matters for the goal
It is the first strategy that could plausibly satisfy WR>50% + positive paper P&L *honestly*: 73%
of months positive, market-neutral, cost-surviving. The "self-learning" target is well-defined —
select durable-positive-funding coins and size the neutral carry — and it learns something REAL
(a structural funding yield) rather than overfitting price noise.

## Recommended next steps (in order)
1. **Deeper execution model:** intra-month basis tracking, realistic spot+perp fills, funding on
   both legs, roll costs, capital/margin efficiency. Confirm ~2%/yr survives.
2. **Longer history / more regimes:** extend before 2023 where data allows; stress a
   negative-funding regime explicitly.
3. **Auditor sign-off** (feed into v8): is a delta-neutral perp-carry paper track within scope, and
   is a ~2%/yr market-neutral yield an acceptable interpretation of the goal, or too modest?
4. **Only then**, if blessed: design the perp-leg paper simulator + a carry admission/sizing loop.

**REAL trading = absolute NO-GO. Every number here is out-of-sample. No metric-gaming.**
