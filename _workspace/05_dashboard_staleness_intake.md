# Intake: suspected dashboard/API metrics staleness

## Symptom
`/api/dashboard/metrics` is served by `dashboard_web.py:1141` →
`dashboard_read_model.get_metrics()`. Code trace shows **no caching layer**:
`_read_recent_rows()` opens a fresh read-only sqlite connection
(`local_learning_storage/cache.sqlite`, `mode=ro`) and runs
`SELECT ... ORDER BY exit_ts DESC LIMIT 100` on every call — so the endpoint
*should* always reflect the latest committed rows.

Observed (this session, informal, imprecise timing — needs re-verification
with exact live timestamps):
- Dashboard "recent" block reported wins=45/losses=53/flats=2,
  recent_win_rate_pct=45.0, recent_profit_factor=0.507 at ~06:10:15Z.
- Same fields, byte-identical, at ~06:51:37Z (40 min later).
- A direct SQL query at ~06:52:30Z (`SELECT COUNT(*),SUM(win) FROM (SELECT *
  FROM closed_trades ORDER BY exit_ts DESC LIMIT 100)`) returned wins=38,
  NOT 45 — different from what the API reported ~1 minute earlier.
- `MAX(exit_ts)` in cache.sqlite at ~06:52:30Z was 06:42:22Z — i.e. a new row
  DID land in the table between the two dashboard checks (06:10 and 06:51),
  yet the API's own two reports were identical.
- Meanwhile `server_local_backups/paper_adaptive_learning_state.json`
  (a *different* data source/write path — `lifetime_n`, `qualification_n`)
  visibly advanced in the same window (567→720, 92→245).

## What needs proving, not assuming
1. Is `/api/dashboard/metrics` genuinely stale (same process, same query,
   not reflecting new commits), or was my manual comparison just imprecise
   (wrong timestamps, comparing against a different window definition, or a
   benign race between my two ad-hoc checks)?
2. If genuinely stale: WHERE does the staleness enter — SQLite WAL/read-
   consistency issue on the `mode=ro` connection, a write path that stopped
   committing to `cache.sqlite` specifically (while the separate
   `paper_adaptive_learning_state.json` write path kept working), a lock,
   or something else entirely?
3. Which write path populates `cache.sqlite`'s `closed_trades` table (find
   it, don't assume) — and is IT healthy/erroring?
4. Does `/api/dashboard/metrics/enhanced` and `/api/trades/recent` (same
   read model, `dashboard_read_model.get_enhanced_metrics()` /
   `get_recent_trades()`) share the same symptom or not?

## Explicitly not assumed
- Not assuming this is a bug — could be a legitimate difference in query
  definition between my ad-hoc SQL and the endpoint's actual logic, or a
  timing coincidence. Falsify before patching.

## Static trace done while forensic agent runs (2026-08-06, before live results)

Confirmed the write wiring IS correct end-to-end (not a dead/orphaned
duplicate-pipeline issue like some past findings this session):

`on_price()` (trade_executor.py:3061, the live per-tick handler) calls
`update_paper_positions()` (imported from paper_trade_executor.py:2051,
confirmed via `try: from ... import update_paper_positions except ImportError:
<stub>` — the stub only activates on import failure) → returns closed trades
→ `_save_paper_trade_closed()` (trade_executor.py:1622) →
`local_persistent_cache.save_closed_trade()` (local_persistent_cache.py:257)
→ `INSERT OR REPLACE INTO closed_trades ...` on `LOCAL_DB_PATH` = confirmed
`local_learning_storage/cache.sqlite` (same path the dashboard reads).
Also wired for timeout closes via `check_and_close_timeout_positions()`
(trade_executor.py:3104-3108, checked every 10s).

**Two silent-failure catch points to check the live logs for**, either of
which would explain the symptom without any wiring being "dead":
1. `trade_executor.py:1669` — `except Exception as e:
   log.warning(f"[LOCAL_CACHE_SAVE_FAILED] {e}")` (wraps the
   `save_closed_trade` call itself)
2. `local_persistent_cache.py:311` — `except Exception as e:
   _log.warning(f"[LOCAL_CACHE] save_closed_trade error: {e}")` (inside
   `save_closed_trade` itself — the sqlite INSERT/commit)

If the forensic agent finds either of these firing repeatedly in the live
journal, that is very likely the root cause (write failing silently, e.g.
sqlite lock/timeout=2s contention, schema mismatch, or disk issue) — the
adaptive-learning `record_close()` path is a structurally separate call
(different function, different try/except, different failure domain) so it
can keep advancing lifetime_n/qualification_n while this one silently fails.
