# 40 — Starvation-discovery idle_s tracking is dead code (rejected fix, cycle 108)

## Status: FOUND, PATCH REJECTED, REVERTED. Not deployed, not committed.

## What happened

Following up on cycle 107's admission-deadlock fix (commit `fc1f73d`),
reviewer-agent had independently flagged a second, likely-related
contributor: the 2026-08-14 "confirmed-bad-segment skip" safety valve in
`paper_training_sampler.py` (~line 2053) read a cached
`_starvation_discovery_state["idle_s"]` field that's only updated on a
*successful* admission — so during an actual stall it never gets
recomputed and stays frozen near 0, meaning the valve (meant to force a
bypass after 900s of no admissions, precisely to prevent a repeat of the
2026-08-14 "zero trades for an hour" incident) could never fire.

I implemented the seemingly obvious one-line fix: compute `idle_s` fresh
as `time.time() - last_eligible_entry_ts` instead of reading the stale
cached field — matching the pattern already used by every other `idle_s`
consumer in the same file.

**reviewer-agent REJECTED this fix**, with strong evidence (AST analysis +
a live runtime experiment), finding a *deeper* bug my fix didn't account
for:

## The real bug

`_update_starvation_discovery_idle()` — the function that's supposed to
keep `last_eligible_entry_ts` current on every successful
`PAPER_STARVATION_DISCOVERY` admission — has exactly one call site, at
line ~2204. That call site is **unreachable dead code**: it sits inside an
`if` block that is a sibling, in the same `try` body, of an *unconditional*
`return` at line ~2139 (the "AGGRESSIVE MODE — ALL GATES DISABLED" early
return, dating to commit `b1375bc`, 2026-05-15 — three months *before* the
idle-tracking valve was even written). Every call to
`maybe_open_training_sample()` that reaches that point in the function
returns at line 2139 and never executes line 2204.

Confirmed by the reviewer via a direct runtime experiment: calling the
real function with a successful admission left `last_eligible_entry_ts`
byte-for-byte unchanged (`before == after`).

**Consequence**: `last_eligible_entry_ts` has exactly one live writer in
the whole codebase — the fresh-process-startup baseline
(`if last_eligible_entry_ts == 0.0: last_eligible_entry_ts = now`, lines
~1917-1919). It is set once, at process start, and never touched again.

## Why my fix would have made things worse, not better

With my fix (`idle_s = time.time() - last_eligible_entry_ts`), and given
`last_eligible_entry_ts` is permanently pinned to process-start time,
`idle_s` silently becomes **process uptime**, not actual idleness. The
900s bypass condition (`idle_s < 900.0`) would then go true exactly once,
15 minutes after every process (re)start, and then **stay true forever**
for the remaining lifetime of that process run — regardless of whether the
bot is admitting trades normally or genuinely stalled. Net effect: the
2026-08-14 "stop re-admitting into a segment already conclusively proven
bad" protection would be **permanently disabled after the first 15 minutes
of uptime, on every restart, for every subsequent minute of that process's
life** — a silent, total revert of the 2026-08-14 fix, and worse than
before because cycle 107's admission-scope widening (`fc1f73d`) now routes
more symbols through this exact path.

The regression tests I wrote to prove the fix (mutation-killed via git
stash, genuinely passing/failing as designed) were faithfully
reproducing exactly this broken state
(`last_eligible_entry_ts = now - 950`, i.e. "950 seconds of uptime") and
asserting that state *should* bypass the skip — which is true only because
uptime and idleness are indistinguishable given the dead-code bug, not
because the valve is working correctly. A textbook case of a test correctly
proving code does what it does, while the code does the wrong thing.

## What was and wasn't done

- **Reverted**: both `src/services/paper_training_sampler.py` and
  `tests/test_paper_training_sampler_segment_skip.py` restored to their
  pre-cycle-108 state via `git checkout --`. Nothing from this cycle was
  ever committed, pushed, or deployed — the review gate caught it first,
  exactly as the harness is designed to.
- **Not done**: the actual reachability fix (moving the
  `PAPER_STARVATION_DISCOVERY` bookkeeping at lines ~2200-2214 above the
  unconditional `return` at line ~2139) — reviewer-agent explicitly
  recommended this be its own separate, carefully-forensicked patch, not a
  rider on this one, because:
  1. it has real, wider blast radius: `_is_starvation_discovery_idle()`
     (line ~1075) and the discovery-vs-other-bucket selection logic
     (line ~960) read the *same* `last_eligible_entry_ts`/`idle_s` state
     and are, by the same mechanism, currently also permanently-stale
     after the same ~600-900s-of-uptime mark;
  2. moving code across the unconditional-return boundary at line 2139
     changes what "AGGRESSIVE MODE — ALL GATES DISABLED" actually means
     for this specific bookkeeping, which needs its own dedicated
     evidence-gathering pass before a safe minimal patch can be designed
     with confidence, not a quick follow-up to today's already-eventful
     admission-deadlock fix.

## Current live impact assessment (not urgent, unlike the fc1f73d deadlock)

This dead-code bug is **not** believed to be actively harmful on its own
right now: the bot is trading normally post-`fc1f73d`
(`closed_today` went from 0 to 55 within ~15 minutes of that deploy,
18 opens across 3 symbols confirmed). The confirmed-bad-segment skip that
this dead code was supposed to eventually *bypass* during a stall is,
itself, still working correctly as designed (it's the mechanism that
correctly stopped ETHUSDT re-admission in the first place). The risk this
dead code represents is specifically: **if a future stall happens for a
different reason, this safety valve will not help**, because it never
could. That's a real gap, but not an active, ongoing harm today.

## Recommended next step

A dedicated future cycle should:
1. Map every consumer of `_starvation_discovery_state["idle_s"]` /
   `last_eligible_entry_ts` (at least lines ~964, ~1075, ~1185, ~2053 per
   this investigation) and classify each as "correctly fresh-computed" vs.
   "reads the state directly" (only the latter are affected by the
   dead-code bug).
2. Decide, with fresh forensic evidence (not assumption), whether moving
   the bookkeeping above the AGGRESSIVE-MODE return is safe -- i.e.
   confirm nothing downstream of that early return currently depends on
   `PAPER_STARVATION_DISCOVERY` bookkeeping specifically NOT happening in
   aggressive mode (the return's own comment, "ALL GATES DISABLED",
   suggests it might be deliberate that gate-adjacent bookkeeping is
   skipped too -- needs to be confirmed, not assumed, before moving code
   across that boundary).
3. Only then re-attempt the one-line `idle_s` fresh-computation fix from
   this cycle, this time correctly.

## Process note

This is the review/safety harness working exactly as intended: a
plausible-looking, well-reasoned one-line fix (which even had a
mutation-killed regression test "proving" it) was caught by an adversarial
reviewer before it reached commit, push, or deploy. Not a failure of this
cycle's work -- the correct outcome of following the harness's own rule
("no deployment without all agent approvals") rather than trusting my own
first-pass diagnosis.
