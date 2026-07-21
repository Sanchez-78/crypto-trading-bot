# M5 Venue-Cost Arithmetic — Early-Decision Memo (2026-07-21)

**Claim under test:** the maker-execution experiment (M1–M5) can be decided by M5 (realistic venue
costs) TODAY, without waiting out the ~30-day data budget. This memo lays out the arithmetic and
asks the external auditor to confirm or refute the early stop (see `EXTERNAL_AUDIT_PROMPT_v8.md`).

## 1. What the enriched data says the strategy can afford
First real OOS read of the corrected v2 model (run 29776673209, live enriched sqlite, conservative
= spread-adjusted executable scenario, GO hard-locked off):

- conservative: `test_exp = +0.14 bp` per admissible signal **at an assumed 4.0 bp round-trip**,
  52 OOS fills, fill rate 1.2%, single symbol, ~single regime (PRELIMINARY, thin — but directional).
- midpoint (non-executable ceiling): `test_exp = +0.017 bp` at 1.0 bp round-trip; train 0.59 bp.
- Implied gross per FILLED trade ≈ cost + net ≈ **~4.1 bp** (conservative config E*=3, TIF 3s).
- Auditor §8 requires net expectancy > 0 **with a +2–3 bp reserve** → the strategy affords a
  realistic round-trip of roughly **≤ 1–2 bp**. Even the modeled 4 bp fails the reserve today.

## 2. What a realistic Binance spot tier actually costs (verified 2026-07-21)
- VIP0: **10 bp maker / 10 bp taker**; with BNB 25% discount: **7.5 bp/side**.
- Maker-in + maker-out round-trip at VIP0+BNB: **~15 bp** (plus spread/queue/partial-fill effects).
- VIP1 (needs $250k 30-day volume): 9 bp maker — immaterial change.
- VIP9 (needs **> $2 B monthly volume**): 2 bp maker → ~4 bp round-trip. This — coincidentally —
  is what our "conservative" scenario assumed. **It is not an attainable tier for this account.**
- Zero-fee promo pairs (historically BTC/FDUSD etc.): promotional, revocable, different pairs than
  the recorded USDT dataset; search found no confirmation of current zero-fee spot pairs. Not a
  structural basis for a strategy, and our data does not cover those books.

Sources: [Binance maker/taker fee guide 2026](https://binancemakertakerfee.org/),
[Bitget Academy: Binance fees 2026](https://www.bitget.com/academy/binance-fees-2026),
[Binance VIP0 spot fee](https://binanceviplevelsfee.com/vip-0-spot-fee.html).

## 3. The arithmetic
| Round-trip cost | Net per filled trade (gross ~4.1 bp) | Verdict vs §8 (needs > 0 with +2–3 bp reserve) |
|---|---|---|
| 1–2 bp (affordable) | +2.1 … +3.1 bp | would pass reserve — **no attainable tier delivers this** |
| 4 bp (VIP9 fantasy = our "conservative") | +0.14 bp | fails the reserve |
| 15 bp (attainable: VIP0 + BNB) | **≈ −10.9 bp** | catastrophically fails |

Can more data rescue it? **No.** The recorded 1s favorable-excursion paths bound the achievable
gross from above: unconditional expectancies are sub-1 bp; per-fill gross ~4–7 bp at 1–3% fill
rates. A 15 bp wall needs a gross edge an order of magnitude larger than anything the six-class
cost-wall screen (`RESEARCH_COSTWALL_FINDINGS.md`) or the shadow dataset has ever shown at these
horizons. Waiting 30 days changes the confidence interval, not the order of magnitude.

## 4. Honest caveats (why this is a proposal, not a unilateral verdict)
- The 0.14 bp / 4.1 bp gross figures come from **thin, single-symbol, ~single-regime** OOS data
  (52 fills). The TRUE multi-regime gross could differ — but it would need to be **>15 bp** to
  matter, which the midpoint *ceiling* (~1.6 bp unconditional) already excludes.
- The recorder measures midpoint paths; conservative subtracts spread/2. Fee arithmetic is
  additive on top and does not depend on the fill-model subtleties the auditor critiqued in v6.
- Passive data collection costs nothing and continues regardless (daily coverage run automated).

## 5. Proposed decision (pending auditor v8)
Invoke the §8 kill switch early: **retire DEV_FADE definitively** on M5 arithmetic — the binding
constraint (execution cost ≥ 15 bp attainable vs ≤ 1–2 bp affordable) is structural for this
venue/account, not statistical. Continue passive collection until the auditor answers (free), then
either (a) archive + pivot per the auditor's guidance, or (b) if the auditor identifies a concrete
attainable ≤ 2 bp execution path we missed, continue the M-series on it. **REAL = NO-GO throughout.**
