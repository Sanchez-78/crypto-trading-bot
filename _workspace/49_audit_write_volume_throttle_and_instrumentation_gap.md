# 49 — Cycle 159: audit write-volume root cause, throttle fix, and a new deferred finding

## Status: FIXED (commit f89203a + doc correction), APPROVED WITH CONDITIONS by reviewer-agent, conditions addressed same cycle. One follow-up item deliberately deferred.

## Trigger

User asked directly: "proc se tak moc zapisuje? potrebujeme 20000/24h" (why
does it write so much? we need [to stay under] 20000/24h).

## Investigation

Measured the actual write-quota consumers live:
- Real trade lifecycle (paper_open/close/learning_update): ~2,400/day
  (808 closed trades/24h from cache.sqlite x ~3 writes/trade).
- Live-sampled the "audits" Redis channel (`redis-cli psubscribe`, 60s
  window): ~2.18 messages/sec continuously, almost entirely
  `reason=REJECTED_CORRELATION` (execution_engine.py's correlation-shield
  rejection — fires whenever a candidate correlates with an already-open
  position, which is common, not rare).
- `audit_worker.py`'s per-reason throttle was only 1.0s — a theoretical
  ceiling of up to 86,400 writes/day from this single reason alone, more
  than the entire 20,000/day budget.
- Cross-checked against the real Firestore `audits` collection size via
  direct `.count()`: 92,684 (2026-08-26) -> 105,933 (2026-08-28, ~46h
  later).

## Fix

Raised `AUDIT_THROTTLE_PER_REASON_S` from 1.0s to 20.0s (new named
constant, was a bare literal). 5 new tests
(`tests/test_audit_worker_throttle_per_reason.py`), all pass.

## Review (reviewer-agent: APPROVED WITH CONDITIONS; trading-safety-agent: PASS)

`trading-safety-agent` confirmed no real-trading exposure — the worker is
a passive, fire-and-forget downstream mirror; nothing reads the `audits`
collection back into any decision path; all 5 real-trading safety guards
independently re-verified in place.

`reviewer-agent` found no grounds to reject, but raised three conditions,
all documentation/process (no code-behavior change needed):

1. **Magnitude overclaim, corrected same cycle.** The "86,400 writes/day"
   figure is an honest theoretical ceiling but is 4-12x higher than what
   the collection's own measured growth (92,684 -> 105,933 over ~46h,
   implying ~6,900-24,200/day net inserts) actually supports — the
   20,000/day write quota itself was very likely already the real cap on
   REJECTED_CORRELATION's write rate, not the old 1.0s throttle. Fixed:
   corrected the comment block in `audit_worker.py` to state both the
   ceiling and the measured range, explicitly flagging the ceiling as
   "don't treat this as the observed rate."
2. **"~4,320/day" is per-reason, not channel-wide, corrected same cycle.**
   `reviewer-agent` enumerated all publishers to the `audits` channel and
   found exactly two: `REJECTED_CORRELATION` (execution_engine.py) and
   `REJECTED_L2_WALL` (signal_engine.py) — each gets its own independent
   20s budget, so the channel-wide ceiling is ~8,640/day, not ~4,320/day.
   Fixed: corrected the comment to state both figures.
3. **Test coverage caveat, accepted as-is (not a code change).**
   `reviewer-agent`'s own mutation check found only 1 of the 5 new tests
   (the direct constant-value pin) actually fails when the fix is
   reverted to 1.0 — the other 4 tests express timing relative to the
   constant and pass identically at either value (they test the
   pre-existing per-reason-throttle *mechanism*, which this patch didn't
   change, not the specific *value* changed). This is an inherent
   limitation of testing "a constant changed" and is disclosed here
   rather than treated as a real coverage gap requiring more tests.

## New finding (deferred, not fixed this cycle): audit_worker.py bypasses the app's own quota accounting entirely

`reviewer-agent`'s most valuable catch: `_sync_batch_write()`'s
`batch.commit()`, and the cleanup pass's `.count()`/delete `.get()`
calls, never call `_record_write()`/`_record_read()` anywhere in this
file — contrast `firebase_client.py`'s own save functions, which do. This
means:

1. The app's own reported write-quota percentage has been systematically
   undercounting for as long as this worker has run (a related, smaller
   instance of the same class of undercounting problem as the read-side
   mystery investigated in `_workspace/22_...md`/cycle 124).
2. **Nobody can confirm today's throttle fix actually worked by watching
   the app's own quota meter** — only by re-querying the real Firestore
   Console/`.count()` directly, the same way this investigation itself
   was done. If a future "why is quota still exhausting" question comes
   up, the app's own dashboard cannot answer it for this specific write
   source.

**Deliberately not fixed this cycle** — instrumenting these writes
correctly (adding `_record_write()`/`_record_read()` calls at the right
points, deciding whether `quota_guard` from the V5 bridge is the right
accounting target for a differently-structured worker) is a distinct,
non-trivial patch in its own right, not a natural extension of a
one-line throttle-constant fix. Flagged here as the clear next priority
if write-quota questions recur.

## Correction (deploy-verify-agent, post-deploy): the "REJECTED_CORRELATION is dominant" attribution may not hold generally

My original 60s sample (pre-deploy) showed the "audits" channel almost
entirely `REJECTED_CORRELATION`. `deploy-verify-agent`'s independent 30s
sample taken shortly after deploy showed the **opposite** composition:
63 `REJECTED_L2_WALL`, 0 `REJECTED_CORRELATION`, at a similar overall
rate (~3.4 msg/s). **This does not affect the fix's correctness or its
budget math** — both reasons are throttled identically and independently
(confirmed exactly 2 publishers exist:
`execution_engine.py:244`/`REJECTED_CORRELATION`,
`signal_engine.py:213`/`REJECTED_L2_WALL`), so the ~8,640/day
channel-wide ceiling holds regardless of which reason dominates at any
given moment. But **don't treat "REJECTED_CORRELATION is the dominant
reason" as a settled fact** in a future investigation — which reason
dominates plausibly depends on which positions happen to be open at
sample time (correlation rejections need an open, correlated position to
reject against; L2-wall rejections don't), i.e. it's window-dependent,
not a fixed property of the system.

## Verification plan (not yet done — needs time to pass)

Watch the `audits` collection's growth rate (direct `.count()` query,
same method used throughout this investigation) over the next several
days to confirm net growth actually slows. Given the backlog itself is
~105,933 docs against a 50-doc cap, full recovery will still take time
(reviewer-agent's estimate: ~12 days at the current drain rate, itself
slightly slowed by this same fix since fewer flushes now happen per
throttle window) — the throttle fix caps *future* write rate, it does
not accelerate backlog drain (that's the separate, already-tracked
`CLEANUP_BATCH_LIMIT`/`CLEANUP_COUNT_REFRESH_S` mechanism from cycle
125).
