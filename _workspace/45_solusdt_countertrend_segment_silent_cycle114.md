# 45 — SOLUSDT:BEAR_TREND:BUY (historically PF 3.53) has gone completely silent — new lead, NOT fixed this cycle

## Status: FOUND, forensically traced to signal-direction generation (not admission blocking). **CYCLE 115 CORRECTION: the "promising lead" framing below was premature — split-sample analysis shows this is very likely the same time-concentrated regime-luck artifact already discredited for TP/SL in cycle 113, not a suppressed-but-valid edge. See Cycle 115 Correction section at the end before trusting anything above it.**

## Trigger

Continuing cycle 111-113's investigation into low WR/negative P&L, this
cycle (114) checked a different lever than exit geometry: segment-level
allocation. Is there an underexploited good segment or an actively-bad
segment being over-admitted?

## Finding

`segment_weights` in the live learning state (`paper_adaptive_learning_state.json`)
shows `SOLUSDT:BEAR_TREND:BUY -> 2.0` (upweighted 2x — the ONLY upweighted
segment out of 8). Historical performance justifies this fully:

| window | n | PF | WR% | mean pnl% |
|---|---|---|---|---|
| 720h (30d) | 185 | **3.53** | **68.1** | +0.112 |
| 168h (7d) | 0 | — | — | — |
| 72h | 0 | — | — | — |

**Zero trades in this segment for at least 7 days**, despite being the
single best-performing segment in the system by a wide margin (next-best,
`SOLUSDT:BULL_TREND:BUY`, is PF 1.25/1137 trades over 30d — good, but not
close to 3.53).

## Root-cause trace (partial — this cycle, live logs)

`SOLUSDT` is in `P0SegmentEVGate.QUARANTINED_SYMBOLS`;
`BEAR_TREND` is in `QUARANTINED_REGIMES`, with the comment "Paper trading
is long-only; BEAR_TREND should be short not long" (`p0_segment_ev_gate.py:97`)
— this quarantines the segment from STRICT_EV promotion, but NOT from the
evidence-collection path (`EVIDENCE_COLLECTION_REGIMES` includes
BEAR_TREND) — which is presumably how the 185 historical trades
accumulated in the first place.

Live journalctl (10min sample) shows repeated
`[SIGNAL_RAW] symbol=SOLUSDT side=SELL regime=BEAR_TREND` (trend-aligned
direction, `dir_src=signal_engine`, `WITH_REGIME`) — **no SOLUSDT BUY
signal in BEAR_TREND observed at all in the sample**. The visible
`[PAPER_STARVATION_SKIP_CONFIRMED_BAD_SEGMENT]` line in the same window is
for `SOLUSDT:BEAR_TREND:SELL` (the trend-aligned, confirmed-BAD segment,
weight 0.25 — correctly being skipped), not the BUY segment.

**Working hypothesis (NOT yet confirmed to the code level):** the core
signal generator currently only proposes the regime-aligned direction
(SELL during BEAR_TREND) for SOLUSDT; the countertrend BUY direction that
built the historically excellent 185-trade track record may have come
exclusively from `PAPER_STARVATION_DISCOVERY` bootstrap exploration
(which per earlier session findings can force otherwise-unlikely
candidates), and that exploration path may no longer be reaching this
specific symbol/regime/side combination -- for a reason not yet traced
(could be a cap, a starvation-idle policy interaction, a regime-detection
change, or something else entirely).

## Why this is NOT fixed this cycle

1. The exact mechanism preventing BUY-direction SOLUSDT/BEAR_TREND
   candidates from being generated/admitted is not yet identified at the
   code level -- only observed as an absence in a live log sample.
   Acting without that would violate this project's own evidence-first
   discipline.
2. `QUARANTINED_REGIMES`'s stated rationale ("BEAR_TREND should be short
   not long") is already known from an earlier session to be partially
   stale (`trend_cost_aware_v1` has a real `short_candidate()` path,
   contradicting the "long-only" framing) — touching this quarantine
   logic needs its own careful, dedicated forensic pass given its history
   of being a source of confusion, not a quick same-cycle edit.
3. n=185 over 30 days, while a strong PF/WR, is still a bucket that needs
   its own sanity check (symbol concentration is moot since it's
   single-symbol by definition; but time-clustering/regime-persistence
   should be checked — was this PF 3.53 driven by one sustained SOL rally
   during the 30-day window, similar to the split-sample fragility found
   in cycle 113's TP/SL analysis?) before treating it as a durable,
   reactivatable edge.

## Recommended next step (dedicated future cycle)

1. Trace `signal_engine.py`'s direction-selection logic for
   countertrend-vs-trend-aligned signal generation — is BUY-in-BEAR_TREND
   structurally suppressed at the raw-signal level, or only failing to
   reach admission?
2. If structural: understand whether this was ever a deliberate,
   documented design choice (matching the quarantine comment's "long
   only" framing) or an accidental regression.
3. Run the same split-sample robustness check cycle 113 used on the
   TP/SL counterfactual (first-15d vs second-15d of the 30-day window) on
   this segment's 185 trades before trusting the aggregate PF 3.53 as
   durable.
4. Only then design a minimal, reviewed change (if warranted) to
   reactivate exploration into this specific segment, through the
   existing evidence-collection/exploration paths -- not by simply
   removing SOLUSDT from `QUARANTINED_SYMBOLS` wholesale, which would
   also affect the confirmed-bad `SOLUSDT:BEAR_TREND:SELL` segment and
   other SOLUSDT segments not part of this investigation.

## Cycle 115 correction: the split-sample check (item 3 above) was run, and it weakens this lead substantially

Ran the same robustness check cycle 113 applied to the TP/SL counterfactual.
Chronological breakdown of all 185 trades:

- **All 185 trades occurred between 2026-07-30 13:40 and 2026-08-06 01:30
  -- a single ~6.5-day window, roughly three weeks before this cycle
  (2026-08-25), not "the last 7 days" as the framing above implied.** The
  segment has actually been silent for ~19 days, not 7.
- Split in half by time: first half (n=151) PF 3.995; second half (n=34)
  PF 1.409 -- already a steep within-window decay.
- Split into thirds: third 1 (n=61) PF 2.11; **third 2 (n=61) PF 22.2**
  (WR 90.2%, driven almost entirely by TIMEOUT exits with a slight
  positive drift, not TP hits -- an unusual pattern in itself); third 3
  (n=63, the most recent of the three, closest to when the segment went
  quiet) PF **1.01 -- essentially breakeven**, WR 46.0%.

**Interpretation:** this looks like the same time-concentrated,
regime-specific-luck signature already discredited for the TP/SL
counterfactual in cycle 113 (and for the price-only momentum leads
earlier in this project's research arc): performance is real but
concentrated in a specific, short, past window (plausibly a genuine SOL
price bounce that the regime detector mislabeled or continued to call
BEAR_TREND through), decays sharply within its own active period, and
has produced nothing at all for three weeks since. This does NOT look
like "a good segment currently being wrongly suppressed" -- it looks more
like "a temporary artifact from a specific past week that naturally
stopped recurring."

**Revised recommendation:** downgrade this from "promising lead worth a
dedicated forensic cycle" to "low priority, likely another discredited
regime-luck pattern." Do not invest further session time chasing this
specific segment without first checking whether a *different* mechanism
(not this one) currently shows a genuinely recent, sustained, split-stable
positive segment -- this one does not qualify on the evidence gathered
so far.
