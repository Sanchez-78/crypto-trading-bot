# External Audit Prompt v9 — Funding-Carry: Scope & Goal-Interpretation Sign-Off

You are the independent external auditor of the CryptoMaster HF-Quant paper-trading project. Your v8
verdict confirmed retiring DEV_FADE on the M5 cost arithmetic (~15 bp attainable spot round-trip vs
sub-2 bp affordable) and, in Q3, asked us to rank credible remaining paths — explicitly naming
"longer-horizon strategies where 15 bp matters less (hours+ holds, fundamentally different data
needs)" and "migrating to a venue/pair set with structurally lower costs." We pursued exactly that
and are back with the **first lead in the entire arc that survives your skeptic battery.** We now ask
you to rule on scope and goal-interpretation before any infrastructure is built.

## What changed since v8 (verifiable in the repo)
- `RESEARCH_LONGHORIZON_FINDINGS.md` — we first tested price-only long-horizon (tsmom, MA filter,
  donchian, xsec momentum) on 1h spot klines, 2023–2026, with adaptive monthly walk-forward. Two
  survivors (donchian, xsec) **were refuted by the same battery you taught us**: bootstrap CI spanned
  zero, all profit in 2024, wins only in up-markets → 2024 bull BETA, not alpha. Ten price-only
  families now fail rigorous OOS + cost. **Price-only momentum/reversion/breakout on 7 majors is
  beta + noise after costs.** We did not manufacture an edge; the learner correctly refused to.
- Pivot to a DIFFERENT information set: perpetual **funding**. `RESEARCH_FUNDING_CARRY_FINDINGS.md`
  + `scripts/research/funding_carry_v2.py`.

## The lead — delta-neutral funding carry (long spot / short perp, equal notional)
Monthly-rebalanced; a coin enters the equal-weight basket iff trailing-3-month funding
> 0.20 bp/8h (causal filter); a rolled position pays no re-entry cost; per coin-month P&L =
Σ funding (short receives) + basis (spot_ret − perp_ret) − transition cost. **TEST OOS
2025-01 .. 2026-06:**

| check | base 30 bp | stress 40 bp | passes your battery? |
|---|---|---|---|
| mean net / month | +18.5 bp | +16.3 bp | — |
| win_rate (months positive) — the goal metric | **0.733** | 0.733 | ✅ (> 0.50) |
| bootstrap CI[5,95] of monthly mean | **[+5.9, +31.0] bp** | [+3.5, +28.9] | ✅ lower > 0 |
| up-market vs down-market net | +1378 / **+187** | +1323 / +182 | ✅ positive in BOTH |
| max single-symbol profit share | 0.26 | 0.26 | ✅ |
| net by year | 2025 +1500, 2026 +63 | — | ✅ not one-year-only |
| approx annual yield | ~2.0 % | ~1.7 % | (modest) |

Unlike the refuted momentum leads, this is a funding YIELD, not a directional bet — which is
structurally why it wins in down-markets too (market-neutral) and does not collapse to 2024 beta.

**⚠ Reality check (do NOT read the table above at face value):** the v2 figures are single-leg
notional with an abstract 30/40 bp cost. The executable model (check 1 below) shows the honest
picture is **materially weaker — ~0.7–1.0%/yr on true deployed capital, and the down-market cushion
does not survive realistic per-leg fills.** We present v2's headline for continuity but the audit
questions below are framed on the executable numbers, not the headline.

## Deepening now in flight (three independent checks; numbers appended on completion)
We are NOT repeating the maker over-claim. Before asking you to bless scope, three checks are
running against your evidence bar (`RESEARCH_PIVOT_CHARTER.md`):
1. **Executable execution model (`funding_carry_v3.py`, COMPLETE):** short-leg funding accrued
   per-8h on the drifting perp notional, intra-month two-leg MtM at 8h (basis drift confirmed tiny,
   ~0.06 bp/coin-mo — delta-neutral really does cancel direction), realistic per-leg fills
   (optimistic/base/conservative), transition cost both legs, yield on TRUE deployed capital
   (1.48× notional = spot 1.0 + perp margin ~0.33 + 0.15 buffer). **This MATERIALLY DOWNGRADES the
   v2 headline on two fronts:** (i) v2's "~2%/yr" was single-leg; on true deployed capital it is
   **1.30%/yr BASE, 1.03% CONSERVATIVE, ~1.09% even OPTIMISTIC — roughly HALVED**; (ii) under
   realistic per-leg fills the **market-neutral-in-BOTH-directions property FAILS**: down-market
   coin-months net **−30 bp (base) / −102 bp (conservative)**, positive only in the optimistic
   scenario (+54). Net bp/mo: 13.5 opt / 10.8 base / 8.5 conservative; WR 0.667; PF 7.2/4.0/2.8;
   bootstrap CI conservative **[+0.5, +16.7] bp — barely > 0** (one or two bad months flips it).
   P&L decomp (base, 15 mo): funding +1039, basis +45, transition −276. by-year: 2025 +812,
   2026 −9 (≈ flat) → regime-dependent on 2025's rich positive funding. Fee/spread are calibrated
   assumptions, not a booked tier; margin/liquidation path modeled as a static buffer, not stressed.
2. **Robustness (`funding_carry_robustness.py`, COMPLETE except extended-history):** scored against
   your GO thresholds — **6/7 PASS, 1 hard FAIL.** PASS: OOS PF 4.25; expectancy +18.5 bp;
   **block-bootstrap CI lower STAYS POSITIVE** ([+3.48, +35.24] base; [+0.35, +33.59] stress —
   fragile but does NOT span zero, categorically unlike donchian/xsec [−26,+196]); no symbol > 50%
   (BTC 26%); positive in 2 years. **FAIL: the ≥200-fill bar — only 67 coin-months, and with lag-1
   autocorr 0.317 the EFFECTIVE N ≈ 7.8 monthly units** (the 7 coins in a month share that month's
   shock → not independent). Purged/embargoed walk-forward: filter is causal (verified no
   look-ahead); positive at all 6 tested split dates, BUT **monotonic decay** — mean 34.9 bp starting
   2024-06 → 18.5 at 2025-01 → basket EMPTY by 2026-Q2, i.e. the edge is front-loaded in the rich
   2025 funding regime and decays to flat. Negative-funding stress: 83% rich occupancy; the filter
   correctly empties the basket (no forced bad carry, fail-safe) but the strategy simply STOPS
   earning when funding dries up. **Extended pre-2023 history (2020–2022) — the single most decisive
   remaining test — is still downloading; appended as a follow-up.** If 2021/22 carry is also
   CI-positive the thin-sample concern eases materially; if not, this is 2025-regime comfort.
3. **Concrete venue cost (COMPLETE):** Binance VIP0+BNB tier, verified fees — spot 7.5 bp/side,
   USDⓈ-M perp 1.8 maker / 4.5 taker; funding confirmed (short RECEIVES when rate > 0, 8h cadence,
   ±0.3%/8h cap on majors). **True delta-neutral round-trip = ~26–29 bp (avg ≈ 27 bp)**, range 25.5
   (BTC) → 33 (DOT/ADA). **v2's 30/40 bp is realistic-to-mildly-conservative — NOT optimistic**, so
   this lead does not die on a hidden fee wall the way DEV_FADE and the six price-only classes did.
   TWO load-bearing caveats: (i) carry clears the wall **only under v2's roll/amortization** —
   a 1-month in/out FAILS (+18.5 gross − 27 RT ≈ −9 bp; breakeven hold ≈ 1.4–1.6 mo), so the
   no-churn roll discipline is essential; (ii) the ~2 %/yr gross carry is **near the risk-free
   opportunity cost of the fully-funded spot leg** (T-bills ~4–5 %/yr) — on an opportunity-cost
   basis the carry is roughly a wash, which is the real magnitude question below, not a cost wall.

## Executable bottom line — all three checks converge
Presenting honestly, not for continuity: the three independent deepenings agree.
- **Not a cost-wall death (a first in this arc).** Concrete venue cost ~27 bp RT ≤ v2's assumed
  30/40 bp; the fee arithmetic is clean and even favorable. Funding-carry does NOT die the way
  DEV_FADE and the six price-only classes did.
- **But it dies on MAGNITUDE, not cost.** On true deployed capital (1.48×) the yield is
  **~0.7–1.3%/yr**, and the venue check puts that **near/below the risk-free rate** (T-bills
  ~4–5%/yr) — an opportunity-cost wash.
- **Its single best property does not survive execution.** v2's market-neutral "wins in down-markets
  too" (the thing that made it alpha not beta) FLIPS negative in down-months under realistic per-leg
  fills (v3: −30/−102 bp base/conservative).
- **Real but thin and regime-contingent.** Block-bootstrap CI stays positive (categorically unlike
  the refuted momentum leads) — but effective N ≈ 8 months (hard fail on the ≥200-fill bar), the
  edge is front-loaded in 2025's rich funding and decays to an empty basket by 2026-Q2.

So this is a genuine, honestly-measured, market-neutral **cash-enhancement lead of ~sub-1%/yr real**
— not a compelling deployable edge. That framing, not the v2 headline, is what the questions ask you
to rule on.

## Q1 (decisive): is a delta-neutral perp-carry PAPER track within scope?
Your standing constraints (v6–v8) were "Binance **spot** data via WebSocket; single retail-tier
account; REAL = NO-GO." Carry **requires a perpetual short leg** — a USDⓈ-M instrument, not spot.
That is an instrument-scope expansion, in paper simulation only (no real money, no leverage risk
realized). **Do you authorize adding a delta-neutral perp-carry paper track** — a perp-leg paper
simulator + a carry admission/sizing loop — as the project's research direction? If you refuse,
state whether it is the perp-leg scope itself you reject, or the evidence you find insufficient.

## Q2 (goal interpretation): is ~2 %/yr market-neutral yield an acceptable reading of the goal?
The goal is "WR > 50% AND positive paper P&L, honestly." Funding-carry delivers 73% positive months
and CI-positive net — but at a **modest ~2%/yr gross**, and the concrete venue-cost check (3) shows
this is **near the risk-free opportunity cost** of the fully-funded spot leg (T-bills ~4–5%/yr), i.e.
on an opportunity-cost basis the strategy is roughly a wash vs doing nothing — before the still-
unmodeled intra-month basis/roll frictions (check 1) erode it further. Two sub-questions: (a) does a
market-neutral cash-enhancement yield satisfy the goal at all, or does "positive paper P&L" implicitly
require beating the risk-free alternative? (b) if a higher bar is required, name it (expectancy/
Sharpe/excess-over-cash) so the research has a concrete target rather than "positive but trivial."

## Q3: does the lead actually clear the evidence bar, or is it thin-sample comfort?
With only **15 monthly observations**, boundary-only basis, and a funding regime (2025) that was
richly positive, is the CI-positive result durable or is it the same thin/time-concentrated tell in
a market-neutral disguise? Once checks 1–3 are appended, rule: **GO to build the perp-carry paper
simulator, or NO-GO (declare the goal not attainable under current constraints).** Name the single
result that would most change your verdict.

## Ground rules (unchanged)
Be adversarial; refute us where the evidence allows. Cite our artifacts by name. Do not soften the
verdict for continuity's sake: if the honest answer is "stop, the goal is not attainable under these
constraints", say it. REAL trading stays an absolute NO-GO regardless of your answer.
