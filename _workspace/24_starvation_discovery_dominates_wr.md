# Finding + fix: PAPER_STARVATION_DISCOVERY is 89% of trade volume and drags WR down

**Date:** 2026-08-14
**Trigger:** Operator directive "udelej vse pro zvyseni wr a prover proces uceni a autoadjustace strategie"
(do everything to increase WR and verify the learning process / strategy auto-adjustment)

## Forensic evidence

Live server, `rolling100` (last 100 canonical-learned trades), broken down
by `admission_bucket`:

| bucket | n | win | loss | flat | WR |
|---|---|---|---|---|---|
| PAPER_STARVATION_DISCOVERY | 89 | 10 | 33 | 46 | **11.2%** |
| A_STRICT_TAKE | 6 | 2 | 0 | 4 | **33.3%** |
| None | 5 | 0 | 3 | 2 | 0.0% |

`PAPER_STARVATION_DISCOVERY` is `maybe_open_training_sample()` in
`paper_training_sampler.py` -- explicitly documented as "Try opening a
paper training sample when normal RDE rejects" / "AGGRESSIVE MODE: Disable
all quality gates for trading" -- it admits candidates the primary EV gate
already rejected (`reason=REJECT_NEGATIVE_EV`), by design, to keep
collecting learning data even when the "good" path finds nothing.

**89% of all recent trade volume comes through this deliberately-EV-negative
path**, while the actual EV-gated path (`A_STRICT_TAKE`, 3x better WR) is
only 6% of volume. The headline WR being stuck at 9-20% all session is
therefore driven at least as much by *volume mix* as by underlying signal
quality on the EV-gated path.

## Is the learning system working?

Yes, partially -- checked directly:

```
regime_tp_learning_enabled: True, blend: 1.0
segment_weights (7 live segments):
  ADAUSDT:BEAR_TREND:BUY   0.25  (floor -- confirmed bad)
  ADAUSDT:BULL_TREND:BUY   1.95  (near ceiling -- confirmed good)
  SOLUSDT:BEAR_TREND:BUY   2.00  (ceiling -- confirmed good)
  SOLUSDT:BULL_TREND:BUY   1.60
  SOLUSDT:BEAR_TREND:SELL  0.25  (floor)
  ETHUSDT:BULL_TREND:BUY   0.25  (floor)
  ETHUSDT:BEAR_TREND:SELL  0.25  (floor)
```

`_update_segment_policy()` (runs on every `record_close()`) correctly
identifies good/bad segments -- 4 of 7 segments have been pushed all the
way to the 0.25 downweight floor by real, repeated losing evidence, 2 are
near the 2.0 upweight ceiling. The *computation* is not broken.

**But it has ~zero practical effect on the dominant path.**
`_apply_adaptive_policy_to_paper_candidate()` -- the function that turns
`segment_weights` into an actual `size_mult` -- explicitly refuses to run
for `ev <= 0` candidates ("Never apply policy to EV<=0 candidates... never
fabricates positive EV"). Correct in isolation, but `PAPER_STARVATION_
DISCOVERY` candidates are EV<=0 *by construction* (they're the ones the
primary gate rejected), so this guard silently no-ops for ~89% of all
trades. The learner computes a confident, correct verdict and it is never
consulted for the one path that actually needs it.

Two existing cooldown mechanisms look like they should already cover this,
but don't:
- `_bootstrap_discovery_cooldown_from_learner()` (bucket-level): trigger
  requires `pf == 0.0` **exactly** (zero wins). Live discovery data has 10
  wins out of 89 -- WR 11.2%, not 0% -- so this has never fired despite the
  bucket being a clear net drag.
- `_bootstrap_segment_cooldowns_from_learner()` (segment-level): scoped
  **only** to `admission_bucket == "C_WEAK_EV_TRAIN"`, never checks
  `"PAPER_STARVATION_DISCOVERY"` at all.

## Fix (this session)

`maybe_open_training_sample()`: before the aggressive-mode "allow
everything" block, check the candidate's segment (`symbol:regime:side`)
against the learner's `rolling100`-derived sample count and
`segment_weights`. If `segment_n >= 20` (same threshold
`_update_segment_policy()` itself requires before touching a weight at
all) **and** `segment_weight <= 0.25` (the downweight floor -- sustained,
repeated losing evidence, not one bad reading), refuse admission
(`reason: "segment_confirmed_bad_skip_discovery"`) instead of opening yet
another sample.

Deliberately narrow:
- Does not touch the primary RDE/EV-gating logic (out of scope, exhaustively
  investigated in earlier sessions -- near-zero exploitable edge confirmed
  from 4 independent angles).
- Does not touch Gate 2 / real-trading safety in any way.
- Does not fabricate EV -- it stops re-sampling a segment the learner has
  *already* reached a confident verdict on; segments still being explored
  (`n < 20`) or only partially downweighted continue exactly as before, so
  the discovery/learning function itself is preserved.
- Fails open on any internal error (log + fall through to normal admission),
  never fails closed and blocks discovery entirely on an unrelated bug.

5 new tests in `tests/test_paper_training_sampler_segment_skip.py`
(confirmed-bad segment skipped; not-yet-confirmed segment still admitted;
partially-downweighted-but-not-floor segment still admitted; a different
segment's bad weight doesn't leak into an unrelated segment; a learner
lookup error fails open). Full `tests/test_paper_mode.py` +
`tests/test_app_metrics_contract.py` (the exact set the deploy gate itself
runs) confirmed clean except one pre-existing, unrelated, local-environment-
only failure (`.env` has a stray `PAPER_TRAIN_STRICT_TAKE_ENABLED=true`
from an earlier session, unrelated to this file). 10 pre-existing failures
in the broader `test_p11ap_o2_*`/`test_p11ap_n2_*` suite confirmed via
`git stash` to be identical before and after this patch (test-isolation
issues in that suite, not a regression).

## Expected effect / what to watch

This does not touch signal generation -- it only stops feeding MORE trades
into segments already conclusively proven bad. Expected effect: the
blended headline WR should drift toward the two remaining populations'
weighted average as confirmed-bad segments stop contributing further
losing samples, while segments still being explored (or already confirmed
good, at the 2.0 ceiling) keep flowing normally. This is a volume-mix fix,
not a signal-quality fix -- the deeper, still-open lever (wiring the
cost-aware P0.8-P1.2 strategies into the live loop, or reducing the primary
EV gate's near-total rejection rate) remains the larger, harder task if
this alone doesn't reach the WR>55% goal.
