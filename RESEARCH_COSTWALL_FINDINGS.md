# Cost-wall screen — findings (2026-07-19)

First application of the `RESEARCH_PIVOT_CHARTER.md` cost-wall filter to candidate signal
classes, on **real Binance hourly data** (public mirror `data-api.binance.vision`), 7 USDT majors.
Read-only, offline, no trading. Scripts: `scripts/research/costwall_screen.py`,
`scripts/research/costwall_multiregime.py`.

## What was tested
Three canonical low-frequency signal classes, gross close-to-close returns (the *friendliest* case
— no execution frictions beyond a flat cost), net after **18 bp** taker round-trip and **6 bp**
(maker-ish). Chronological OOS split.

## Result: no simple signal clears the wall out-of-sample across regimes

### 180-day screen (one window)
| signal | OOS net@18 (median across 7 sym) | verdict |
|---|---|---|
| breakout | −41.7 bp | below wall (0/7 positive) |
| **tsmom** (168h lookback, 48h hold) | **+84.7 bp** | *looked like* it cleared (5/7) |
| revert (z-score fade) | −69.9 bp | below wall (0/7) |

### Why tsmom's +85 bp was a trap (the discipline that mattered)
- **Not bull-beta:** buy-and-hold over the window was **negative for all 7 symbols** (BTC −28%, ETH
  −38%, …). tsmom profited mainly via the **short side** (short net +21…+109 bp/sym) — genuine
  directional capture in a downtrend, not beta. It survived 3 chronological thirds too.
- **But it IS a regime artifact.** Trend-following shines in any sustained trend and bleeds in
  chop. That 180-day window was a clean downtrend — its best case.

### 3-year multi-regime + purged walk-forward (the evidence-bar test) — KILLS it
- **Full-period net@18 per symbol:** BTC −16, ETH +0.2, ADA +3, BNB −20, DOT +15, SOL +29, XRP −13
  → median ≈ 0, half negative.
- **Walk-forward test folds positive:** 1/4, 1/4, 2/4, 0/4, 2/4, 2/4, 2/4 → **no symbol robustly
  positive.**
- **By regime (efficiency ratio):** the bulk of trades (3218/3766) are low-efficiency/choppy and
  net **−7 bp**; only a thin trending slice is positive. On hourly bars a causal trend filter fires
  almost never (high-efficiency buckets: n=14, n=1) — so a regime-gated version has no sample.

## Honest conclusion
**None of the three simple signal classes reaches the goal (positive P&L after cost) out-of-sample
across regimes.** The one that looked promising (tsmom) was a single-regime artifact that the
multi-regime walk-forward killed — exactly the over-claim the charter's evidence bar exists to
prevent. Had the screen stopped at the 180-day window it would have falsely declared a winner.

This does not prove "no edge exists anywhere" — it proves **cheap, simple, close-to-close signals
do not clear an 18 bp wall on these 7 majors.** Reaching the goal would require genuine alpha
(better features / alt-data / microstructure execution edge), which is real quant work with a
real budget and human direction — not something a quick autonomous screen manufactures. Per the
charter, we do **not** build infra for a signal that hasn't passed the cost-wall check, and none
has. REAL trading remains absolute NO-GO.

## Round 2 (2026-07-20) — cross-sectional (relative-value) momentum: also fails
Tested a *different* class: rank the 7 symbols by past-lookback return, long the top / short the
bottom, market-neutral, longer holds (cost amortized). Best config (720h lookback, 168h hold,
2 long / 2 short) *looked* like a lead — **OOS net +12.4 bp/rebalance after 36 bp round-trip
(18 bp/leg × 2 legs), PF 1.29**. Then the stress test killed it:
- **The short leg LOSES** (−55 bp) — the entire spread profit is the **long leg (+114 bp) = market
  beta** (majors net rose over 3y). It is long-momentum in disguise, not neutral alpha.
- **Decays** across sub-periods: +102 → +68 → **+8 bp**; recent period barely positive.
- **Block-bootstrap OOS CI = [−272, +225] bp** — the +12 bp is statistically indistinguishable
  from noise (n=60, huge variance).

## Honest bottom line (both rounds)
**Two apparent edges (tsmom, cross-sectional momentum) each looked positive and each died under
proper scrutiny** (single-regime artifact; short-leg-is-beta + decay + no-CI). Within what this bot
can actually do — directional / cross-sectional trading of 7 spot majors at ~18 bp — **no durable
edge clearing the cost wall has been found.** Remaining ideas (funding/basis carry, cross-venue
arb) need capabilities the bot lacks (perp+spot legs, multiple venues). Reaching the goal, if
possible at all here, requires either new capabilities or genuine alpha (alt-data / microstructure),
not a screen over close prices. This negative is now the input to external audit v7. REAL = NO-GO.

## Reusable tooling (kept for the next candidate)
- `costwall_screen.py` — fetch + multi-signal cost-wall screen with OOS split.
- `costwall_multiregime.py` — long-history regime breakdown + rolling purged walk-forward.
- `xsec_momentum_screen.py` — cross-sectional (relative-value) momentum screen.
- `xsec_momentum_stresstest.py` — leg decomposition + cost/sub-period/bootstrap stress test.
Point them at any new candidate signal *before* writing any production code.
