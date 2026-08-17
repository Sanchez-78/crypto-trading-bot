# Re-analysis: the learning process after the complete repair pass

**Date:** 2026-08-17
**Trigger:** Third step of the operator's directive ("...pak vse znovu
analyzuj jestli je funkcni" -- then re-analyze everything to see if it's
functional), following the `_workspace/28→30` fix and the `_workspace/31`
cleanup.

## What changed since the `_workspace/29` audit

1. **Fixed** (`_workspace/30`, deployed): `SKIP_SCORE_HARD` no longer
   unconditionally `return None`s -- once idle reaches 1800s, it now
   routes through the same shared `_try_discovery_admission()` mechanism
   `REJECT_NEGATIVE_EV` already used. This was the structural blocker that
   could (and did, for 66+ hours) prevent the two live learning
   mechanisms below from ever getting a chance to run at all.
2. **Removed** (`_workspace/31`, deployed): the fully-dead V4
   genetic-algorithm strategy selector and V5.1 RL/DQN agent -- imports,
   module-level state, all four functions, and the startup init block, all
   confirmed to have zero live callers.

## Live re-verification (post-deploy, same session)

Checked directly against the running process within minutes of the
deploy, not just static code analysis this time:

| Mechanism | Live evidence checked | Result |
|---|---|---|
| `segment_weights` | `[PAPER_POLICY_ADAPTATION]` log frequency | 50 hits / 5 min -- still firing |
| `regime_tp_strategy` | `[LEARNING_TP_USED]` log frequency | 56 hits / 5 min -- still firing |
| Startup sequence | `[N/7]` progress log | Cleanly `[1/7]→[2/7]→[4/7]...[6/7]`, old `[3/7] genetic algorithm` step gone, no gap/error |
| Process health | `systemctl is-active`, journalctl error grep | active, zero tracebacks/import errors in the minutes after deploy |
| Trade throughput | `[PAPER_ENTRY]` count | 45-122 per few-minute window -- healthy, not stalled |
| `SKIP_SCORE_HARD` escape hatch | idle_s at deploy time | Reset to ~0 by the restart itself (this file's own `_last_trade_ts` re-initializes at import); trading resumed on its own before idle could reach the 1800s trigger, so **the escape hatch itself has not yet been exercised live** -- see caveat below |

## Important honesty check: what actually ended the 66-hour stall?

The stall ended (bot started admitting `RDE_TAKE` trades again through the
**normal, already-existing** EV-gated path, not through the newly-added
escape hatch) **before** this session's `SKIP_SCORE_HARD` fix was even
deployed to verify it -- live logs show ~118 successful `RDE_TAKE`
admissions in the 10 minutes immediately preceding the fix's deploy,
while `SKIP_SCORE_HARD`/`REJECT_NEGATIVE_EV` were still rejecting many
other candidates the old way. In other words: **the underlying EV/score
computation improved on its own** (market conditions changed, or enough
new history accumulated to shift the rolling EV calculation) -- this
session did not observe proof that the new escape hatch itself has fired
in production yet, since idle time never re-accumulated past 1800s once
normal trading resumed.

This does not invalidate the fix -- the gap it closes (a persistently
negative EV/score silently stalling everything with zero fallback) is
real, evidenced, and will matter again the next time the signal quality
dips for an extended stretch. But it means this session cannot claim
"the fix caused the resumption" -- only "the fix is deployed, verified
not to have broken anything, and will be ready the next time it's needed."
Flagging this explicitly rather than overclaiming.

## Current state of "the learning process" (post-repair)

Unchanged from `_workspace/29`'s core finding, now with the access path
fixed and the clutter removed: **exactly two mechanisms** close the loop
from "the bot learns something" to "the bot's behavior changes as a
result" --

1. `segment_weights` -- per-`symbol:regime:side` sizing (EV>0 path) +
   admission skip for confirmed-bad segments (discovery path, with the
   `_workspace/27` idle-based safety valve).
2. `regime_tp_strategy` -- adaptive TP target per regime+volatility band.

Both are now reachable via the widest possible set of rejection paths
(the `SKIP_SCORE_HARD` fix), and the codebase no longer contains
misleadingly-named dead subsystems (RL agent, genetic algorithm) that a
future reader could mistake for live behavior.

## What remains genuinely unresolved

- The deeper issue this whole investigation keeps circling back to:
  the primary signal path's EV has been independently confirmed
  near-zero-to-negative across this session and prior ones. Neither
  today's fix nor the cleanup changes that. `lifetime_pf` remains ~0.27,
  well below profitable.
- Whether `SKIP_SCORE_HARD`'s escape hatch actually works correctly in a
  real 1800s-idle scenario is still empirically unverified in production
  (only unit-tested in isolation, per `_workspace/30`). Next occurrence of
  a genuine extended stall is the real test.
- The bigger, already-repeatedly-flagged lever (wiring the cost-aware
  P0.8-P1.2 strategies into live admission, or a deeper redesign of the
  primary EV computation) remains the larger, harder, still-untouched
  task for actually reaching WR>55%/high P&L.
