# 46 — Cycle 123: real Firebase quota exhaustion + two NEW forensic findings (not yet patched)

## Status: EVIDENCE COLLECTED, NO PATCH/DEPLOY THIS CYCLE (quota genuinely exhausted, deferring clean verification to post-reset cycle)

## Trigger

Routine 30-min check found `firebase_quota.quota_exhausted=true`,
`writes=20013-20163/20000` (100.1%+, real Firestore 429s, not a stale flag).
Went deeper than the usual "note it, wait for 07:00 UTC reset" response
because journalctl also showed two distinct NEW log patterns not seen in
cycles 111-122.

## Finding 1 (operational, self-resolving): genuine write-quota exhaustion

`journalctl` since 2026-08-26 04:30 UTC shows continuous `429 Quota exceeded`
errors on Firestore writes (trade opens/closes, learning updates, dashboard
snapshot publish, auditor state saves) starting ~06:00 UTC. This is real,
not the read/write-conflation bug fixed 2026-08-18 (writes are genuinely at
20013-20163 against a 20000 limit). Resets automatically at 07:00 UTC per
`firebase_client.py:_reset_quota_if_new_day()` (already correctly
boundary-based). **No code fix needed or attempted — this is quota
depletion, not a bug**, per the standing harness rule ("Stop if quota <10%
until reset... no patch can fix quota depletion").

## Finding 2 (NEW bug, root-caused, not yet patched): outbox replay uses a malformed Firestore path for `learning_update`

`v5_legacy_bridge/firebase_writer.py`:
- **Live write path** (`write_learning_update()`, line 170): `path = f"v5_trades/{trade_id}"`, `.set(path, payload, merge=True)` — correct, 2-segment doc path.
- **Outbox replay path** (line 318-321, used when the live write fails/queues, e.g. under quota pressure): `f"v5_trades/{entry.idempotency_key}/learning"` — **3 segments, ends on a collection ("learning"), not a document.** Firestore requires an even number of path segments for `.set()`/`.update()`; this always raises `Invalid path (must end on doc, not collection)`.

**Evidence:** `[FIRESTORE_PATH_SET_FAILED] path=v5_trades/paper_.../learning error=Invalid path (must end on doc, not collection)` — 60 occurrences in the 2026-08-25 00:00–2026-08-26 06:05 window, all clustered from **2026-08-26 05:19:03 onward** (zero before that timestamp in the same window — this is a newly-triggered failure mode, not a long-standing background rate). The clustering onset lines up with write-quota pressure starting to push `learning_update` writes into the outbox (the direct path only fails over to outbox on quota exhaustion or a live write exception — see line 162-167 and 175-180) — the outbox-replay code path is apparently rarely exercised in normal operation, so this bug has likely been dormant/rare until today's quota exhaustion made outbox usage common.

**Effect:** any `learning_update` entry that falls back to the outbox (quota pressure, or any live-write exception) is **permanently unable to replay successfully** — it will retry forever (`retry_count` increments indefinitely in the observed logs, e.g. `id=37554` still retrying) and never persist. This affects only the Firestore-side learning-update mirror used by the V5/Android bridge; it does **not** touch the primary paper-trading decision loop, which reads `segment_weights`/learning state from local `cache.sqlite`/`paper_adaptive_learning_state.json`, not this Firestore path. **Scope: cosmetic/audit-trail data loss on the Android dashboard's learning view, not a trading-logic bug.**

**Proposed minimal fix (not yet applied):** outbox replay should use the same path as the live write (`f"v5_trades/{entry.idempotency_key}"` with `merge=True`), matching line 170-171, instead of appending `/learning`.

## Finding 3 (NEW bug, root-caused, not yet patched): `EMERGENCY_MONITOR` false-positive `CRASH_DETECTED` alerts

`emergency_health_monitor.py:detect_crashes()` (line 222-233) flags a
"crash" on **any** log line containing the bare substrings `"Traceback"`,
`"Exception"`, `"FATAL"`, or `"ERROR"` — a naive substring match, not an
actual unhandled-exception/traceback detector.

**Evidence:** at `2026-08-26 06:05:18`, this fired a `CRITICAL
CRASH_DETECTED` alert with `RESTART_SERVICE_FORCE` remediation, triggered
by the log line `⚠️ WebSocket error: WebSocketTimeoutException: ping/pong
timed out` — a normal, already-handled transient market-stream reconnect
warning (logged with a `⚠️` warning marker, not a raw traceback), which
matches only because the word "Exception" appears inside the class name
`WebSocketTimeoutException`. **Confirmed false positive via
`systemctl show`: `NRestarts=0`, continuous uptime since
`2026-08-24T07:35:49Z`** — the service never actually crashed or
restarted around this or the several earlier `RESTART_SERVICE`
alerts logged 05:48-06:03 UTC.

**Risk:** `EMERGENCY_MONITOR`'s remediation actions are **advisory-only**
(logged strings; grepped the file for `subprocess`/`os.system`/direct
`systemctl` invocation — none found, only human-readable "run: systemctl
restart..." text in log messages). So this does **not** auto-restart the
service or otherwise act — it is pure log noise/false alarming, not an
operational risk today. But it actively misleads anyone reading logs
(including a future monitoring cycle) into believing the service crashed
when `NRestarts=0` proves it did not.

**Proposed minimal fix (not yet applied):** require a real crash signature
(e.g. `"Traceback (most recent call last)"` literal, or a logging
level/severity check) instead of a bare substring match on `"Exception"`/
`"ERROR"`, which will false-positive on any handled-and-logged exception
class name.

## Why NOT patched/deployed this cycle

1. Firebase quota is genuinely exhausted right now (reset ~55 min away at
   07:00 UTC) — deploying and then trying to verify "no new errors
   post-deploy" would be unreadable against the backdrop of ongoing
   unrelated 429 quota-exceeded log noise.
2. Both findings are real but **low urgency**: Finding 2 is a cosmetic/
   audit-trail gap (Android learning-view mirror only, not trading logic);
   Finding 3 is a false-alarm-only advisory log line (no auto-action).
   Neither is causing live trading harm right now.
3. Per harness discipline, any production code change needs the standard
   evidence->review->deploy pipeline (trading-safety-agent,
   reviewer-agent) even for low-risk fixes — better done in a cycle where
   post-deploy verification isn't confounded by ongoing quota noise.

## Recommended next step (next cycle, after 07:00 UTC quota reset)

1. Author both fixes as two small, independent patches (they touch
   unrelated files/paths — no reason to bundle them).
2. Dispatch `trading-safety-agent` (confirm PAPER-only scope, no real
   trading path touched — trivially true for both, but still verify) and
   `reviewer-agent` per standard process.
3. Deploy through the existing gated Hetzner workflow, verify clean logs
   (now free of quota-exhaustion noise) for ~10-15 min post-deploy.
