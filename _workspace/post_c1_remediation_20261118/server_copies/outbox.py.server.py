"""
V5 Legacy Bridge — Durable Outbox

SQLite-backed outbox for Firebase writes. If Firebase fails, events are queued
with retry logic. Idempotency by (event_type, idempotency_key).

Never loses closed PAPER trades.
"""

import logging
import sqlite3
import json
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List
import hashlib

from . import config

logger = logging.getLogger(__name__)


@dataclass
class OutboxEntry:
    """Outbox event record."""
    id: int
    event_type: str
    idempotency_key: str
    payload: dict
    retry_count: int = 0
    next_retry_at: Optional[str] = None
    error: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


class DurableOutbox:
    """
    Manages outbound events with retry logic and idempotency.

    Event types:
    - paper_open
    - paper_close
    - learning_update
    - dashboard_publish
    - readiness_publish
    - quota_publish

    Idempotency: unique constraint on (event_type, idempotency_key)
    """

    def __init__(self):
        self.db_path = config.V5_OUTBOX_DB_PATH
        self._ensure_runtime_dir()
        self._init_db()

    def _ensure_runtime_dir(self):
        """Create runtime dir with proper permissions."""
        import os

        os.makedirs(config.RUNTIME_DIR, mode=config.RUNTIME_DIR_PERMS, exist_ok=True)
        try:
            os.chmod(config.RUNTIME_DIR, config.RUNTIME_DIR_PERMS)
        except OSError:
            pass

    def _init_db(self):
        """Initialize SQLite database for outbox."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    next_retry_at TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(event_type, idempotency_key)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pending ON outbox(event_type, retry_count, next_retry_at)"
            )
            conn.commit()
            conn.close()

            # Set permissions
            import os

            try:
                os.chmod(self.db_path, config.RUNTIME_FILE_PERMS)
            except OSError:
                pass

        except Exception as e:
            logger.error(f"[V5_BRIDGE] Outbox DB init failed: {e}")

    def enqueue(
        self, event_type: str, idempotency_key: str, payload: dict
    ) -> bool:
        """
        Enqueue an event for Firebase write.

        Args:
            event_type: Type of event (paper_open, paper_close, etc.)
            idempotency_key: Unique key for idempotency (e.g., trade_id)
            payload: Event payload dict

        Returns:
            True if enqueued, False if failed or already exists
        """
        try:
            conn = sqlite3.connect(self.db_path)
            now = datetime.utcnow().isoformat()

            conn.execute(
                """
                INSERT OR IGNORE INTO outbox
                (event_type, idempotency_key, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_type, idempotency_key, json.dumps(payload), now, now),
            )
            conn.commit()
            conn.close()

            logger.info(
                f"[V5_BRIDGE_OUTBOX_ENQUEUED] event_type={event_type} "
                f"idempotency_key={idempotency_key}"
            )
            return True

        except Exception as e:
            logger.error(
                f"[V5_BRIDGE] Outbox enqueue failed: event_type={event_type}, "
                f"idempotency_key={idempotency_key}, error={e}"
            )
            return False

    def get_pending(self, limit: int = 20) -> List[OutboxEntry]:
        """Get pending outbox entries ready for retry."""
        try:
            now = datetime.utcnow().isoformat()
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                """
                SELECT id, event_type, idempotency_key, payload, retry_count,
                       next_retry_at, error, created_at, updated_at
                FROM outbox
                WHERE retry_count < ? AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (config.OUTBOX_MAX_RETRIES, now, limit),
            )

            entries = []
            for row in cursor.fetchall():
                entries.append(
                    OutboxEntry(
                        id=row[0],
                        event_type=row[1],
                        idempotency_key=row[2],
                        payload=json.loads(row[3]),
                        retry_count=row[4],
                        next_retry_at=row[5],
                        error=row[6],
                        created_at=row[7],
                        updated_at=row[8],
                    )
                )

            conn.close()
            return entries

        except Exception as e:
            logger.error(f"[V5_BRIDGE] get_pending failed: {e}")
            return []

    def mark_sent(self, entry_id: int) -> bool:
        """Mark entry as successfully sent."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM outbox WHERE id = ?", (entry_id,))
            conn.commit()
            conn.close()

            logger.info(f"[V5_BRIDGE_OUTBOX_SENT] id={entry_id}")
            return True

        except Exception as e:
            logger.error(f"[V5_BRIDGE] mark_sent failed: {e}")
            return False

    def mark_failed(self, entry_id: int, error: str = "") -> bool:
        """Mark entry as failed and schedule retry."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT retry_count FROM outbox WHERE id = ?", (entry_id,))
            row = cursor.fetchone()

            if not row:
                conn.close()
                return False

            retry_count = row[0]
            retry_count += 1

            # Exponential backoff: 60s, 300s, 900s
            backoff_seconds = min(60 * (2 ** (retry_count - 1)), 900)
            next_retry_at = (
                datetime.utcnow() + timedelta(seconds=backoff_seconds)
            ).isoformat()

            conn.execute(
                """
                UPDATE outbox
                SET retry_count = ?, next_retry_at = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    retry_count,
                    next_retry_at,
                    error[:500],  # Limit error message
                    datetime.utcnow().isoformat(),
                    entry_id,
                ),
            )
            conn.commit()
            conn.close()

            logger.warning(
                f"[V5_BRIDGE_OUTBOX_RETRY] id={entry_id} retry_count={retry_count} "
                f"next_retry_at={next_retry_at} error={error[:100]}"
            )
            return True

        except Exception as e:
            logger.error(f"[V5_BRIDGE] mark_failed failed: {e}")
            return False

    def pending_count(self) -> int:
        """Get count of pending entries."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                "SELECT COUNT(*) FROM outbox WHERE retry_count < ?",
                (config.OUTBOX_MAX_RETRIES,),
            )
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except Exception as e:
            logger.error(f"[V5_BRIDGE] pending_count failed: {e}")
            return 0

    def flush(self, limit: int = 20) -> dict:
        """
        Attempt to flush pending entries.

        This is a stub - actual Firebase writes happen in firebase_writer.py.

        Args:
            limit: Max entries to process

        Returns:
            Status dict with pending count
        """
        pending = self.get_pending(limit)
        return {
            "processed": 0,
            "sent": 0,
            "failed": 0,
            "pending_count": self.pending_count(),
            "entries_in_batch": len(pending),
        }
