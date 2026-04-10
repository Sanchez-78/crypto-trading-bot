"""
audit_worker.py — Redis -> Firestore Bridge (Phase 5 Task 2)

Subscribes to Redis channel "audits", receives rejection/alert events, 
and persists them to Firestore collection "audits" for real-time 
visibility in the React Native app.

Throttling: 
  - Max 1 write per second per reason to avoid db hammering.
  - Keeps only the last 50 audits total (circular buffer logic).
"""

import asyncio
import json
import logging
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

REDIS_URL: str      = "redis://localhost:6379/0"
AUDIT_CHANNEL: str  = "audits"
MAX_AUDITS: int    = 50

class AuditWorker:
    def __init__(self) -> None:
        self._running = False
        self._redis: Optional[Any] = None
        self._last_write_ts: dict[str, float] = {}

    async def _get_redis(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        return self._redis

    async def start(self) -> None:
        self._running = True
        log.info("AuditWorker started (subscribing to '%s')", AUDIT_CHANNEL)
        
        while self._running:
            try:
                r      = await self._get_redis()
                pubsub = r.pubsub()
                await pubsub.subscribe(AUDIT_CHANNEL)
                
                async for message in pubsub.listen():
                    if not self._running: break
                    if message["type"] != "message": continue
                    
                    try:
                        data = json.loads(message["data"])
                        await self._persist_audit(data)
                    except Exception as exc:
                        log.warning("Audit parse error: %s", exc)
                        
            except Exception as exc:
                log.warning("AuditWorker connection lost: %s — reconnecting in 5s", exc)
                self._redis = None
                await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    async def _persist_audit(self, data: dict) -> None:
        """Throttled write to Firestore."""
        reason = data.get("reason", "unknown")
        now = time.time()
        
        # Throttle: 1s per reason type
        if now - self._last_write_ts.get(reason, 0) < 1.0:
            return
            
        self._last_write_ts[reason] = now
        
        try:
            from src.services.firebase_client import db
            if db is None: return
            
            # Use background executor for Firestore blocking calls
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._sync_write, db, data)
        except Exception as exc:
            log.debug("_persist_audit error: %s", exc)

    def _sync_write(self, db: Any, data: dict) -> None:
        try:
            # Write new audit
            db.collection("audits").add({
                **data,
                "server_ts": time.time()
            })
            
            # Simple cleanup: delete oldest if > MAX_AUDITS
            # (In production, a triggered Cloud Function is better, but this works for HFT-lite)
            snap = db.collection("audits").order_by("timestamp", direction="DESCENDING").offset(MAX_AUDITS).limit(10).get()
            for doc in snap:
                doc.reference.delete()
                
        except Exception as exc:
            log.debug("_sync_write error: %s", exc)

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
