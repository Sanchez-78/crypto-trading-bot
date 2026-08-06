# Intake: "WR je male" (WR is low) — MAJOR finding, needs careful scoping

## User-triggered investigation
User flagged low WR (dashboard showing ~27-30% recent WR, PF ~0.9-0.95).
Full autonomy granted for monitoring/fixes/decisions.

## Segment breakdown (live, rolling100 from paper_adaptive_learning_state.json)
By admission bucket:
- A_STRICT_TAKE: n=37, WR=67.7%, sum_pnl=+1.368 — GOOD, healthy.
- C_WEAK_EV_TRAIN: n=31, WR=37.5%, sum_pnl=-0.403 — weak by design (name says so).
- PAPER_STARVATION_DISCOVERY: n=17, WR=45.5%, sum_pnl=+0.042 (near breakeven) —
  reasonable given it's deliberately negative/zero-EV exploration (recently
  unblocked by an earlier fix this session).
- None (bucket unset): n=15, WR=0%, sum_pnl=-0.724 — small sample, concerning
  but not yet investigated further.

By segment (top by volume):
- SOLUSDT:BULL_TREND:BUY: n=46, WR=76.5%, sum_pnl=+1.964 — excellent, dominant.
- ETHUSDT:BULL_TREND:BUY: n=24, WR=11.1%, sum_pnl=-0.785 — very bad.
- ETHUSDT:BEAR_TREND:SELL: n=20, WR=44.4%, sum_pnl=-0.191 — mediocre.
- SOLUSDT:BEAR_TREND:SELL: n=10, WR=0%, sum_pnl=-0.705 — very bad.

## THE finding: segment_weights are computed correctly but NEVER APPLIED

`paper_adaptive_learning.py._update_segment_policy()` (called from every
`record_close()`) correctly computes and persists `segment_weights` --
confirmed live: `SOLUSDT:BULL_TREND:BUY -> 2.0` (ceiling, correctly
upweighted), `ETHUSDT:BULL_TREND:BUY -> 0.50` and actively still
downweighting (`[PAPER_POLICY_ADAPTATION] ... action=downweight_losing_segment`
logged live at 09:50 and 09:55 today). The learning IS correct.

BUT: repo-wide grep shows `segment_weights` is referenced in exactly two
files: `paper_adaptive_learning.py` (writer) and
`firebase_learning_persistence.py` (persistence, my earlier fix). **Nothing
else in the codebase reads `self.segment_weights` to affect sizing or
admission.**

There IS a *separate*, independently-computed weight mechanism --
`paper_training_sampler.py:_apply_adaptive_policy_to_paper_candidate()`
(via `get_paper_policy_snapshot()`'s own `segment_weight` field, itself
derived from the same rolling data but tracked/applied differently) -- which
DOES compute a `weight_mult` and, if used, would do
`size_mult = size_mult * policy_result["weight_mult"]`
(`paper_training_sampler.py:2130`).

**But that application code is UNREACHABLE.** `maybe_open_training_sample()`
(the function containing it) has an **unconditional early return** at
`paper_training_sampler.py:2009-2022` ("AGGRESSIVE MODE: Skip all quality
gates - allow all trades" / `allowed_mode_all_gates_disabled`) that fires
for EVERY candidate with a valid bucket, BEFORE execution ever reaches the
`_apply_adaptive_policy_to_paper_candidate` call at line 2116 or the
`size_mult *= weight_mult` at line 2130. Confirmed: no `if` condition
gates the line 2009 return -- it is straight-line code after the
bucket/disabled-symbol checks.

## Root cause: a 2-month-old, self-documented EMERGENCY bypass never reverted

`git log -S"AGGRESSIVE MODE: Skip all quality gates"` ->
commit `bc96cbb`, 2026-06-05, by a prior Claude Haiku 4.5 session. Commit
message, verbatim: **"BREAKING CHANGE: paper_training_sampler now bypasses
ALL quality gates: No duplicate checks, No cost_edge validation, No idle
timer requirements, No position cap limits... This is an EMERGENCY mode to
get trading system operational. Production code should never ship with
this - requires proper quality gates. Testing only - revert before
production deployment."**

It was never reverted. It has been live for 2+ months. This is the SAME
root-cause class as the PAPER_STARVATION_DISCOVERY stall fixed earlier
today (paper_training_sampler.py's caps/cooldowns being dead code) --
same commit, same mechanism, wider blast radius than previously scoped.

## Why this must NOT be rushed / blindly reverted

The commit removed real logic in one shot: duplicate checks, cost_edge
validation, idle timer requirements, position cap limits, AND the segment-
weight application. Reverting the whole commit wholesale risks recreating
whatever "not operational" state necessitated the emergency bypass in the
first place (2 months ago) -- possibly some of what it removed has since
been superseded/reimplemented elsewhere in the pipeline (2 months of
subsequent development), possibly not.

## What must be verified before any patch
1. Are `_training_quality_gate`, `_check_cost_edge`/`_estimate_expected_move`,
   duplicate-checks, idle-timer, and position-cap logic that this commit
   removed from `maybe_open_training_sample` ALSO enforced somewhere else
   in the current pipeline (e.g. moved into `open_paper_position` itself,
   or into `realtime_decision_engine.py`, since 2026-06-05)? If yes for a
   given gate, its removal here is redundant/harmless. If no, that gate is
   genuinely gone.
2. What specifically breaks if JUST the "AGGRESSIVE MODE" unconditional
   return is removed (i.e., restore the pre-bc96cbb conditional flow) --
   does it recreate a stall/starvation condition (matching PAPER_STARVATION_
   DISCOVERY's 100%-blocked history), or does normal signal flow already
   provide enough volume that the removed gates would just filter cleanly?
3. NARROWEST possible fix: can the segment-weight application specifically
   be made to run (moving it, or making it run before the early return, or
   making the early return apply weight_mult before returning) WITHOUT
   reinstating the other four removed gates (duplicate checks, cost_edge,
   idle timer, position caps)? This is almost certainly the safer,
   properly-scoped fix -- narrow-patch-authoring discipline: fix the
   specific thing causing measurable harm (bad segments not being
   downweighted), don't undo a 2-month-old deliberate (if overdue) change
   wholesale in one shot.
4. Check `bucket=None` cohort (WR=0%, n=15) separately -- what admission
   path produces bucket=None, and is it a genuinely different, smaller
   issue or related to the same root cause?

## Scope
PAPER only. Do not touch real-trading gates. No recurring/cron loop. This
is exactly the kind of "BREAKING CHANGE" scope that deserves the full
forensics -> critical-review -> minimal-patch discipline, not a quick
one-liner given the history here.
