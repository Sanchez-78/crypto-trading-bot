# Firebase quota read/write conflation + debug log spam — root-caused and fixed

**Date:** 2026-08-18
**Trigger:** Operator shared a Firebase Console screenshot showing 100%
of daily free WRITE quota used (20,008/20,000) while reads were only at
29% (14,880/50,000) -- contradicting this session's own quota-status
check moments earlier, which reported reads at 50000/50000 (fully
exhausted) via the app's internal `/api/dashboard/metrics` endpoint.

## Evidence

1. Firebase Console (ground truth): reads 14,880/50,000 (29%), writes
   20,008 (over the 20,000 free tier -- "100% of daily quota for free
   writes" banner), deletes 3,940/20,000 (19%).
2. App's own `firebase_quota` status (same moment): `reads: 50000,
   reads_limit: 50000` (claims 100% read exhaustion) -- directly
   contradicted by #1.
3. Live journalctl: `[FIREBASE_DEGRADED] write skipped: quota_95pct
   (20003/20000 writes, 100.0%)` -- confirms the real trigger was writes.
4. Live journalctl: `[QUOTA_DEBUG] Quota high: 50000/50000 reads
   (100.0%). Not resetting (...)` logged dozens of times PER SECOND
   (e.g. 17 occurrences within a single second at 06:11:23) -- confirms
   `_reset_quota_if_new_day()` is on a hot path (called on every quota
   check) and its "quota still high" debug branch was completely
   unthrottled.
5. Bot's own trading throughput: `lifetime_n` frozen across a 2-minute
   re-check during the incident, and grew by only +37 trades over the
   preceding ~18h (vs. hundreds per 30 minutes earlier in the day) --
   consistent with reads being incorrectly treated as unavailable for
   admission-relevant lookups.

## Root cause

`src/services/firebase_client.py`'s `_mark_quota_exhausted(error_msg)`
unconditionally pinned BOTH `_QUOTA_READS = _QUOTA_MAX_READS` AND
`_QUOTA_WRITES = _QUOTA_MAX_WRITES` (and marked BOTH
`_FIREBASE_READ_DEGRADED`/`_FIREBASE_WRITE_DEGRADED`) on ANY 429 error,
regardless of which quota pool actually triggered it. All 3 call sites
(`_handle_quota_error` -> `_read_doc_dict`/`load_history`/
`load_commands_since`, all read-only; `_async_firebase_write` and
`save_batch`, both write-only) already know their own context but never
passed it through.

Today's incident: writes crossed the 20,000/day free tier (a plausible,
maybe-expected consequence of current trade volume, not investigated
further this pass -- see "Not done" below), producing a write-side 429
from `save_batch`/`_async_firebase_write`. That single write-429 then
incorrectly pinned READS to their max too, even though real reads were
still at 29% -- wasting ~71% of that day's read capacity on a purely
write-side problem, and (per the frozen `lifetime_n` evidence) likely
degrading trading admission logic that depends on Firestore reads for
the remainder of the quota window.

**Not a new bug in the 24h-lockout sense**: `_reset_quota_if_new_day()`
already correctly clears `quota_429` degradation the moment the real
07:00 UTC boundary passes (2026-08-07 fix, still intact and verified
present in the code) -- so this incident would have self-resolved at
the next reset regardless. The value of this fix is for the ~hours
*between* a write-quota breach and the next reset, and for every future
day writes cross their ceiling while reads are still healthy.

## Fix

1. `_mark_quota_exhausted(error_msg, *, is_read=True, is_write=True)` --
   new keyword-only params, defaulting to the old (conservative,
   both-pinned) behavior for any caller that doesn't specify. Only pins
   the quota pool(s) actually passed as `True`.
2. `_handle_quota_error(label, exc, *, is_read=True, is_write=False)` --
   its only real callers are read-only, so this default is now correct
   rather than incidentally-both-pinning.
3. `_async_firebase_write`/`save_batch`'s two direct call sites now pass
   `is_read=False, is_write=True` explicitly.
4. `[QUOTA_DEBUG]` log line in `_reset_quota_if_new_day()`'s "not
   resetting, quota still high" branch throttled to once per 60s via a
   new `_LAST_QUOTA_DEBUG_LOG` module-level timestamp (same pattern as
   `should_skip_noncritical_write()`'s existing throttle in this same
   file).

## Not done this pass (disclosed, not oversights)

- **Why writes reached 20,008/day in the first place** -- not
  investigated. Could be normal/expected at current trade volume (~5500
  trades/day, each likely generating an open-write + a close-write +
  possibly audit/learning writes), or could be a genuine write-burn bug
  analogous to `_workspace/26`'s read-burn (`audit_worker.py`'s
  `.offset()` cleanup query). Worth a dedicated forensic pass if this
  recurs on a subsequent day now that reads will no longer be
  collaterally blocked -- the Firebase Console's per-collection write
  breakdown (not checked this pass) would be the natural next step.
- Real trading was never affected -- PAPER-only throughout, no
  real-order path touched by this change.

## Tests

`tests/test_firebase_quota.py` (+6): write-429 doesn't pin reads,
read-429 doesn't pin writes, default (unspecified) still pins both
(backward compat), `_handle_quota_error`'s read-only default doesn't
touch writes, debug-log throttle (20 calls within a test -> exactly 1
log line). 85 passed / 1 pre-existing failure (confirmed via `git
stash`, identical before/after) / 2 skipped across the full
quota/firebase/degradation-tagged sweep. `py_compile` clean.
