"""
audit_worker.py — Redis -> Firestore Bridge (Phase 5 Task 2)

Subscribes to Redis channel "audits", receives rejection/alert events, 
and persists them to Firestore collection "audits" for real-time 
visibility in the React Native app.

Throttling: 
  - Max 1 write per second per reason to avoid db hammering.
  - Buffers events for up to 3 seconds, then batch-commits.
  - Keeps only the last 50 audits total (circular buffer logic).
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

REDIS_URL: str      = os.getenv("REDIS_URL", "redis://localhost:6379/0")
AUDIT_CHANNEL: str  = "audits"
MAX_AUDITS: int    = 50
BATCH_INTERVAL: float = 3.0   # seconds between batch flushes
# 2026-08-14 (_workspace/26_quota_burn_found_audit_worker_offset.md): the
# cleanup query below (.offset(MAX_AUDITS)) was running on every single
# batch flush -- as often as every BATCH_INTERVAL (3s) whenever the buffer
# had anything. Firestore bills an offset() query for every document it
# skips server-side, not just the ones returned, so each cleanup call was
# reading on the order of MAX_AUDITS+20 documents regardless of whether
# cleanup was actually needed. Confirmed live via the Firestore read tracer
# (finally working after 3 tracer generations, see _workspace/22/23_...md):
# this was the single largest READ call site during an active quota-burn
# window. Throttling the cleanup to once per CLEANUP_INTERVAL_S is enough --
# the audits collection is naturally near its 50-doc cap already (this
# worker enforces it), so it doesn't need re-trimming on every 3s flush.
CLEANUP_INTERVAL_S: float = 300.0  # only run the cleanup this often
# 2026-08-26 v1 (_workspace/47_...md): the throttle above reduced call
# FREQUENCY, but the .offset(MAX_AUDITS) query still bills 50 skipped reads
# every call. ALSO (found independently by two review agents during patch
# review, not by this session's own analysis): the DESCENDING+offset(50)
# query was deleting the 51st-70th NEWEST documents, never the true oldest
# tail -- so the "audits" collection grew to ~92,684 documents despite
# MAX_AUDITS=50 because the cleanup never reached the actual backlog at
# all, regardless of the read-cost question.
#
# 2026-08-26 v2 (after review): v1 of this fix replaced offset() with a
# per-pass aggregate .count() call, intending to save reads. REJECTED on
# review: Firestore bills count() at 1 read per 1,000 index entries
# matched, so against a ~92,684-doc collection count() actually costs
# ~93 reads, not 1 -- calling it every cleanup pass roughly DOUBLED the
# read cost (153/call vs the old 70/call) during the exact period (a huge
# backlog) where it mattered most, and count() is also invisible to the
# Firestore read tracer (not one of the classes it patches), making the
# new dominant cost unobservable to the instrument built to catch exactly
# this. Fixed to v2: cache the count locally, refreshed only once per
# CLEANUP_COUNT_REFRESH_S (~hourly) via a real .count() call, and kept
# in sync between refreshes purely from local knowledge (+= len(items)
# on every successful write batch, -= the actual delete count on every
# cleanup pass) -- no extra Firestore reads needed to track it. Net cost
# ~9,672 reads/day (drain query 60/pass x ~124 passes/day + ~93 reads/hour
# for the periodic count refresh), roughly at parity with the old code's
# estimated cost while ACTUALLY draining the true oldest tail via the
# ASCENDING order_by kept from v1. Deliberately NOT a one-shot full-backlog
# drain (would cost ~92k reads, an entire day's quota, in one call) --
# clears gradually; a Firestore TTL policy on the `timestamp` field would
# eliminate the backlog risk entirely going forward but requires Firebase
# Console/gcloud access this session does not have -- flagged for the
# user, not something silently configured here.
CLEANUP_BATCH_LIMIT: int = 60
CLEANUP_COUNT_REFRESH_S: float = 3600.0  # re-run the real count() at most this often

class AuditWorker:
    def __init__(self) -> None:
        self._running = False
        self._redis: Optional[Any] = None
        self._last_write_ts: dict[str, float] = {}
        self._buffer: list[dict] = []
        self._flush_task: Optional[asyncio.Task] = None
        self._last_cleanup_ts: float = 0.0
        self._cached_audit_count: Optional[int] = None
        self._last_count_refresh_ts: float = 0.0

    async def _get_redis(self) -> Optional[Any]:
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
            except ImportError:
                log.error("❌ CRITICAL: 'redis' module NOT FOUND. 'AuditWorker' (Redis -> Firestore bridge) is DISABLED.")
                log.error("   To fix this, run: pip install redis")
                self._running = False  # Shut down to prevent infinite loop
                return None
        return self._redis

    async def start(self) -> None:
        self._running = True
        log.info("AuditWorker started (subscribing to '%s')", AUDIT_CHANNEL)
        
        # Start background flush loop
        self._flush_task = asyncio.create_task(self._flush_loop())
        
        fail_count = 0
        while self._running:
            try:
                r = await self._get_redis()
                if r is None:
                    # redis module missing, already logged
                    self._running = False
                    break
                
                pubsub = r.pubsub()
                await pubsub.subscribe(AUDIT_CHANNEL)
                
                # Success - reset fail_count
                if fail_count > 0:
                    log.info("📡 AuditWorker: Redis connection RESTORED after %d failed attempts.", fail_count)
                fail_count = 0

                async for message in pubsub.listen():
                    if not self._running: break
                    if message["type"] != "message": continue
                    
                    try:
                        data = json.loads(message["data"])
                        self._buffer_audit(data)
                    except Exception as exc:
                        log.warning("Audit parse error: %s", exc)
                        
            except Exception as exc:
                if "No module named 'redis'" in str(exc) or isinstance(exc, ImportError):
                    log.error("❌ CRITICAL: 'redis' module missing. Disabling AuditWorker. Run: pip install redis")
                    self._running = False
                    break

                fail_count += 1
                # Exponential backoff: 5s, 10s, 20s, 40s, up to 60s max
                backoff = min(60, 5 * (2 ** (min(fail_count - 1, 4))))

                if fail_count == 1:
                    log.warning("⚠️  AuditWorker: Redis connection lost/failed. Retrying with exponential backoff (5s→60s). Error: %s", exc)
                elif fail_count % 3 == 0:
                    log.warning("⚠️  AuditWorker: Reconnection attempt #%d failed (backoff: %ds). Check Redis server: redis-cli ping", fail_count, int(backoff))
                else:
                    log.debug("AuditWorker reconnection attempt #%d failed (next retry: %ds): %s", fail_count, int(backoff), exc)

                self._redis = None
                await asyncio.sleep(backoff)

    async def stop(self) -> None:
        self._running = False
        # Flush remaining buffer
        if self._buffer:
            await self._flush_batch()
        if self._flush_task:
            self._flush_task.cancel()
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    def _buffer_audit(self, data: dict) -> None:
        """Throttled buffering — skip if same reason was seen < 1s ago."""
        reason = data.get("reason", "unknown")
        now = time.time()
        
        if now - self._last_write_ts.get(reason, 0) < 1.0:
            return
            
        self._last_write_ts[reason] = now
        data["timestamp"] = now
        data["server_ts"] = now
        self._buffer.append(data)

    async def _flush_loop(self) -> None:
        """Periodic flush of buffered audits to Firestore."""
        while self._running:
            await asyncio.sleep(BATCH_INTERVAL)
            if self._buffer:
                await self._flush_batch()

    async def _flush_batch(self) -> None:
        """Batch-commit all buffered audits to Firestore."""
        if not self._buffer:
            return
        
        # Grab and clear buffer atomically
        batch_data = self._buffer[:]
        self._buffer.clear()
        
        try:
            from src.services.firebase_client import db
            if db is None: return
            
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._sync_batch_write, db, batch_data)
        except Exception as exc:
            log.debug("_flush_batch error: %s", exc)

    def _sync_batch_write(self, db: Any, items: list[dict]) -> None:
        """Sync Firestore batch write — runs in executor thread."""
        try:
            batch = db.batch()
            for data in items:
                ref = db.collection("audits").document()
                batch.set(ref, data)
            batch.commit()

            log.debug("Audit batch committed: %d events", len(items))

            # Keep the local count estimate in sync with zero extra reads --
            # see CLEANUP_COUNT_REFRESH_S comment above for why this exists.
            if self._cached_audit_count is not None:
                self._cached_audit_count += len(items)

            # Cleanup: delete oldest if > MAX_AUDITS.
            # 2026-08-14 quota-burn fix: throttled to once per
            # CLEANUP_INTERVAL_S instead of every flush.
            # 2026-08-26 v2 quota-burn fix (see CLEANUP_BATCH_LIMIT /
            # CLEANUP_COUNT_REFRESH_S comments above): the real .count() is
            # only actually called once per CLEANUP_COUNT_REFRESH_S; every
            # other pass reuses the locally-tracked estimate. The delete
            # query is ASCENDING-ordered (the true oldest documents, unlike
            # the old DESCENDING+offset(50) pattern which deleted the
            # 51st-70th newest and never reached the actual backlog).
            now = time.time()
            if now - self._last_cleanup_ts >= CLEANUP_INTERVAL_S:
                self._last_cleanup_ts = now
                try:
                    if (
                        self._cached_audit_count is None
                        or (now - self._last_count_refresh_ts) >= CLEANUP_COUNT_REFRESH_S
                    ):
                        count_result = db.collection("audits").count().get()
                        self._cached_audit_count = count_result[0][0].value
                        self._last_count_refresh_ts = now
                        log.info(
                            "[AUDIT_CLEANUP_COUNT_REFRESH] total=%d",
                            self._cached_audit_count,
                        )

                    excess = self._cached_audit_count - MAX_AUDITS
                    if excess > 0:
                        drain_limit = min(excess, CLEANUP_BATCH_LIMIT)
                        snap = db.collection("audits").order_by(
                            "timestamp", direction="ASCENDING"
                        ).limit(drain_limit).get()
                        if snap:
                            del_batch = db.batch()
                            deleted = 0
                            for doc in snap:
                                del_batch.delete(doc.reference)
                                deleted += 1
                            del_batch.commit()
                            self._cached_audit_count -= deleted
                except Exception as e:
                    # 2026-08-26: was a bare `except Exception: pass` -- a
                    # silently-swallowed cleanup failure is exactly how the
                    # collection reached ~92,684 docs under a 50-doc cap
                    # without anyone noticing. Still non-fatal (must not
                    # break the write batch above), but now logged.
                    log.warning("[AUDIT_CLEANUP_FAILED] %s", e)

        except Exception as exc:
            log.debug("_sync_batch_write error: %s", exc)

_worker: Optional[AuditWorker] = None

async def start() -> None:
    global _worker
    if _worker is not None: return
    _worker = AuditWorker()
    await _worker.start()

async def stop() -> None:
    global _worker
    if _worker:
        await _worker.stop()
        _worker = None
