"""Durable outbox for PAPER trade outcomes.

Trades are written to local WAL before Firebase to ensure durability.
If Firebase write fails, outbox holds the outcome until next successful flush.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

from src.v5_bot.util.datetime_utils import utc_now, utc_timestamp_iso

logger = logging.getLogger(__name__)


class TradeOutbox:
    """SQLite-backed WAL for trade outcomes."""

    DB_PATH = Path("runtime/v5_trade_outbox.sqlite")

    def __init__(self):
        """Initialize trade outbox."""
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_outcomes (
                    trade_id TEXT PRIMARY KEY,
                    epoch_id TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    firebase_synced INTEGER DEFAULT 0,
                    sync_attempts INTEGER DEFAULT 0,
                    last_sync_attempt_at TEXT,
                    last_error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    epoch_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    update_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    firebase_synced INTEGER DEFAULT 0,
                    sync_attempts INTEGER DEFAULT 0,
                    last_sync_attempt_at TEXT
                )
                """
            )
            conn.commit()

    def enqueue_trade_outcome(self, trade_id: str, epoch_id: str, outcome: Dict[str, Any]) -> None:
        """
        Persist a trade close outcome before Firebase write.

        Args:
            trade_id: unique trade identifier
            epoch_id: current epoch
            outcome: complete close data (from v5_trades close operation)
        """
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trade_outcomes
                (trade_id, epoch_id, outcome_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (trade_id, epoch_id, json.dumps(outcome), utc_timestamp_iso()),
            )
            conn.commit()
        logger.debug(f"Enqueued trade outcome: {trade_id}")

    def enqueue_learning_update(self, epoch_id: str, segment_id: str, update: Dict[str, Any]) -> None:
        """
        Persist a learning state update before Firebase write.

        Args:
            epoch_id: current epoch
            segment_id: segment being updated
            update: learning state diff/changes
        """
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO learning_updates
                (epoch_id, segment_id, update_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (epoch_id, segment_id, json.dumps(update), utc_timestamp_iso()),
            )
            conn.commit()
        logger.debug(f"Enqueued learning update: {segment_id}")

    def get_pending_trade_outcomes(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get pending (not yet synced) trade outcomes.

        Args:
            limit: maximum number to retrieve

        Returns:
            List of outcome records with trade_id, epoch_id, outcome_json
        """
        with sqlite3.connect(self.DB_PATH) as conn:
            rows = conn.execute(
                """
                SELECT trade_id, epoch_id, outcome_json, sync_attempts
                FROM trade_outcomes
                WHERE firebase_synced = 0
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "trade_id": row[0],
                "epoch_id": row[1],
                "outcome": json.loads(row[2]),
                "sync_attempts": row[3],
            }
            for row in rows
        ]

    def get_pending_learning_updates(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get pending learning updates.

        Args:
            limit: maximum number to retrieve

        Returns:
            List of update records
        """
        with sqlite3.connect(self.DB_PATH) as conn:
            rows = conn.execute(
                """
                SELECT id, epoch_id, segment_id, update_json, sync_attempts
                FROM learning_updates
                WHERE firebase_synced = 0
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            {
                "id": row[0],
                "epoch_id": row[1],
                "segment_id": row[2],
                "update": json.loads(row[3]),
                "sync_attempts": row[4],
            }
            for row in rows
        ]

    def mark_trade_synced(self, trade_id: str) -> None:
        """Mark a trade outcome as successfully synced to Firebase."""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "UPDATE trade_outcomes SET firebase_synced = 1, last_sync_attempt_at = ? WHERE trade_id = ?",
                (utc_timestamp_iso(), trade_id),
            )
            conn.commit()
        logger.debug(f"Marked trade synced: {trade_id}")

    def mark_learning_synced(self, update_id: int) -> None:
        """Mark a learning update as successfully synced to Firebase."""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "UPDATE learning_updates SET firebase_synced = 1, last_sync_attempt_at = ? WHERE id = ?",
                (utc_timestamp_iso(), update_id),
            )
            conn.commit()
        logger.debug(f"Marked learning update synced: {update_id}")

    def record_sync_failure(self, trade_id: str, error: str) -> None:
        """Record a failed sync attempt for a trade."""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                UPDATE trade_outcomes
                SET sync_attempts = sync_attempts + 1,
                    last_sync_attempt_at = ?,
                    last_error = ?
                WHERE trade_id = ?
                """,
                (utc_timestamp_iso(), error, trade_id),
            )
            conn.commit()
        logger.warning(f"Sync failure for trade {trade_id}: {error}")

    def record_learning_sync_failure(self, update_id: int, error: str) -> None:
        """Record a failed sync attempt for a learning update."""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                UPDATE learning_updates
                SET sync_attempts = sync_attempts + 1,
                    last_sync_attempt_at = ?
                WHERE id = ?
                """,
                (utc_timestamp_iso(), update_id),
            )
            conn.commit()
        logger.warning(f"Sync failure for learning update {update_id}: {error}")

    def get_outbox_status(self) -> Dict[str, Any]:
        """Get current outbox status."""
        with sqlite3.connect(self.DB_PATH) as conn:
            trade_pending = conn.execute(
                "SELECT COUNT(*) FROM trade_outcomes WHERE firebase_synced = 0"
            ).fetchone()[0]
            learning_pending = conn.execute(
                "SELECT COUNT(*) FROM learning_updates WHERE firebase_synced = 0"
            ).fetchone()[0]

            oldest_trade = conn.execute(
                "SELECT created_at FROM trade_outcomes WHERE firebase_synced = 0 ORDER BY created_at ASC LIMIT 1"
            ).fetchone()

        oldest_age_s = None
        if oldest_trade:
            created = datetime.fromisoformat(oldest_trade[0])
            oldest_age_s = (utc_now() - created).total_seconds()

        return {
            "pending_trade_outcomes": trade_pending,
            "pending_learning_updates": learning_pending,
            "oldest_pending_age_s": oldest_age_s,
            "timestamp": utc_timestamp_iso(),
        }

    def clear_old_synced(self, days: int = 7) -> None:
        """Delete synced records older than N days."""
        from datetime import timedelta

        cutoff = utc_now() - timedelta(days=days)
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "DELETE FROM trade_outcomes WHERE firebase_synced = 1 AND created_at < ?",
                (cutoff.isoformat(),),
            )
            conn.execute(
                "DELETE FROM learning_updates WHERE firebase_synced = 1 AND created_at < ?",
                (cutoff.isoformat(),),
            )
            conn.commit()
        logger.info(f"Cleaned up synced records older than {days} days")
