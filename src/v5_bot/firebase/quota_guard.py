"""QuotaGuard — hard Firestore quota enforcement with SQLite ledger.

Tracks read/write/delete attempts against daily caps (Pacific timezone).
Enforces internal soft caps with significant headroom below official quota.
Circuit breaker pattern for CRITICAL and HARD_STOP states.
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
import pytz
import logging

from src.v5_bot.util.datetime_utils import utc_now, utc_timestamp_iso

logger = logging.getLogger(__name__)


class QuotaLedger:
    """SQLite-backed quota counter for a single day."""

    DB_PATH = Path("runtime/v5_quota_usage.sqlite")
    SCHEMA_VERSION = 1

    def __init__(self):
        """Initialize SQLite quota ledger."""
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quota_daily (
                    date TEXT PRIMARY KEY,
                    reads_attempted INTEGER DEFAULT 0,
                    writes_attempted INTEGER DEFAULT 0,
                    deletes_attempted INTEGER DEFAULT 0,
                    retries_attempted INTEGER DEFAULT 0,
                    state TEXT DEFAULT 'normal',
                    updated_at TEXT
                )
                """
            )
            conn.commit()

    def _pt_date(self) -> str:
        """Current date in Pacific timezone (YYYYMMDD)."""
        tz = pytz.timezone('America/Los_Angeles')
        return datetime.now(tz).strftime('%Y%m%d')

    def record_operation(self, op_type: str, count: int = 1) -> None:
        """
        Record an operation attempt (before actual Firestore call).

        Args:
            op_type: 'read', 'write', 'delete', or 'retry'
            count: number of operations (default 1)
        """
        date = self._pt_date()
        with sqlite3.connect(self.DB_PATH) as conn:
            # Ensure row exists
            conn.execute(
                "INSERT OR IGNORE INTO quota_daily (date, updated_at) VALUES (?, ?)",
                (date, utc_timestamp_iso()),
            )

            # Increment counter
            if op_type == 'read':
                conn.execute("UPDATE quota_daily SET reads_attempted = reads_attempted + ? WHERE date = ?", (count, date))
            elif op_type == 'write':
                conn.execute("UPDATE quota_daily SET writes_attempted = writes_attempted + ? WHERE date = ?", (count, date))
            elif op_type == 'delete':
                conn.execute("UPDATE quota_daily SET deletes_attempted = deletes_attempted + ? WHERE date = ?", (count, date))
            elif op_type == 'retry':
                conn.execute("UPDATE quota_daily SET retries_attempted = retries_attempted + ? WHERE date = ?", (count, date))

            conn.execute("UPDATE quota_daily SET updated_at = ? WHERE date = ?", (utc_timestamp_iso(), date))
            conn.commit()

    def get_daily_usage(self) -> Tuple[int, int, int, int]:
        """
        Get current day's usage.

        Returns:
            (reads_attempted, writes_attempted, deletes_attempted, retries_attempted)
        """
        date = self._pt_date()
        with sqlite3.connect(self.DB_PATH) as conn:
            row = conn.execute(
                "SELECT reads_attempted, writes_attempted, deletes_attempted, retries_attempted FROM quota_daily WHERE date = ?",
                (date,),
            ).fetchone()
        if row:
            return row
        return (0, 0, 0, 0)

    def update_state(self, state: str) -> None:
        """Update quota state for current day."""
        date = self._pt_date()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("INSERT OR IGNORE INTO quota_daily (date, updated_at) VALUES (?, ?)", (date, utc_timestamp_iso()))
            conn.execute("UPDATE quota_daily SET state = ?, updated_at = ? WHERE date = ?", (state, utc_timestamp_iso(), date))
            conn.commit()

    def get_state(self) -> str:
        """Get quota state for current day."""
        date = self._pt_date()
        with sqlite3.connect(self.DB_PATH) as conn:
            row = conn.execute("SELECT state FROM quota_daily WHERE date = ?", (date,)).fetchone()
        if row:
            return row[0]
        return "normal"


class QuotaGuard:
    """Hard quota enforcer with circuit breaker."""

    # Internal operational caps (well below official 50k reads / 20k writes)
    SOFT_CAP_READS = 4000
    SOFT_CAP_WRITES = 1500
    HARD_CAP_READS = 8000
    HARD_CAP_WRITES = 3000

    # State transitions
    THRESHOLD_WARNING_READS = 4000
    THRESHOLD_WARNING_WRITES = 1500
    THRESHOLD_DEGRADED_READS = 6000
    THRESHOLD_DEGRADED_WRITES = 2500
    THRESHOLD_CRITICAL_READS = 7500
    THRESHOLD_CRITICAL_WRITES = 2800

    def __init__(self):
        """Initialize quota guard with SQLite ledger."""
        self.ledger = QuotaLedger()

    def check_can_read(self, count: int = 1) -> Tuple[bool, str]:
        """
        Pre-flight check: can we perform reads?

        Args:
            count: number of read operations

        Returns:
            (allowed: bool, reason: str)
        """
        reads, writes, deletes, retries = self.ledger.get_daily_usage()
        state = self._compute_state(reads, writes)

        if state == "hard_stop":
            return False, "HARD_STOP_FIRESTORE: read quota exhausted"
        if state == "critical" and reads + count >= self.HARD_CAP_READS:
            return False, "CRITICAL: would exceed hard read cap"
        if reads + count >= self.HARD_CAP_READS:
            return False, "read quota hard limit"

        return True, ""

    def check_can_write(self, count: int = 1) -> Tuple[bool, str]:
        """
        Pre-flight check: can we perform writes?

        Args:
            count: number of write operations

        Returns:
            (allowed: bool, reason: str)
        """
        reads, writes, deletes, retries = self.ledger.get_daily_usage()
        state = self._compute_state(reads, writes)

        if state == "hard_stop":
            return False, "HARD_STOP_FIRESTORE: write quota exhausted"
        if state == "critical" and writes + count >= self.HARD_CAP_WRITES:
            return False, "CRITICAL: would exceed hard write cap"
        if writes + count >= self.HARD_CAP_WRITES:
            return False, "write quota hard limit"

        return True, ""

    def check_entry_write_reserve(self, open_count: int, new_close_writes: int = 4) -> Tuple[bool, str]:
        """
        Check if we have enough write budget to close all open positions + new entry.

        Entry is only allowed if:
            remaining_writes >= (open_count * close_writes) + new_close_writes + emergency_reserve
        Entry is blocked during CRITICAL and HARD_STOP states (if reserve is sufficient).

        Args:
            open_count: number of currently open positions
            new_close_writes: writes needed for one new trade lifecycle (default 4)

        Returns:
            (allowed: bool, reason: str)
        """
        reads, writes, deletes, retries = self.ledger.get_daily_usage()
        state = self._compute_state(reads, writes)

        emergency_reserve = 20
        close_writes_per_trade = 3  # trade close + open_positions update + optional metrics

        total_needed = (open_count * close_writes_per_trade) + new_close_writes + emergency_reserve
        remaining = self.HARD_CAP_WRITES - writes

        # Check reserve insufficiency first (more specific reason)
        if remaining < total_needed:
            return False, f"insufficient write reserve: {remaining} available, {total_needed} needed"

        # Then check state blocking (only if reserve is sufficient)
        if state in ("critical", "hard_stop"):
            return False, f"entry blocked during {state} quota state"

        return True, ""

    def record_read(self, count: int = 1) -> None:
        """Record successful read attempt."""
        self.ledger.record_operation('read', count)
        self._update_state()

    def record_write(self, count: int = 1) -> None:
        """Record successful write attempt."""
        self.ledger.record_operation('write', count)
        self._update_state()

    def record_delete(self, count: int = 1) -> None:
        """Record successful delete attempt."""
        self.ledger.record_operation('delete', count)
        self._update_state()

    def record_retry(self) -> None:
        """Record a retry attempt (counted separately for diagnostics)."""
        self.ledger.record_operation('retry', 1)

    def _compute_state(self, reads: int, writes: int) -> str:
        """Determine quota state based on usage."""
        if reads >= self.HARD_CAP_READS or writes >= self.HARD_CAP_WRITES:
            return "hard_stop"
        if reads >= self.THRESHOLD_CRITICAL_READS or writes >= self.THRESHOLD_CRITICAL_WRITES:
            return "critical"
        if reads >= self.THRESHOLD_DEGRADED_READS or writes >= self.THRESHOLD_DEGRADED_WRITES:
            return "degraded"
        if reads >= self.THRESHOLD_WARNING_READS or writes >= self.THRESHOLD_WARNING_WRITES:
            return "warning"
        return "normal"

    def _update_state(self) -> None:
        """Update state in ledger based on current usage."""
        reads, writes, deletes, retries = self.ledger.get_daily_usage()
        new_state = self._compute_state(reads, writes)
        self.ledger.update_state(new_state)

    def get_status(self) -> dict:
        """Get current quota status."""
        reads, writes, deletes, retries = self.ledger.get_daily_usage()
        state = self._compute_state(reads, writes)
        self.ledger.update_state(state)

        return {
            "state": state,
            "reads_attempted": reads,
            "reads_remaining": max(0, self.HARD_CAP_READS - reads),
            "writes_attempted": writes,
            "writes_remaining": max(0, self.HARD_CAP_WRITES - writes),
            "deletes_attempted": deletes,
            "retries_attempted": retries,
            "timestamp": utc_timestamp_iso(),
        }

    def reset_daily_quota(self) -> None:
        """Reset quota for a new day (should be called at startup if new day detected)."""
        logger.info("Resetting daily quota for new PT day")
        self.ledger._init_db()
