# 45 — SOLUSDT:BEAR_TREND:BUY (historically PF 3.53) has gone completely silent — new lead, NOT fixed this cycle

## Status: FOUND, forensically traced to signal-direction generation (not admission blocking), NOT YET root-caused to the code level. Needs a dedicated future cycle.

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
