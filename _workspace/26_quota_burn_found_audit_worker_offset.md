# Found it: the Firestore quota burn was audit_worker.py's offset() cleanup query

**Date:** 2026-08-14
**Trigger:** User shared a Firebase Console screenshot (36,648/50,000 reads,
73%, climbing) mid-session; checked the (finally-working, 3rd-generation)
read tracer's `[FIRESTORE_READ_TRACE_SUMMARY]` log for the first time this
multi-day investigation produced real attribution data.

## The evidence

```
[FIRESTORE_READ_TRACE_SUMMARY] top call sites:
  WRITE:v5_legacy_bridge/firebase_client_wrapper.py:62   980  (shared write chokepoint, see below)
  READ:audit_worker.py:166                               436  <-- the culprit
  READ:google/cloud/firestore_v1/query.py:204            436  (same call, SDK-internal frame)
  WRITE:google/cloud/firestore_v1/collection.py:134      114
  ...
```
(counts as of one snapshot; both READ lines climbed together at the same
rate over subsequent snapshots, confirming they're the same call chain --
`audit_worker.py:166` is the actual `.get()` invocation, `query.py:204` is
the SDK frame the tracer also caught because the wrapper is installed on
the concrete `Query` class.)

## Root cause

`src/services/audit_worker.py`, `_sync_batch_write()`:

```python
snap = db.collection("audits").order_by(
    "timestamp", direction="DESCENDING"
).offset(MAX_AUDITS).limit(20).get()  # MAX_AUDITS = 50
```

This is a "keep only the last 50 audits" cleanup query, and it ran on
**every batch flush** -- as often as every `BATCH_INTERVAL` (3 seconds)
whenever the buffer had anything queued. Firestore's `.offset()` is a
well-known anti-pattern: it is billed for **every document it skips
server-side**, not just the documents actually returned. An
`.offset(50).limit(20)` call therefore reads on the order of 50-70+
documents per invocation, regardless of whether any cleanup was actually
needed (the collection is usually already near its 50-doc cap, since this
same worker enforces it).

At even a modest sustained rate of one flush every few seconds, this alone
plausibly accounts for the full daily 50k-read burn within a matter of
hours -- consistent with every quota-exhaustion timing this session
observed (ranging roughly 1-20 hours depending on how active the audit/
rejection event stream was).

Two earlier tracer generations (documented in
`_workspace/22_quota_burn_confirmed_dashboard_lies.md` and
`_workspace/23_lifetime_metric_was_rolling100.md`'s sibling `_workspace/
20_.../21_...` reads) caught zero hits because they patched the wrong
classes (`Base*` abstract bases instead of the concrete SDK classes that
actually own `get`/`stream`/etc. -- fixed 2026-08-13/14). Once the tracer
actually worked, this call site was visible within the first live snapshot
checked.

## Fix

Throttle the cleanup query to run at most once per `CLEANUP_INTERVAL_S`
(300s / 5 min), tracked via a per-worker-instance `_last_cleanup_ts`,
independent of how often `_sync_batch_write()` itself is called. The
regular audit writes (`batch.set()`/`batch.commit()`) are untouched and
still happen on every flush -- only the expensive re-trim query is
throttled. A failing cleanup still advances the throttle timestamp (can't
spin-retry every flush on a persistent error).

Did not touch the `.offset()` query pattern itself (a cursor-based
rewrite would be a larger, riskier change for a collection this small and
already effectively self-limiting) -- reducing call *frequency* alone cuts
the burn rate proportionally with minimal risk, which is enough given the
collection only needs to be re-trimmed occasionally, not every 3 seconds.

Also checked the top WRITE call site (`firebase_client_wrapper.py:62`,
`FirestorePathClient.set()`) -- this is a **shared, generic chokepoint**
every V5-legacy-bridge write funnels through (trade opens/closes, quota
state, outbox flushes), not a single hot/buggy pattern; its high count is
expected given it aggregates all legitimate write traffic, not a bug.
Writes were at 13% of quota (2,778/20,000) vs reads at 73% (36,648/50,000)
at the time this was found -- reads were the actual emergency, and are now
addressed.

## Tests

`tests/test_audit_worker_cleanup_throttle.py` (new): cleanup runs on first
flush; does not re-run within the throttle window across multiple flushes;
re-runs after the window elapses; the actual write batch still commits on
every flush regardless of the cleanup throttle; a cleanup exception is
swallowed and still advances the throttle timestamp. 5/5 pass.

## Expected effect

This should be the actual fix for the multi-day quota-exhaustion
investigation (`_workspace/13`, `22`, `23` and the many monitoring-loop
cycles that found `quota_exhausted=True` recurring). Watch the Firebase
Console reads-over-time graph after this deploys -- expect a dramatically
flatter growth curve, not the steep climb-to-exhaustion pattern seen in
every screenshot shared this session.
