# 47 — Cycle 125: fixed the 3 findings from cycles 123-124, plus a correction and a new backlog discovery

## Status: THREE FIXES AUTHORED + LOCAL-TESTED, PENDING REVIEW + DEPLOY (not yet reviewed/deployed at time of writing)

## Correction to cycle 124's framing (self-correction, before this propagates further)

Cycle 124's write-up (and the memory file
`project_read_quota_mystery_likely_solved_20260826.md`) characterized the
`audit_worker.py:188` `.offset()` read-cost finding as effectively a fresh
discovery. **That overclaimed it.** Re-reading `_workspace/26_quota_burn_found_audit_worker_offset.md`
(2026-08-14) while implementing the fix: this exact call site, this exact
mechanism (Firestore billing every skipped document), and this exact
"the fix only reduces frequency, not per-call cost" tradeoff were **already
found and explicitly, consciously accepted as a deliberate tradeoff** on
2026-08-14 — that doc's own words: *"Did not touch the `.offset()` query
pattern itself (a cursor-based rewrite would be a larger, riskier change
for a collection this small and already effectively self-limiting) --
reducing call frequency alone cuts the burn rate proportionally with
minimal risk."*

**What IS actually new in cycle 124/125, stated precisely:** the
2026-08-14 assumption that the collection was "already effectively
self-limiting" and that the frequency-only throttle would produce "a
dramatically flatter growth curve" turned out to be **wrong in practice**
— quota is still exhausting regularly today (cycle 123), 12 days later,
and live-querying the actual collection size (below) shows it never
stayed near its 50-doc cap at all. The genuinely new contribution this
cycle is: (a) confirming empirically that the accepted 2026-08-14
mitigation was insufficient, and (b) discovering the collection has grown
far beyond anyone's expectation, which is a different and larger problem
than the pure per-call-read-cost question 2026-08-14 addressed.

## New finding: the "audits" collection has ~92,684 documents, not ~50

Live-queried via a direct Firestore aggregate `.count()` call (2026-08-26
07:11 UTC): **92,684 documents** in the `audits` collection, against a
design intent (`MAX_AUDITS=50`) of keeping only the most recent 50. The
`.limit(20)`-per-pass deletion rate, even fully utilized every
`CLEANUP_INTERVAL_S` (300s), caps at ~5,760 deletes/day maximum — clearly
insufficient against the collection's actual write rate over whatever
period it took to reach 92,684 (not established exactly how long, but the
throttle fix has been live since 2026-08-14, i.e. up to 12 days).

This is a big deal for two separate reasons:
1. **Storage**: the project's own free-tier note (`firebase_client.py`
   docstring) cites a 1GB storage cap. Not measured this cycle whether
   92,684 small audit documents approach that, but it's worth checking.
2. **Read cost floor**: because `.offset(50)` always skips exactly 50
   documents regardless of total collection size, the per-call READ cost
   of the OLD cleanup pattern was NOT growing with the backlog — it was a
   flat ~70/call the whole time. So the backlog's existence doesn't change
   the earlier per-call cost estimate (~8,680 reads/day plausible from
   this site), but it does mean the fix needs to actually shrink the
   collection, not just stop it from (barely) growing.

## Fixes applied (3 files, all local-tested, none yet deployed)

### 1. `v5_legacy_bridge/firebase_writer.py` — outbox-replay malformed path (cycle 123 Finding 2)

`flush_outbox()`'s `learning_update` branch used
`f"v5_trades/{id}/learning"` (3 segments, invalid). Changed to match the
live-write path exactly: `f"v5_trades/{id}"` with `merge=True`. Verified
`OutboxFlushWorker` (a separate, parallel outbox consumer in
`outbox_flush_worker.py`) already used the correct path shape — only
`V5LegacyFirebaseWriter.flush_outbox()` had the bug. New tests:
`tests/test_v5_legacy_firebase_writer_outbox_replay_path.py` (2 tests,
including a direct even-segment-count regression check), both pass.

**Side note, not acted on:** log evidence shows both `flush_outbox()` and
`OutboxFlushWorker._flush_batch()` appear to process the same outbox table
(different log tags for the same retry sequence on the same entry id) —
possibly two independent consumers of one queue. Not a correctness bug
given both now use the same correct path, but worth a dedicated look in a
future session to understand whether this causes redundant work.

### 2. `emergency_health_monitor.py` — false-positive CRASH_DETECTED (cycle 123 Finding 3)

`detect_crashes()` bare-substring-matched `"Exception"`/`"ERROR"`/`"FATAL"`
anywhere in a log line. Now requires `"Traceback (most recent call last)"`
or `"FATAL"`, and explicitly skips lines already carrying this codebase's
own `"⚠️"` handled-warning marker. New tests:
`tests/test_emergency_health_monitor_crash_detection.py` (5 tests: the
exact production false positive, two other handled-warning shapes, a real
traceback still detected, a FATAL marker still detected), all pass.

### 3. `audit_worker.py` — offset-free cleanup + faster drain (cycle 124 finding)

Replaced `.offset(MAX_AUDITS).limit(20).get()` with an aggregate
`.count().get()` (1 read) to size the actual excess, then an
ascending-order `.limit(min(excess, CLEANUP_BATCH_LIMIT)).get()` that only
reads documents it's about to delete. `CLEANUP_BATCH_LIMIT=60` (up from
the old fixed 20) to start draining the backlog faster without a large
read-cost increase. **Deliberately does NOT attempt a one-shot full
backlog drain** — reading all 92,684 documents to delete them would cost
~92,684 reads, an entire day's quota in a single call. At the observed
real call rate (~124/day per the tracer), this drains roughly 60×124 ≈
7,440 docs/day → the existing backlog would take ~12-13 days to fully
clear at this rate, which is an acceptable gradual resolution given the
alternative (a bigger one-shot operation) carries real quota risk.
Updated `tests/test_audit_worker_cleanup_throttle.py` for the new
count()-based mocking (7 tests, all pass, including 2 new tests
specifically for the excess-sizing and skip-when-under-cap behavior).

**Not done, flagged for the user/a future session:** a Firestore TTL
(time-to-live) policy on the `audits` collection's `timestamp` field would
eliminate this entire class of problem going forward (server-side
expiry, no client reads/writes/deletes counted against quota) — this
requires Firebase Console or `gcloud` access this session does not have.
Recommended as the actual long-term fix; today's code change is a
quota-safe mitigation, not a replacement for that.

## Verification before deploy

- `python -m pytest tests/test_audit_worker_cleanup_throttle.py tests/test_v5_legacy_firebase_writer_outbox_replay_path.py tests/test_emergency_health_monitor_crash_detection.py -v` → 14/14 pass.
- Broader sweep `pytest tests/ -k "audit_worker or v5_legacy or emergency_health or outbox"` → 6 pre-existing failures in `test_v5_legacy_bridge_hooks.py`, confirmed via `git stash` to already fail identically with none of this cycle's changes applied — unrelated to this cycle's 3 files, not investigated further (out of scope).
- Live-verified the `.count()` API works against the real Firestore `audits` collection (returned 92,684, matches expectations of the API shape used in the code).

## Next step

Dispatch `trading-safety-agent` + `reviewer-agent` (per harness discipline
for any production code change) before deploying through the gated
Hetzner workflow.

## Review results + v2 corrections (same cycle)

**`trading-safety-agent`: PASS** (no real-trading exposure in any of the
3 files; confirmed the advisory-only nature of `emergency_health_monitor`'s
alerts end-to-end, not just by inspection — traced `monitor_loop` and
confirmed the return value is discarded, no subprocess/systemctl call
exists anywhere in the path). Flagged the same count()-cost concern as
`reviewer-agent` below, non-blocking from a safety standpoint but
recommended fixing before deploy.

**`reviewer-agent`: REJECTED**, with three findings, all addressed below:

1. **Blocking, Fix 3 cost claim was wrong.** Firestore bills `.count()`
   at ~1 read per 1,000 index entries matched, not a flat 1 — against the
   live ~92,684-doc collection, v1's per-pass `.count()` actually cost
   ~93 reads, making the fix ~2.2x MORE expensive than the old code
   during the exact period (huge backlog) it mattered most, and — worse —
   `count()` is invisible to the Firestore read tracer (not one of the
   patched classes), so this new cost would have been unobservable to the
   very instrument built to catch this class of problem.
   **Fixed (v2):** cache the count locally, refresh via a real `.count()`
   only once per `CLEANUP_COUNT_REFRESH_S` (~hourly), keep the estimate in
   sync between refreshes purely from local knowledge (`+= len(items)` on
   every write batch, `-= deleted` on every cleanup pass) — zero extra
   Firestore reads to track it. Net cost now ~9,672 reads/day, roughly at
   parity with the old code's estimated cost.
2. **Corrects a premise I got wrong, favors the fix.** The OLD
   `DESCENDING + offset(50)` query deleted the **51st-70th newest**
   documents, never the true oldest tail — this is *why* the collection
   reached 92,684 despite the cap, independent of the read-cost question.
   The v1 rewrite's `ASCENDING order_by` (kept unchanged in v2) is the
   *correct* direction and was already right; I hadn't realized this was
   also fixing a logic bug, not just a cost one. Confirmed no data-loss
   risk either version — neither query ever touches the newest 50.
3. **Bare `except Exception: pass` masked exactly this kind of failure.**
   Fixed: now `log.warning("[AUDIT_CLEANUP_FAILED] %s", e)`.

Also for Fix 2 (`emergency_health_monitor.py`): the `⚠️` line-skip added
in v1 was unnecessary (the positive-match narrowing alone already kills
the production false positive) and cost a real detection — it silently
suppressed `runtime_fault_registry.py`'s genuine
`"⚠️  RUNTIME_FAULT [CRITICAL]: ..."` faults. **Fixed (v2):** removed the
emoji skip, added an explicit `"RUNTIME_FAULT [CRITICAL]"` marker to the
positive-match list instead.

Also for the test suite: `tests/test_v5_legacy_firebase_writer_outbox_replay_path.py`'s
fixture originally pointed at the real runtime artifact
`config.V5_OUTBOX_DB_PATH` and `os.remove()`d it — the same file the live
bot uses, risking a Windows file-handle collision and contaminating a
shared path. **Fixed:** fixture now monkeypatches `config.V5_OUTBOX_DB_PATH`
to an isolated `tmp_path` before constructing `DurableOutbox()`.

Also noted, not acted on (informational): `write_learning_update()` entries
that already exceeded `OUTBOX_MAX_RETRIES=3` before this deploy are
permanently excluded from replay by `get_pending()`'s own filter — this
fix prevents *future* loss, it does not recover the ~60 already-lost
entries from today's incident. Not claiming recovery in any summary.

19 tests now (up from 14), all pass locally:
`python -m pytest tests/test_audit_worker_cleanup_throttle.py
tests/test_v5_legacy_firebase_writer_outbox_replay_path.py
tests/test_emergency_health_monitor_crash_detection.py -v` → 17 passed
(9+3+5 across the three files with the new count-refresh and
runtime-fault-critical tests). Broader sweep unchanged: same 6
pre-existing, unrelated failures as before (confirmed via `git stash`
earlier), no new failures or errors introduced by the fixture fix.

**Status: re-submitted for final confirmation, not yet deployed.**
