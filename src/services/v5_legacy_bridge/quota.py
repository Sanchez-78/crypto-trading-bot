"""
V5 Legacy Bridge — Quota Guard

Manages daily Firebase read/write quotas with safety reserves for closing positions.
Blocks new PAPER entries if close-reserve is insufficient.
"""

import logging
import sqlite3
import os
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

from . import config

logger = logging.getLogger(__name__)


@dataclass
class QuotaDecision:
    """Result of quota check."""
    allowed: bool
    reason: str = ""
    reads_remaining: int = 0
    writes_remaining: int = 0


class V5LegacyQuotaGuard:
    """
    Manages Firebase quota with daily caps and safety reserves.

    Key rules:
    - 20,000 reads/day cap
    - 10,000 writes/day cap
    - Reserve 500 writes for closing existing positions
    - Reserve 200 writes for new entry lifecycle
    - Reserve 100 emergency writes
    - New entries blocked if reserves cannot be met
    - Existing closes are never blocked (can be outboxed)
    """

    def __init__(self):
        self.db_path = config.V5_QUOTA_DB_PATH
        self.reads_cap = config.V5_ACTIVE_HARD_READS_CAP_PER_DAY
        self.writes_cap = config.V5_ACTIVE_HARD_WRITES_CAP_PER_DAY
        self._ensure_runtime_dir()
        self._init_db()

    def _ensure_runtime_dir(self):
        """Create runtime dir with proper permissions."""
        os.makedirs(config.RUNTIME_DIR, mode=config.RUNTIME_DIR_PERMS, exist_ok=True)
        try:
            os.chmod(config.RUNTIME_DIR, config.RUNTIME_DIR_PERMS)
        except OSError:
            pass  # Silently ignore if cannot chmod

    def _init_db(self):
        """Initialize SQLite database for quota tracking."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quota_usage (
                    date TEXT PRIMARY KEY,
                    reads_used INTEGER DEFAULT 0,
                    writes_used INTEGER DEFAULT 0,
                    reads_recorded INTEGER DEFAULT 0,
                    writes_recorded INTEGER DEFAULT 0,
                    last_reset TEXT,
                    state TEXT DEFAULT 'normal'
                )
            """)
            conn.commit()
            conn.close()

            # Set permissions
            try:
                os.chmod(self.db_path, config.RUNTIME_FILE_PERMS)
            except OSError:
                pass

        except Exception as e:
            logger.error(f"[V5_BRIDGE] Quota DB init failed: {e}")

    def _get_today(self) -> str:
        """Get today's date as YYYY-MM-DD."""
        return datetime.utcnow().date().isoformat()

    def _get_or_create_quota(self):
        """Get or create today's quota record."""
        today = self._get_today()
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("SELECT * FROM quota_usage WHERE date = ?", (today,))
            row = cursor.fetchone()

            if not row:
                conn.execute(
                    "INSERT INTO quota_usage (date, last_reset) VALUES (?, ?)",
                    (today, datetime.utcnow().isoformat()),
                )
                conn.commit()

            conn.close()
        except Exception as e:
            logger.error(f"[V5_BRIDGE] Quota record creation failed: {e}")

    def check_can_read(self, reads: int = 1) -> QuotaDecision:
        """Check if read quota allows the operation."""
        try:
            self._get_or_create_quota()
            today = self._get_today()

            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                "SELECT reads_used FROM quota_usage WHERE date = ?", (today,)
            )
            row = cursor.fetchone()
            conn.close()

            reads_used = row[0] if row else 0
            reads_remaining = max(0, self.reads_cap - reads_used)

            allowed = reads_remaining >= reads
            return QuotaDecision(
                allowed=allowed,
                reason="" if allowed else "READ_QUOTA_EXHAUSTED",
                reads_remaining=reads_remaining,
            )
        except Exception as e:
            logger.error(f"[V5_BRIDGE] check_can_read failed: {e}")
            return QuotaDecision(allowed=False, reason="QUOTA_CHECK_ERROR")

    def check_can_write(self, writes: int = 1) -> QuotaDecision:
        """Check if write quota allows the operation."""
        try:
            self._get_or_create_quota()
            today = self._get_today()

            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                "SELECT writes_used FROM quota_usage WHERE date = ?", (today,)
            )
            row = cursor.fetchone()
            conn.close()

            writes_used = row[0] if row else 0
            writes_remaining = max(0, self.writes_cap - writes_used)

            allowed = writes_remaining >= writes
            return QuotaDecision(
                allowed=allowed,
                reason="" if allowed else "WRITE_QUOTA_EXHAUSTED",
                writes_remaining=writes_remaining,
            )
        except Exception as e:
            logger.error(f"[V5_BRIDGE] check_can_write failed: {e}")
            return QuotaDecision(allowed=False, reason="QUOTA_CHECK_ERROR")

    def record_read(self, reads: int = 1, reason: str = ""):
        """Record a read operation."""
        try:
            self._get_or_create_quota()
            today = self._get_today()

            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE quota_usage SET reads_used = reads_used + ? WHERE date = ?",
                (reads, today),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[V5_BRIDGE] record_read failed: {e}")

    def record_write(self, writes: int = 1, reason: str = ""):
        """Record a write operation."""
        try:
            self._get_or_create_quota()
            today = self._get_today()

            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "UPDATE quota_usage SET writes_used = writes_used + ? WHERE date = ?",
                (writes, today),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[V5_BRIDGE] record_write failed: {e}")

    def check_entry_allowed(
        self, open_global: int, open_for_symbol: int, estimated_lifecycle_writes: int = 5
    ) -> QuotaDecision:
        """
        Check if new PAPER entry is allowed based on quota reserves.

        Rules:
        - Block if remaining writes < (close_reserve + lifecycle_writes + emergency_reserve)
        - Allow closes to proceed (they can be outboxed)

        Args:
            open_global: Current global open positions
            open_for_symbol: Current open positions for this symbol
            estimated_lifecycle_writes: Estimated writes for open+close lifecycle (default 5)

        Returns:
            QuotaDecision with allowed flag and remaining quota
        """
        try:
            # Check symbol limit
            if open_for_symbol >= config.MAX_OPEN_PER_SYMBOL:
                return QuotaDecision(
                    allowed=False,
                    reason=f"MAX_OPEN_PER_SYMBOL_{config.MAX_OPEN_PER_SYMBOL}",
                )

            # Check global limit
            if open_global >= config.MAX_OPEN_GLOBAL:
                return QuotaDecision(
                    allowed=False,
                    reason=f"MAX_OPEN_GLOBAL_{config.MAX_OPEN_GLOBAL}",
                )

            # Check write quota with reserves
            decision = self.check_can_write(1)
            if not decision.allowed:
                return decision

            # Calculate required reserves
            close_reserve = config.QUOTA_CLOSE_RESERVE  # For closing existing positions
            lifecycle_reserve = estimated_lifecycle_writes  # For new entry lifecycle
            emergency_reserve = config.QUOTA_EMERGENCY_RESERVE

            total_reserve = close_reserve + lifecycle_reserve + emergency_reserve

            writes_remaining = decision.writes_remaining
            if writes_remaining < total_reserve:
                logger.warning(
                    f"[V5_BRIDGE_QUOTA_BLOCK] remaining={writes_remaining} "
                    f"required_reserve={total_reserve} reason=QUOTA_CLOSE_RESERVE"
                )
                return QuotaDecision(
                    allowed=False,
                    reason="QUOTA_CLOSE_RESERVE",
                    writes_remaining=writes_remaining,
                )

            return QuotaDecision(
                allowed=True,
                writes_remaining=writes_remaining - total_reserve,
            )

        except Exception as e:
            logger.error(f"[V5_BRIDGE] check_entry_allowed failed: {e}")
            return QuotaDecision(allowed=False, reason="QUOTA_CHECK_ERROR")

    def snapshot(self) -> dict:
        """Get current quota snapshot."""
        try:
            self._get_or_create_quota()
            today = self._get_today()

            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                "SELECT reads_used, writes_used, state FROM quota_usage WHERE date = ?",
                (today,),
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                reads_used, writes_used, state = row
            else:
                reads_used, writes_used, state = 0, 0, "normal"

            return {
                "date": today,
                "internal_reads_cap": self.reads_cap,
                "internal_writes_cap": self.writes_cap,
                "reads_used": reads_used,
                "writes_used": writes_used,
                "reads_remaining": max(0, self.reads_cap - reads_used),
                "writes_remaining": max(0, self.writes_cap - writes_used),
                "state": state,
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"[V5_BRIDGE] snapshot failed: {e}")
            return {"state": "error", "error": str(e)}

    def reads_remaining(self) -> int:
        """Get reads remaining today."""
        snap = self.snapshot()
        return snap.get("reads_remaining", 0)

    def writes_remaining(self) -> int:
        """Get writes remaining today."""
        snap = self.snapshot()
        return snap.get("writes_remaining", 0)

    def get_state(self) -> str:
        """Get current quota state."""
        snap = self.snapshot()
        return snap.get("state", "unknown")
