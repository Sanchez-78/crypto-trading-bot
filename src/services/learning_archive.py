"""Durable, quota-bounded learning archive with a Firestore outbox.

The local SQLite database is authoritative for runtime continuity.  Firebase is
an idempotent, append-only archive used for disaster recovery and bounded
startup hydration.  The market/tick path never performs network I/O.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MAX_EVENT_BYTES = 850_000
DEFAULT_FLUSH_LIMIT = 50


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _default_path() -> Path:
    configured = os.getenv("LEARNING_ARCHIVE_DB", "").strip()
    if configured:
        return Path(configured)
    production = Path("/opt/cryptomaster")
    base = production if production.is_dir() else Path(".")
    return base / "local_learning_storage" / "learning_archive.sqlite"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {
            str(key)[:200]: _json_safe(item)
            for key, item in value.items()
            if key is not None
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class LearningArchive:
    """SQLite append-only event log plus an idempotent Firebase outbox."""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        clock: Callable[[], float] = time.time,
    ):
        self.path = Path(path or _default_path())
        self._clock = clock
        self._lock = threading.RLock()
        self._last_flush_at = 0.0
        self._last_flush_error: Optional[str] = None
        self._last_hydrated = 0
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_archive_events (
                    event_id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    synced_at REAL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_archive_pending
                ON learning_archive_events(synced_at, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_archive_type
                ON learning_archive_events(event_type, created_at DESC)
                """
            )

    def append(
        self,
        event_type: str,
        payload: dict,
        *,
        event_id: Optional[str] = None,
        created_at: Optional[float] = None,
        synced: bool = False,
    ) -> dict:
        event_type = str(event_type or "").strip().lower()
        if not event_type or not isinstance(payload, dict):
            return {"accepted": False, "reason": "invalid_event"}

        created_at = float(self._clock() if created_at is None else created_at)
        safe_payload = _json_safe(payload)
        payload_json = _canonical_json(safe_payload)
        if len(payload_json.encode("utf-8")) > MAX_EVENT_BYTES:
            return {"accepted": False, "reason": "event_too_large"}

        if not event_id:
            digest = hashlib.sha256(
                f"{event_type}\0{payload_json}".encode("utf-8")
            ).hexdigest()
            event_id = digest
        event_id = str(event_id).strip()
        if (
            not event_id
            or len(event_id) > 240
            or "/" in event_id
            or event_id in {".", ".."}
        ):
            return {"accepted": False, "reason": "invalid_event_id"}

        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO learning_archive_events
                (event_id, schema_version, event_type, created_at, payload_json,
                 synced_at, attempts, last_error)
                VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
                """,
                (
                    event_id,
                    SCHEMA_VERSION,
                    event_type,
                    created_at,
                    payload_json,
                    created_at if synced else None,
                ),
            )
            accepted = cursor.rowcount == 1
            if not accepted:
                existing = connection.execute(
                    """
                    SELECT event_type, payload_json
                    FROM learning_archive_events
                    WHERE event_id = ?
                    """,
                    (event_id,),
                ).fetchone()
                if (
                    existing is None
                    or existing["event_type"] != event_type
                    or existing["payload_json"] != payload_json
                ):
                    return {
                        "accepted": False,
                        "duplicate": False,
                        "reason": "event_id_payload_conflict",
                        "event_id": event_id,
                    }
        return {
            "accepted": accepted,
            "duplicate": not accepted,
            "event_id": event_id,
        }

    def pending(self, limit: int = DEFAULT_FLUSH_LIMIT) -> list[dict]:
        limit = min(max(int(limit), 1), 200)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, schema_version, event_type, created_at,
                       payload_json, attempts
                FROM learning_archive_events
                WHERE synced_at IS NULL
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"corrupt_learning_archive_payload:{row['event_id']}"
                ) from exc
            if not isinstance(payload, dict):
                raise RuntimeError(
                    f"invalid_learning_archive_payload:{row['event_id']}"
                )
            events.append(
                {
                    "event_id": row["event_id"],
                    "schema_version": row["schema_version"],
                    "event_type": row["event_type"],
                    "created_at": row["created_at"],
                    "payload": payload,
                    "attempts": row["attempts"],
                }
            )
        return events

    def mark_synced(self, event_ids: Iterable[str]) -> int:
        ids = [str(value) for value in event_ids if value]
        if not ids:
            return 0
        now = float(self._clock())
        with self._lock, self._connect() as connection:
            cursor = connection.executemany(
                """
                UPDATE learning_archive_events
                SET synced_at = ?, last_error = NULL
                WHERE event_id = ?
                """,
                [(now, event_id) for event_id in ids],
            )
        return max(0, cursor.rowcount)

    def mark_failed(self, event_ids: Iterable[str], error: str) -> None:
        ids = [str(value) for value in event_ids if value]
        if not ids:
            return
        message = str(error or "unknown")[:500]
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                UPDATE learning_archive_events
                SET attempts = attempts + 1, last_error = ?
                WHERE event_id = ?
                """,
                [(message, event_id) for event_id in ids],
            )

    def recent(self, event_type: str, limit: int = 1) -> list[dict]:
        limit = min(max(int(limit), 1), 200)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, created_at, payload_json, synced_at
                FROM learning_archive_events
                WHERE event_type = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(event_type).strip().lower(), limit),
            ).fetchall()
        result = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                payload = {}
            result.append(
                {
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "created_at": row["created_at"],
                    "payload": payload,
                    "synced": row["synced_at"] is not None,
                }
            )
        return result

    def flush(
        self,
        *,
        limit: int = DEFAULT_FLUSH_LIMIT,
        writer: Optional[Callable[[list[dict]], Iterable[str]]] = None,
    ) -> dict:
        if not _env_bool("FIREBASE_LEARNING_ARCHIVE_ENABLED", True):
            return {**self.status(), "flush": "disabled"}

        events = self.pending(limit)
        if not events:
            self._last_flush_at = float(self._clock())
            self._last_flush_error = None
            return {**self.status(), "flush": "idle", "sent": 0}

        ids = [event["event_id"] for event in events]
        try:
            if writer is None:
                from src.services.firebase_client import (
                    save_learning_archive_batch,
                )

                writer = save_learning_archive_batch
            synced_ids = list(writer(events) or ())
            synced_set = {str(value) for value in synced_ids}
            if synced_set:
                self.mark_synced(synced_set)
            missing = [event_id for event_id in ids if event_id not in synced_set]
            if missing:
                self.mark_failed(missing, "firebase_writer_did_not_confirm")
            self._last_flush_at = float(self._clock())
            self._last_flush_error = (
                None if not missing else "firebase_writer_did_not_confirm"
            )
            return {
                **self.status(),
                "flush": "sent" if synced_set else "deferred",
                "sent": len(synced_set),
            }
        except Exception as exc:
            self.mark_failed(ids, f"{type(exc).__name__}: {exc}")
            self._last_flush_at = float(self._clock())
            self._last_flush_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            log.warning("[LEARNING_ARCHIVE_FLUSH_ERROR] %s", self._last_flush_error)
            return {**self.status(), "flush": "failed", "sent": 0}

    def hydrate(
        self,
        *,
        limit: int = 50,
        loader: Optional[Callable[[int], list[dict]]] = None,
    ) -> int:
        """Bounded Firebase-to-local restore; never replaces local events."""
        try:
            if loader is None:
                from src.services.firebase_client import load_learning_archive

                loader = load_learning_archive
            events = loader(min(max(int(limit), 1), 200)) or []
        except Exception as exc:
            log.warning("[LEARNING_ARCHIVE_HYDRATE_ERROR] %s", exc)
            return 0

        loaded = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            payload = event.get("payload")
            event_id = str(event.get("event_id") or "")
            try:
                schema_version = int(event.get("schema_version", SCHEMA_VERSION))
                created_at = float(event.get("created_at"))
            except (TypeError, ValueError):
                continue
            if (
                schema_version != SCHEMA_VERSION
                or not isinstance(payload, dict)
                or not event_id
                or "/" in event_id
                or event_id in {".", ".."}
                or not math.isfinite(created_at)
                or created_at <= 0
            ):
                continue
            result = self.append(
                event.get("event_type", ""),
                payload,
                event_id=event_id,
                created_at=created_at,
                synced=True,
            )
            loaded += int(bool(result.get("accepted")))
        self._last_hydrated = loaded
        return loaded

    def status(self) -> dict:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN synced_at IS NULL THEN 1 ELSE 0 END) AS pending,
                       MAX(CASE WHEN synced_at IS NOT NULL THEN synced_at END) AS last_synced,
                       MAX(created_at) AS last_event
                FROM learning_archive_events
                """
            ).fetchone()
        return {
            "agent": "firebase_archive",
            "status": (
                "degraded"
                if self._last_flush_error
                else ("pending" if int(row["pending"] or 0) else "healthy")
            ),
            "total_events": int(row["total"] or 0),
            "pending_events": int(row["pending"] or 0),
            "last_event_at": row["last_event"],
            "last_synced_at": row["last_synced"],
            "last_flush_at": self._last_flush_at or None,
            "last_error": self._last_flush_error,
            "last_hydrated": self._last_hydrated,
            "db_path": str(self.path),
        }


_archive: Optional[LearningArchive] = None
_archive_lock = threading.Lock()


def get_learning_archive() -> LearningArchive:
    global _archive
    if _archive is None:
        with _archive_lock:
            if _archive is None:
                _archive = LearningArchive()
    return _archive


def archive_learning_event(
    event_type: str,
    payload: dict,
    *,
    event_id: Optional[str] = None,
    created_at: Optional[float] = None,
) -> dict:
    return get_learning_archive().append(
        event_type,
        payload,
        event_id=event_id,
        created_at=created_at,
    )


def flush_learning_archive(limit: int = DEFAULT_FLUSH_LIMIT) -> dict:
    return get_learning_archive().flush(limit=limit)


def get_learning_archive_status() -> dict:
    return get_learning_archive().status()
