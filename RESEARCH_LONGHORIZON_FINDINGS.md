# Long-Horizon Pivot — Findings (2026-07-21)

**Question:** second-scale strategies die on the ~15 bp attainable cost wall
(`RESEARCH_M5_COST_ARITHMETIC.md`). At multi-hour holds, moves are 100-500 bp, so cost is
friction not a wall. Do LONG-HORIZON, LONG-ONLY (spot) strategies clear realistic costs OOS?
Tested on 1h Binance spot klines for the 7 traded USDT pairs, 2023-01 .. 2026-06 (30,647 bars each,
data.binance.vision). Scripts: `scripts/research/longhorizon_{screen,walkforward,robustness}.py`.

## Step 1 — fixed configs (train 2023-24 select, test 2025-26 OOS): ALL FAIL
Every family: strong positive TRAIN, strong negative TEST — textbook overfitting.

| family | TRAIN exp | TEST exp @15bp |
|---|---|---|
| tsmom | +54 bp | **−53 bp** |
| MA filter | +73 bp | **−37 bp** |
| donchian | +338 bp | **−121 bp** |
| xsec momentum | +273 bp | **−86 bp** |

## Step 2 — walk-forward adaptive (re-select monthly on trailing 12mo): 2 survive... apparently
This is the honest "self-learning" test: each month picks the best config on prior data, trades the
next month (true OOS). tsmom/MA stay dead (~−1.5 bp). donchian +72 bp and xsec +75 bp looked ALIVE
(survive 20 bp stress). **Treated as a LEAD, not an edge** — the maker story also looked positive
and drew auditor verdict C.

## Step 3 — skeptic battery on the two survivors: LEAD REFUTED
| check | donchian | xsec | pass? |
|---|---|---|---|
| bootstrap CI[5,95] of mean net | **[−26, +196] bp** | **[−37, +196] bp** | ❌ lower < 0 |
| net by year | 2024 **+68186**, 2025 −10189, 2026 −15380 | 2024 **+30390**, 2025 −586, 2026 −11525 | ❌ all profit in 2024 |
| up-market vs down-market net | +57703 vs **−15085** | +51061 vs **−32782** | ❌ wins only when market up |
| max single-symbol profit share | 0.27 (XRP) | 0.22 (XRP) | ✅ (only passing check) |

**Verdict:** the apparent walk-forward edge is **2024 bull-market BETA, not alpha.** The adaptive
learner rode a rising market; when 2025-26 turned choppy/down it lost. Statistically insignificant
(CI spans zero), time-concentrated (one year), and directional (long-only beta). No durable,
market-neutral, cost-surviving edge.

## Cumulative honest scoreboard
Ten strategy families now fail rigorous OOS + realistic cost testing:
6 second-scale (`RESEARCH_COSTWALL_FINDINGS.md`) + 4 long-horizon (fixed AND adaptive, here).
The self-learning mechanism itself works (it adapts, selects, gates honestly) — but it can only
harvest what is in the strategy space, and price-only momentum/reversion/breakout on 7 majors
contains only beta + noise after costs.

## What this does and does not imply
- **Does NOT imply** the learning infrastructure is broken. It correctly refuses to manufacture edge.
- **Does imply** that net-of-cost profit needs one of:
  1. a richer information set where alpha may actually live — funding rates / basis, order-book
     microstructure, on-chain flows, cross-asset/macro, sentiment — a real research project, not tuning;
  2. short capability to harvest down-markets (futures) — but that adds leverage/liquidation risk and
     is outside the spot-only, REAL=NO-GO constraint, and momentum-short decay is its own problem;
  3. an explicit beta-timing mandate (be long only in detected bull regimes) — honest, but it is
     "own the market when it rises", not a market-neutral strategy, and it loses in bear markets.
- Open for the external auditor (v8 Q3): rank these, or declare the goal not attainable under the
  current constraints (spot-only, price-only, single retail account, realistic costs).

**REAL trading = absolute NO-GO throughout. No metric-gaming: every number here is out-of-sample.**
