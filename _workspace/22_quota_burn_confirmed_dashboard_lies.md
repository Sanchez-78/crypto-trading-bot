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

---

## Update: ruled out the obvious hypothesis, root cause still not found

Checked `firebase_trade_hydration.py:hydrate_trades_from_firebase()` (unbounded
`db.collection('trades').stream()`, no `.limit()`) as the prime suspect for a
big startup burst. **It's dead code** -- grepped the entire repo, it is never
called from anywhere (`bot2/main.py`, `start.py`, or any `src/services/*.py`).
Not the cause.

Also checked `canonical_state.py:_load_from_firestore()` (single-document
read, gated behind `initialize_canonical_state()`, startup-only) -- too small
(1 read) to matter, not the cause either.

**Given the drain is sustained (~4.2 reads/sec for ~3h15m, not a single
burst), the real cause is more likely something periodic** (a background
timer/loop re-reading a collection every N seconds, or a per-tick/per-symbol
read multiplied across a hot loop) rather than a single big startup call.
Manual grep-based code review across 176+ files in `src/services/` is not
converging efficiently.

**Recommended approach for the next session that picks this up:** rather
than continuing manual review, monkey-patch/wrap the Firestore client's
`.get()`/`.stream()`/`.where()` methods at the `firebase_client.db` object
level with a call-site logger (capture `inspect.stack()` on every real
Firestore read call, log the caller file:line, aggregate counts per
call-site over a time window) and observe on the next restart. This
would find the actual source empirically in one restart cycle instead of
continued manual grep. Not implemented this session -- would itself need a
deploy (Gate 5) and a dedicated observation window, and this session has
already spent significant time on this specific side-investigation without
reaching a confirmed root cause; stopping here rather than guess-fixing
without evidence (this session's established discipline throughout).

## UPDATE 2026-08-13: Tracer generation 3 — root cause of zero-hits found

Generation 2 (BaseDocumentReference added) deployed as commit `bc80d27`→`c7c30028`
and confirmed live via `journalctl`: right at process restart, `calibration`,
`weights`, `metrics`, `canonical state`, `load_stats`, `load_model_state` all
hit `429 Quota exceeded` within seconds — real Firestore reads were definitely
being attempted — yet **zero** `[FIRESTORE_READ_TRACE_SUMMARY]` lines appeared,
even ~60s+ after install (past the summary interval).

Root cause isolated by inspecting the installed SDK directly on the server:

```python
DocumentReference.get is own:    True   # NOT inherited from BaseDocumentReference
CollectionReference.get is own:  True   # NOT inherited from BaseCollectionReference
CollectionReference.stream is own: True
Query.get is own:                True   # NOT inherited from BaseQuery
Query.stream is own:             True
DocumentReference.set/update/create/delete is own: True (all four)
```

`Base*` classes are abstract bases; the **concrete** sync classes actually
returned by `db.collection(...)`/`.document(...)` (the ones `firebase_admin`'s
sync `Client` instantiates) each define their own `get`/`stream`/`set`/
`update`/`create`/`delete`/`collections` in their own `__dict__`. Per Python
MRO, an instance's method lookup finds the concrete class's own method first
and never falls back to a patched `Base*` method — patching `Base*` was
**inert from generation 1**, on every single deploy of this tracer so far.

**Fix (commit pending, this session):** `_install_firestore_read_tracer()` now
patches `google.cloud.firestore_v1.{collection,document,query}`'s
`CollectionReference`/`DocumentReference`/`Query` directly (in addition to the
harmless Base fallback), gated by `method_name not in cls.__dict__` so each
method is wrapped exactly once on the class that actually owns it. 21 tests
(new file content), including a direct regression test
(`test_patching_base_class_alone_would_not_have_covered_the_concrete_class`)
that asserts the concrete classes' methods are NOT the same object as
whatever `Base*` defines for that name.

**Next step once deployed:** wait for the next quota-exhaustion burst (still
recurring every ~1-19h depending on window) and read the actual
`[FIRESTORE_READ_TRACE_SUMMARY] top call sites: [...]` line for the first
time this diagnostic effort has produced real data.
