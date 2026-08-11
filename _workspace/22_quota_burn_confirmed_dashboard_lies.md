# CONFIRMED: real Firebase quota burn (~49k/50k unattributed) + dashboard "degraded" field is unreliable

**Date:** 2026-08-11, ~12:45 UTC
**Trigger:** user shared a live Firebase Console screenshot showing 50,137/50,000 reads used today.

## What's confirmed

- Real Firebase Console: 50,137 reads used (over the 50k free cap), cumulative-reads chart
  climbs steeply then flatlines hard at the ceiling for many hours.
- Server-side confirmation: `local_learning_storage/quota_attribution_snapshot.json` shows
  `reads: 50000/50000`, `generated_at_utc: 2026-08-11T11:04:30Z`, `reason: "quota_429:429 Quota exceeded."`
- `journalctl` right now (12:42 UTC): `[QUOTA_HARD_GATE] Blocking read: 50,000/50,000` spamming
  continuously, `[SAFE_MODE] dashboard state=SAFE_MODE_FIREBASE_DEGRADED entries=blocked reason=quota_429`.

## Dashboard API is lying (or at least stale/wrong)

`curl http://localhost:5001/api/dashboard/metrics` returns `"degraded": false` **at the exact same
moment** the bot's own process logs show `SAFE_MODE_FIREBASE_DEGRADED` firing continuously. This
field cannot be trusted. Every "stable, no issues" report this session for the last ~5 hours
(cycles logged in `monitoring_progress.json` between the 07:49 UTC deploy and now) relied on this
field and was therefore **not verifying what it claimed to verify**. The shadow evaluator's own
stability (zero crashes, zero candidates) is independently confirmed via direct log inspection and
is NOT affected by this -- it only talks to Binance REST, never Firebase.

**Process correction going forward:** check `journalctl -u cryptomaster.service | grep SAFE_MODE`
directly, never trust the dashboard's `degraded` field alone.

## The burn itself: mostly unattributed, ~4.2 reads/sec sustained for ~3h15m

At the 11:04:30 UTC snapshot: `reads: 50000`, attribution: `{"load_history": 600,
"load_auditor_state": 36}` = 636 attributed reads. **~49,364 reads (98.7%) are unattributed** --
not a single burst, but sustained draw from server restart (07:49:26 UTC) to quota exhaustion
(~11:04:30 UTC) = ~3h15m, averaging ~253 reads/minute / ~4.2 reads/second continuously.

This directly contradicts yesterday's "currently healthy, ~264 reads/hour" assessment
(`_workspace/17_...md` cycle notes) -- that assessment was made from a ~2h window that happened to
be quiet, not a representative sample. The real burn rate is roughly **1000x higher** than that
earlier estimate. `_workspace/13_quota_exhaustion_audit.md` rec #5 (never root-caused, repeatedly
deferred across sessions) is now confirmed real and large, not speculative.

## Partial lead: at least one unattributed direct-read call site found

`src/services/canonical_state.py:69`: `db.collection("metrics_full").document("global").get()` --
a direct Firestore read that bypasses `_can_read()`/`_record_read()` entirely (no quota gate, no
attribution label). One single-document read per call, so by itself this only matters if the
containing function is called very frequently (not yet confirmed how often). Not yet established
whether this alone accounts for a meaningful fraction of 49,364 -- likely one contributor among
several, not proven as the sole cause.

`src/services/auto_filter.py:41` (`AutoFilter.load_stats()`) has a similar unguarded direct read,
but is instance-cached (`if key in self.cache: return`), so it should NOT cause sustained high
volume unless the cache is defeated somehow (e.g., fresh instances created repeatedly). Not yet
investigated further.

## Not yet done (next priority)

1. Find the actual dominant unattributed read source(s) -- likely requires either (a) instrumenting
   more Firestore call sites with `_record_read()`, or (b) reproducing locally with a read-call
   trace/counter patched into the Firestore client to catch every `.get()`/`.stream()` regardless
   of whether the code path calls the tracked wrapper.
2. Fix the dashboard's stale/wrong `degraded` field (separate bug, same class as the previously
   documented "23.5h stale dashboard" incident -- the dashboard is a separate systemd unit/process
   from the bot and can drift from live state).
3. Root-cause + fix the actual burn once located -- likely the single highest-leverage remaining
   fix in this whole program, since it silently degrades the bot (entries blocked) for large parts
   of most days, which the dashboard has been hiding from every prior monitoring cycle.

## Explicitly not caused by today's new pipeline

`p0_8_plus_shadow_evaluator.py`, `candle_cache_v1.py`, `live_quote_cache_v1.py` make zero Firestore
calls (candle fetch is Binance REST; live quotes come from the existing event_bus). Confirmed via
code review (only `p0_risk_guard_v1.py` touches `firebase_client.get_firebase_health()`, a
read-only in-memory status check, not a Firestore call). The shadow pipeline's "0 candidates for
5 hours, zero errors" observation stands independently of this finding.
