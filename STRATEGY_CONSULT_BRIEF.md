# DEV_FADE — Strategy Consultation Brief (for an external quant / execution specialist)

**Date:** 2026-07-19 · **Mode:** PAPER only · **REAL trading:** absolute NO-GO (not on the table). · **Ask:** tear this apart. One question is open; everything else is settled.

---

## 0. TL;DR — the question, and our own (negative) answer
DEV_FADE is a 1-second mean-reversion "fader" (buys weakness / sells strength) on 7 USDT pairs. It **loses on paper** (lifetime PF 0.68, everything times out slightly negative). We proved *why*: the signal is **directionally right but its magnitude (~2 bp gross) is an order below the ~18 bp round-trip taker cost**. The one thing that could have saved it — **maker / passive execution** — we have now **tested and it fails** (see §5b): adverse selection on a fade entry more than eats the price improvement, and the walk-forward is NO-GO even at *zero* fee.

> **We are no longer asking "find us the path." We are asking you to try to REFUTE our refutation:** is our maker-fill / adverse-selection model wrong, or missing an execution style (e.g. a smarter passive/aggressive hybrid, a different horizon, cross-venue) that would make a ~2 bp gross edge executable? If you agree it's dead, we retire DEV_FADE.

---

## 1. The strategy
- **Signal:** DEV_FADE — deviation-fade mean reversion. Enters *against* a short-term move (buy after a down-tick cluster, sell after an up-tick cluster), expecting reversion.
- **Universe:** BTC, ETH, ADA, BNB, DOT, SOL, XRP — all vs USDT.
- **Horizon:** intra-minute; positions currently exit on a 15-min TIMEOUT (TP/SL effectively never hit — see §2).
- **Sizing:** fixed small paper size. **Learning:** Bayesian calibration + EV gating (downstream of the signal; it correctly learns to *not* trade when EV<0).

## 2. Empirical performance (paper, verified from raw data — not the dashboard headline)
| Metric | Value | Source |
|---|---|---|
| Lifetime trades | 17,102 | `learning_state.json` lifetime_n |
| Lifetime profit factor | **0.679** | learning_state |
| Lifetime expectancy/trade | **−0.027** (net, loss) | learning_state |
| Current DB rows | 1,023 | `cache.sqlite:closed_trades` |
| Exit-reason split of those 1,023 | **TIMEOUT 1023 / TP 0 / SL 0** | cache.sqlite |
| Last-100 window | WR **39%**, PF **0.591** (pct basis), net **−$0.50** | cache.sqlite |

**Key tell:** *everything* exits on TIMEOUT — neither the take-profit nor the stop is ever reached. The move is too small to hit either barrier; the position just decays to a small (usually negative-after-cost) P&L and times out. This is the fingerprint of "signal magnitude < cost", not of a bad stop/target.

## 3. Observation-only evidence (the load-bearing dataset)
We stopped opening positions (`PAPER_DATA_COLLECTION_ONLY=1`) and instead **recorded, for every DEV_FADE signal, the actual 1-second forward price path and first-barrier crossings** — no execution, no market impact, pure counterfactual.

- **N = 3,452** observations, all `data_quality=ok`.
- Favorable forward excursion: **median +1.2 bp, mean +0.83 bp**, max favorable first-crossing **~15 bp** (never reached +20 bp within 15 min).
- **~58%** of observations end on the favorable side (signal *is* directionally predictive).
- **Caveat (important):** the sample is **~98% BULL_TREND and ~92% ETHUSDT** — one regime, one symbol, ~12–24 h. A fader should do *best* in RANGING/quiet and *worst* in trends, so a trend-heavy sample is arguably a lower bound — but this cannot yet answer regime-conditioning. A definitive read needs ≥14 days, multi-regime.

## 4. Cost picture
- Assumed **taker round-trip ≈ 18 bp**.
- **Break-even taker round-trip ≈ 2 bp** (horizon-F mean +2.05 bp on n=9305).
- At 18 bp the edge is buried ~8× under cost.

## 5b. Maker/passive-fill model result (n=9305) — the hypothesis, tested
`scripts/maker_fill_model.py` simulates a passive entry E bp better than reference: it fills **only** when the 1s path first moves E bp *against* the trade (adverse), then holds to horizon (conservative — passive exit not modelled). Unfilled = no trade.

| passive offset E | fill rate | adverse-selection gap vs full sample |
|---|---|---|
| 2 bp | 59% | **−3.9 bp** |
| 4 bp | 46% | **−4.8 bp** |
| 6 bp | 31% | **−6.2 bp** |

- **Best unconditional expectancy by round-trip cost:** 0 bp → +2.0 (best E=0, i.e. just take); 2 bp → +0.005; **3 bp → −0.21; 18 bp → −0.99**. Passive entry never beats taking.
- **Walk-forward OOS (pick E\* on train, test once):** test expectancy **−0.26 bp @3 bp**, **−0.09 bp @0 bp** (negative even fee-free), −1.08 @18 bp → **NO-GO-OOS**.
- **Reading:** the price improvement from posting passively is *more than cancelled* by adverse selection — you get filled precisely when the fade is wrong. Maker execution makes DEV_FADE **worse**, not better.
- **Caveat:** dataset is still ~97.6% BULL_TREND (RANGING only 221 of 9305), 94% ETH. A fader's *best* regime is under-sampled — but adverse selection on a fade entry is structural. This is the main thing we want you to stress-test.

## 5. The two numbers that must not be conflated
| Framing | Number | Meaning | Trust |
|---|---|---|---|
| In-sample best-config sweep, **zero cost** | +2.83 bp/trade (TP=10/SL=5, PF 2.52, WR 59%) | best TP/SL chosen with hindsight on the same rows | **optimistically biased** |
| Out-of-sample walk-forward (train/val-select → **test once**), **18 bp cost** | **−19.3 bp/trade, PF 0**, 95% CI [−19.9, −18.7] | honest generalization estimate | **this is the verdict** |

The OOS walk-forward is the one that counts: **NO-GO at 18 bp**. The zero-cost story is real but **not OOS-validated at any realistic cost**. So maker execution is a *hypothesis to test*, not a demonstrated edge.

## 6. What we're asking you (specifically)
1. **Adverse selection:** for a mean-reversion *entry*, a passive limit at/inside the touch gets filled preferentially when the move *continues against you* and skipped when it reverts. Does that systematically destroy the ~1–3 bp gross edge? Is there a known correction/estimate for fade-entry passive fills?
2. **Achievable cost:** on liquid pairs (ETH/BTC), is ≤3–4 bp round-trip realistically reachable (maker rebate / fee tier / venue), or is the effective floor higher once adverse selection is priced in?
3. **Class fit:** is a 1-second fade even the right instrument for this edge, or is a ~1 bp gross edge simply un-executable regardless of cost engineering?
4. **Regime:** given the fader thesis, how much should we weight a 98%-BULL sample, and what multi-regime coverage would you require before trusting any GO?

## 7. What is NOT in scope
- **No real trading.** REAL is a hard NO-GO regardless of this consult.
- **Not a safety/infra review** — that's had 5 external audit rounds; safety, deploy gating, and fail-closed real-order guards are done.
- **Not the learning loop** — learning is downstream of the signal; it cannot manufacture an edge the signal lacks (it already correctly gates to ~no trades).

## 8. Data we can hand over
- `closed_trades.csv` — full row-level trade history (schema-flexible, no secrets).
- Reduced shadow export (`shadow_excursion_observations` + `shadow_first_crossing` full; `shadow_path_1s` reducible to full 1-second paths on request) — the counterfactual input.
- `scripts/e1_e4_counterfactual.py` — the walk-forward TP/SL analyzer (methodology to critique).
- `scripts/maker_fill_model.py` — the maker/passive-fill + adverse-selection model (§5b) — the one we most want you to try to break.
- `STRATEGY_EDGE_ANALYSIS.md` — our own writeup (with the maker-refutation update at the top).

---
*Prepared for external strategy/execution consultation. All numbers verified against raw `cache.sqlite` / `learning_state.json` / the shadow dataset on 2026-07-19.*
