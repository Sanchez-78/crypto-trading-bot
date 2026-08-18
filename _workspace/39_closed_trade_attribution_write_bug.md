# Closed-trade attribution silently lost on write to cache.sqlite — found and fixed

**Date:** 2026-08-18
**Trigger:** Post-deploy monitoring after the admission-path-unification
fix (`_workspace/38`) noticed recent-100 WR crash to 3% and investigated
thoroughly given the timing proximity to that day's riskiest change.

## Investigation summary (ruling out today's other changes first)

1. Dashboard showed WR=3%, PF=0.093 in the recent-100 window. All 30
   sampled closed trades showed `exit_reason=TIMEOUT` — consistent with
   the long-documented, pre-existing 100%-TIMEOUT problem
   (`docs/P1_0_ACCEPTANCE.md` cites the same pattern from 2026-08-06/07),
   not obviously new.
2. Queried `cache.sqlite` directly (not the dashboard's cached view) for
   `bucket`/`source`/`paper_source`/etc. attribution on recent trades:
   **all NULL** on every trade since a specific transition point.
3. Traced the transition precisely: `bucket IS NULL` starts at
   **2026-08-18T06:48:58 UTC** — no transition back since. Correlates in
   time with that day's *first* deploy (the Firebase quota conflation
   fix, `_workspace/34`, `[DEPLOY_OK]` logged at 06:48:42 UTC, 16s
   earlier) — but that commit's content (pure Firestore quota tracking)
   has no code path that touches trade attribution, ruling it out as the
   direct cause.
4. Checked the exact `[PAPER_TRAIN_QUALITY_ENTRY]` log line for one of
   the null-attribution trades at its OPEN time: it showed
   `bucket=C_WEAK_EV_TRAIN training_bucket=C_WEAK_EV_TRAIN
   source=paper_evidence_collection` — **correctly populated in memory
   at open time.** This ruled out every admission/opening-side hypothesis
   (including this session's own admission-path-unification and
   evidence-scope-widening changes) and pointed at the **write-to-SQLite
   path on close** instead.
5. Found `src/services/local_persistent_cache.py`'s `save_closed_trade()`
   — the confirmed sole/authoritative sink for `cache.sqlite` closed
   trades (per an existing code comment: a second, dead sink was already
   removed 2026-07-16) — and its `INSERT OR REPLACE INTO closed_trades`
   statement **never included** `source`, `tp_sl_profile`, `bucket`,
   `training_bucket`, `explore_bucket`, `paper_source`, `learning_source`,
   `readiness_eligible`, `real_readiness_eligible`, `paper_learning_only`,
   `learning_shadow_only`, or `tags_json` — despite the live database
   already having all these columns (added at some earlier, untracked
   point — this project has a documented history of ad-hoc schema drift,
   e.g. the systemd-overlay incident) and despite `close_paper_position()`
   passing a `closed_trade` dict that spreads the full position
   (`{**pos, ...}`) and therefore genuinely has these fields available.

**Conclusion: pre-existing, structural bug, NOT caused by any of this
session's 2026-08-18 changes.** None of today's five other commits touch
`local_persistent_cache.py`. The exact 06:48:58 UTC start-time coincidence
with the quota-fix deploy remains unexplained (possibly restart-related
state, possibly this bug has been present for longer and simply wasn't
observed this closely before) — not fully root-caused, disclosed rather
than overclaimed. What matters operationally: attribution has been lost
for every trade closed since at least that point, until this fix.

## Fix

`local_persistent_cache.py`:
1. `_init_db()`'s migration list extended (idempotent `ALTER TABLE ADD
   COLUMN`, same pattern as the existing F8 migration) to declare all 12
   missing columns — needed so a fresh/local/test database also gets
   them, not just the already-migrated production one.
2. `save_closed_trade()`'s INSERT statement extended to actually write
   all 12 columns from the `trade` dict. `bucket` uses the same
   `bucket or training_bucket or explore_bucket` fallback precedence
   `trade_executor.py`'s own readers already use elsewhere (consistency,
   not a new convention). Booleans (`readiness_eligible` etc.) convert to
   0/1/NULL explicitly (`None` stays `None` — "unknown" is not coerced to
   "false"). `tags` (a list) is JSON-serialized to `tags_json`, empty
   list stores `NULL` not `"[]"`.

## Impact assessment

- **No trading-safety impact.** Core trade mechanics (entry/exit price,
  PnL, win/loss, exit_reason, regime, MFE/MAE) were never affected — only
  the secondary attribution/learning-source metadata.
- **Real impact**: any learning-loop logic that reads `bucket`/
  `paper_source`/`learning_source` from `cache.sqlite` (segment weight
  updates, bucket-specific metrics, dashboard bucket breakdowns) has been
  working with incomplete data for every trade closed in the affected
  window (~06:48 UTC onward until this fix deploys) — a real accuracy
  gap in the learning system for that window, though the live in-memory
  position always had it correctly (so anything reading the position
  BEFORE close, e.g. Firebase sync via `trade_executor.py`'s separate
  Firestore write path using the same `closed_trade` dict directly, was
  unaffected — only the local SQLite copy was incomplete).

## Tests

`tests/test_local_persistent_cache_attribution.py` (new, 10 tests):
attribution persists correctly, bucket fallback precedence, boolean
0/1/NULL conversion (including "unknown stays unknown"), tags JSON
serialization (including empty-list-is-NULL), missing fields don't crash
(backward compat with genuinely old trade dicts), core fields unaffected,
`INSERT OR REPLACE` correctly updates attribution on a rewrite, fresh
database gets the migration, `_init_db()` idempotent on re-call. Full
regression sweep (this file + `test_paper_close_pipeline.py` +
`test_closed_trades_migration.py` + `test_paper_mode.py`): 282 passed, 1
pre-existing failure, 4 skipped. `test_v5_legacy_bridge_hooks.py`'s 12
failures confirmed pre-existing (same as every other check this session).

## What is NOT fixed by this patch (disclosed)

- Historical trades closed between 06:48:58 UTC and this fix's deploy
  keep their NULL attribution permanently (no backfill attempted —
  the source data, i.e. which bucket/strategy each trade came from, is
  gone; a backfill would have to guess, which is worse than an honest
  gap).
- The exact reason the bug's effects started precisely at 06:48:58 UTC
  today (rather than being visible in earlier historical data) is not
  conclusively root-caused — flagged, not resolved.
