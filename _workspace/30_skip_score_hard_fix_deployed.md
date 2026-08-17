# Fix deployed: SKIP_SCORE_HARD critical-idle escape hatch

**Date:** 2026-08-17
**Trigger:** Operator directive "proved kompletni opravu procesu uceni"
(perform a complete repair of the learning process), following up on
`_workspace/28`'s deliberately-deferred finding.

## What changed

`src/services/realtime_decision_engine.py`:

1. **Extracted** the discovery-fallback logic (paper exploration probe +
   P0-gated routing + `maybe_open_training_sample()` + `open_paper_
   position()`) out of the `REJECT_NEGATIVE_EV` branch into a new shared
   function `_try_discovery_admission(signal, route_reason, reject_reason,
   score_before_adj, score_adj)`. The `REJECT_NEGATIVE_EV` branch now
   calls this helper instead of inlining the ~75-line block -- behavior
   for that path is unchanged (same calls, same arguments, same order),
   verified by diff review and by the existing regression suite (see
   below) showing zero change in outcome.

2. **Added** a critical-idle escape hatch to the `SKIP_SCORE_HARD` branch:
   immediately before its `return None`, if
   `time.time() - _last_trade_ts[0] >= 1800.0` (30 minutes -- deliberately
   more conservative than the 900s "critical idle" threshold used
   elsewhere in this same function and in `hardblock_adapter.py`, since
   this is a more consequential last-resort for a more central gate), it
   now calls the same `_try_discovery_admission()` before returning.
   Below 1800s idle, behavior is completely unchanged (still an
   unconditional hard reject).

## Why this was safe to do now (vs. deferred in `_workspace/28`)

`_workspace/28` deferred this exact fix same-day, citing the risk of
touching the most historically fragile file in the codebase without a
full trace of the data flow. Between then and now:

- Did the full trace: confirmed `signal`, `_score_before_adj`, `_score_adj`
  are the exact same in-scope variables the `REJECT_NEGATIVE_EV` branch
  already uses for the identical call, at the exact point `SKIP_SCORE_
  HARD` needed them.
- Chose extraction over duplication specifically to avoid the two paths
  ever drifting out of sync -- a real risk if this were copy-pasted
  instead.
- Verified the extraction is behavior-preserving for the existing
  (already-live, already-relied-upon) `REJECT_NEGATIVE_EV` path via a
  careful diff review plus the full existing regression suite touching
  this area.
- Added 5 new unit tests for `_try_discovery_admission()` in isolation
  (happy path opens a position with correct metadata; P0 refusal opens
  nothing; sampler refusal opens nothing; exploration-probe exception
  doesn't propagate; sampler-import exception doesn't propagate).

## Tests

`tests/test_rde_discovery_admission_extraction.py` (new): 5/5 pass.
`tests/test_p0_4_rde_routing.py`: 8/8 pass (unchanged). Full regression
sweep across every test file referencing `evaluate_signal`/
`REJECT_NEGATIVE_EV`/`SKIP_SCORE_HARD`/`realtime_decision_engine`
(`test_observe_gate_choke.py`, `test_v10_13u_patches.py`,
`test_p1_paper_exploration.py`, `test_phase4b_starvation_paper_flow.py`):
27 pre-existing failures confirmed identical before/after via `git stash`
(test-isolation issues in those files, matching a pattern found
repeatedly elsewhere in this codebase's test suite this session -- not a
regression from this change), 235 passed both before and after.

**Caveat:** `evaluate_signal()` itself (the ~1000-line function both
changes live inside) has **zero existing direct test coverage** anywhere
in the suite -- no test calls it end-to-end. This session's verification
is necessarily indirect (isolated helper tests + careful diff review +
confirmed-unchanged regression suite), not a full end-to-end proof. Watch
production closely after this deploys.

## What to watch post-deploy

- `idle_s`/`_last_trade_ts`-derived idle was already past 1800s (in fact
  past 66 hours) at deploy time, so the escape hatch should fire on the
  very next `SKIP_SCORE_HARD` rejection -- expect `[PAPER_ENTRY]` log
  lines to resume quickly if the fix works.
- Watch for any new exceptions/tracebacks in `evaluate_signal`'s
  neighborhood immediately after deploy.
- If trading resumes: this doesn't fix the underlying negative-EV signal
  quality (still the deeper, larger issue) -- expect the SAME low WR this
  session has seen throughout, just with trades happening again instead
  of a total stall. Zero trades is a worse outcome than a low WR (no data,
  no P&L at all), so resumption itself is the win being targeted here.
