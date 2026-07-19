# Research Pivot Charter (2026-07-19)

**Decision (autonomous, after external audit kolo 6 verdict C):**
- **DEV_FADE current implementation → RETIRED.** Taker at ~18 bp is unviable; the current
  (midpoint-touch) maker model gives no deployable basis. Kept OFF (bot stays in
  `PAPER_DATA_COLLECTION_ONLY=1`, 0 positions).
- **DEV_FADE hypothesis → NOT declared dead** (audit says evidence is insufficient), but we are
  **not** spending the bounded M1–M5 research budget on it now — the corrected experiment would
  most likely just re-confirm NO-GO (real executable fills are worse than midpoint touches, not
  better). **Research pivots to a different signal class.**
- **Observation-only collection stays ON** (free, no positions) — if anyone later wants the
  corrected DEV_FADE experiment the raw paths keep accruing.
- **REAL trading = absolute NO-GO** (unchanged).

---

## The one hard lesson: the cost wall
Every failure so far traces to one thing: **execution cost (~18 bp taker round-trip) dwarfs the
signal's gross edge (~2 bp).** So the pivot is governed by a single filter applied *before* any
engineering:

> **A candidate signal is only worth building for if it plausibly clears the cost wall — i.e.
> either (a) gross edge comfortably > ~18 bp per trade, OR (b) a *validated executable* ≤ ~3 bp
> round-trip path.** If neither, do not build infra for it.

DEV_FADE failed (a) (2 bp << 18 bp) and could not prove (b) with the data we had.

## The evidence bar (do NOT repeat the kolo-6 mistakes)
Any future signal's edge claim must be established with the auditor's corrected methodology —
these are now standing requirements, not optional:

1. **Executable fills, not midpoint.** Use bid/ask + aggTrade (aggressor side) + a queue/partial
   proxy. `(bid+ask)/2` touch is NOT a fill. Report optimistic / base / conservative fill
   scenarios; the verdict must hold in base *and* conservative.
2. **Admissible-trade dataset.** Evaluate on trades that would actually pass every entry gate
   (EV, segment, time, exposure, per-symbol/max-open caps) — not raw pre-gate signal candidates.
3. **Fill-time & TIF.** Model when the fill happens and a post-only→cancel(→conditional taker)
   policy; P&L must be measured from the fill, with at least {exit at signal expiry, fixed hold
   from fill}.
4. **Purged nested walk-forward.** Purge/embargo ≥ one max horizon around the split; block/cluster
   bootstrap by time/regime episode; report *effective* sample size (overlapping paths ≠
   independent trials).
5. **Realistic, venue-specific costs.** maker fee/rebate + taker exit + spread + slippage +
   partial-fill/cancel + latency — from a concrete tier, not abstract 0/3/18.
6. **GO thresholds:** OOS PF ≥ 1.20, expectancy > 0 with ≥ +2–3 bp reserve after realistic
   costs, cluster-bootstrap 95% CI lower > 0, ≥ 200 OOS fills for the chosen policy, stable in
   ≥ 2 regimes (or explicitly regime-gated), no symbol > 50% of profit.

## Candidate directions (to be filtered by the cost wall — none chosen yet)
Kept as options for the operator; each must pass a **cheap offline feasibility check against the
cost wall before any code**:
- **Larger-move / lower-frequency capture** — a horizon/signal where the target move is 50–100+ bp
  so ~18 bp is a small fraction (directly attacks the cost wall via (a)). DEV_FADE's own shadow
  data shows moves are tiny, so this needs a *different* predictive signal, not this one.
- **Funding / basis / carry** — perp-spot or cross-exchange structural signals with holding
  periods long enough that per-trade cost is amortized.
- **Event / regime-conditioned** — trade only in states where edge is large enough to clear cost
  (e.g. a fader restricted to validated RANGING regimes — but that still needs the executable
  proof above, and multi-regime data we don't yet have).

## Next concrete step (cheap, before any infra)
For whichever direction is chosen: run an **offline feasibility check first** — does the raw gross
edge plausibly clear ~18 bp (or is there a real ≤3 bp execution path)? Only then build the
executable-fill dataset + model to the evidence bar above. **Lead with the cost-wall check; never
build first and measure later** — that is the mistake this whole arc corrected.

---
*Governs research direction after DEV_FADE retirement. Pairs with `CryptoMaster_EXTERNAL_AUDIT_REPORT_v6.md` and `AUDIT_CHANGES_LOG.md` (2026-07-19).*
