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
CLEANUP_INTERVAL_S: float = 300.0  # only run the offset-based cleanup this often

class AuditWorker:
    def __init__(self) -> None:
        self._running = False
        self._redis: Optional[Any] = None
        self._last_write_ts: dict[str, float] = {}
        self._buffer: list[dict] = []
        self._flush_task: Optional[asyncio.Task] = None
        self._last_cleanup_ts: float = 0.0

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

            # Cleanup: delete oldest if > MAX_AUDITS.
            # 2026-08-14 quota-burn fix: this offset() query is expensive
            # (Firestore bills for every skipped document, not just the 20
            # returned) and previously ran on every flush -- throttled to
            # once per CLEANUP_INTERVAL_S since the collection is already
            # kept near its cap and doesn't need re-trimming every 3s.
            now = time.time()
            if now - self._last_cleanup_ts >= CLEANUP_INTERVAL_S:
                self._last_cleanup_ts = now
                try:
                    snap = db.collection("audits").order_by(
                        "timestamp", direction="DESCENDING"
                    ).offset(MAX_AUDITS).limit(20).get()
                    if snap:
                        del_batch = db.batch()
                        for doc in snap:
                            del_batch.delete(doc.reference)
                        del_batch.commit()
                except Exception:
                    pass  # cleanup failure is non-critical
                
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
