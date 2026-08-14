# Finding + fix: the segment-skip fix (cycle 73) caused a total admission stall

**Date:** 2026-08-14, ~4h after the cycle-73 segment-skip fix deployed
**Severity:** High -- zero trades opened for a full hour in production

## Symptom

Routine monitoring cycle noticed `closed_trades` had gone from +93/+36/+18/+7
per 30-min window (a clear decline) to **+0**, with 0 open positions. Direct
investigation found:

```
[PAPER_TRAIN_HEALTH] open=0 closed_1h=0 entries_1h=1435 target_1h=6 learning_updates_1h=134 status=OK
```

1,435 candidate entries evaluated in the last hour, **zero** admitted. The
pre-existing watchdog (`bot2/main.py`) had been escalating for a while:

```
[WATCHDOG] Critical idle (15min) → enabling micro-trades
[HBLOCK] ... idle=9149s zone=CRITICAL ...
```

idle_s had climbed to 9,000+ seconds (2.5h+) with no sign of clearing on
its own, despite the watchdog's own escalation attempts.

## Root cause

`_workspace/24_starvation_discovery_dominates_wr.md`'s fix
(`maybe_open_training_sample()`, deployed cycle 73) refuses admission when
a segment has `segment_n >= 20` and `segment_weight <= 0.25` (the
downweight floor). Checked live segment_weights at the time of the stall:

```
total segments tracked: 8
at floor (<=0.25): 5   (ADAUSDT:BEAR_TREND:BUY, SOLUSDT:BULL_TREND:BUY,
                         ETHUSDT:BULL_TREND:BUY, ETHUSDT:BEAR_TREND:SELL,
                         ADAUSDT:BEAR_TREND:SELL)
still open: 3           (ADAUSDT:BULL_TREND:BUY=1.65,
                         SOLUSDT:BEAR_TREND:BUY=2.0,
                         SOLUSDT:BEAR_TREND:SELL=2.0)
```

Only 8 distinct `symbol:regime:side` segments are actively tracked at all
(a small universe: a handful of symbols × 2 trending regimes seen in
practice). The fix has no awareness of *aggregate* admission volume -- it
only ever evaluates one segment in isolation. When the market sits in one
or two correlated regimes for an extended stretch (routine in crypto --
alts move together), it's entirely possible for the *specific* regime
combinations the market is currently generating candidates in to be
exactly the ones already at the floor, while the 3 still-open segments
simply don't match current price action. The result: admission grinds
toward zero even though the skip mechanism, evaluated one segment at a
time, is behaving exactly as designed.

This is a real design gap in the original fix, not a coding bug: stopping
trades on a *provably bad* segment is correct in isolation, but doing so
with zero regard for how many of the small, finite segment universe are
simultaneously blocked can (and did) starve the whole discovery mechanism
-- which defeats its own purpose. A total stall is strictly worse than the
WR drag being fixed: zero trades means zero data *and* zero P&L, not
merely a worse win rate.

## Fix

Added a safety valve: `maybe_open_training_sample()` now checks
`_starvation_discovery_state["idle_s"]` (already tracked in this same
module) before applying the segment-confirmed-bad skip. Once idle time
reaches 900s -- the exact same "critical idle" threshold `bot2/main.py`'s
pre-existing watchdog already escalates on (`enabling micro-trades`) --
the skip is bypassed entirely, deferring to that existing escalation
signal instead of silently fighting it. Below 900s idle, the skip behaves
exactly as before (cycle 73's fix, unchanged).

This preserves the intended benefit (stop wasting trades on segments
already conclusively proven bad, during *normal* operation) while
guaranteeing the mechanism can never fully starve the discovery loop for
more than ~15 minutes, matching the pre-existing operational expectation
already encoded elsewhere in the codebase.

## Tests

`tests/test_paper_training_sampler_segment_skip.py` (extended): confirmed-
bad segment is admitted anyway once `idle_s >= 900`; still correctly
skipped just below the threshold (899s) -- the valve is a last resort, not
a general loophole. Writing the first of these two tests caught a real
subtlety in `maybe_open_training_sample()` itself: it resets `idle_s` back
to 0 on its own if `last_eligible_entry_ts` reads as the "never set"
sentinel (0.0) -- the test had to set both fields consistently to avoid
that fresh-startup reset masking the scenario being tested. 7/7 pass. Full
deploy-gate test set (`test_paper_mode.py` + `test_app_metrics_
contract.py`) clean except the same pre-existing local-env-only failure
documented in `_workspace/24_...md`.

## Lesson

Evidence-based fixes for one metric (WR, via volume mix) need to consider
their effect on *aggregate* system health (total throughput), not just
the metric being targeted in isolation -- especially in a small, finite
state space (8 segments here) where "most of them are simultaneously bad"
is a real, not just theoretical, scenario. Should have added this safety
valve in the original cycle-73 patch; didn't anticipate the segment
universe was small enough for simultaneous saturation. Caught within
~4 hours via routine monitoring, not left running stalled indefinitely.
