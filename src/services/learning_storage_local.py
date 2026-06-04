"""
V10.15 LOCAL LEARNING STORAGE — Firebase-bypass for learning persistence

Problem: Firebase writes exceeded quota (20,833/20,000), learning data not persisting
Solution: Use local SQLite + JSON for learning state, async Firebase for backup

Data flow:
  trade_closed → learning_event → LOCAL storage ← (1ms, no quota impact)
                                 → Firebase async → (deferred, no blocking)
"""

import json
import sqlite3
import threading
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger(__name__)

# Local storage paths
DB_PATH = Path("/opt/cryptomaster/runtime/learning.db")
JSON_PATH = Path("/opt/cryptomaster/runtime/learning_state.json")

_lock = threading.Lock()
_initialized = False


def init_storage():
    """Initialize local learning database."""
    global _initialized
    if _initialized:
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_metrics (
                id INTEGER PRIMARY KEY,
                timestamp REAL,
                trades INTEGER,
                wins INTEGER,
                losses INTEGER,
                profit REAL,
                pf REAL,
                health REAL,
                data JSON
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at REAL
            )
        """)
        conn.commit()
        conn.close()
        log.info("[LEARNING_STORAGE] Local SQLite initialized")
        _initialized = True
    except Exception as e:
        log.error(f"[LEARNING_STORAGE] Init failed: {e}")


def save_metrics(metrics_dict: dict) -> bool:
    """Save metrics to local storage (fast, no quota impact)."""
    if not _initialized:
        init_storage()

    try:
        with _lock:
            conn = sqlite3.connect(str(DB_PATH))

            # Extract key metrics
            trades = metrics_dict.get("trades", 0)
            wins = metrics_dict.get("wins", 0)
            losses = metrics_dict.get("losses", 0)
            profit = metrics_dict.get("profit", 0.0)
            pf = metrics_dict.get("pf", 0.0)
            health = metrics_dict.get("health", 0.0)

            conn.execute("""
                INSERT INTO learning_metrics
                (timestamp, trades, wins, losses, profit, pf, health, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().timestamp(),
                trades, wins, losses, profit, pf, health,
                json.dumps(metrics_dict)
            ))

            # Keep only last 1000 records
            conn.execute("""
                DELETE FROM learning_metrics
                WHERE id NOT IN (
                    SELECT id FROM learning_metrics
                    ORDER BY id DESC LIMIT 1000
                )
            """)

            conn.commit()
            conn.close()

            # Also save JSON snapshot
            with open(JSON_PATH, 'w') as f:
                json.dump({
                    "timestamp": datetime.utcnow().isoformat(),
                    "metrics": metrics_dict
                }, f)

            return True
    except Exception as e:
        log.warning(f"[LEARNING_STORAGE] Save failed: {e}")
        return False


def load_latest_metrics() -> dict:
    """Load latest metrics from local storage."""
    if not _initialized:
        init_storage()

    try:
        # Try JSON first (most recent)
        if JSON_PATH.exists():
            with open(JSON_PATH) as f:
                data = json.load(f)
                return data.get("metrics", {})

        # Fallback to SQLite
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute("""
            SELECT data FROM learning_metrics
            ORDER BY id DESC LIMIT 1
        """).fetchone()
        conn.close()

        if row:
            return json.loads(row['data'])
    except Exception as e:
        log.warning(f"[LEARNING_STORAGE] Load failed: {e}")

    return {}


def get_learning_history(limit: int = 100) -> list:
    """Get historical learning metrics (for analysis)."""
    if not _initialized:
        init_storage()

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT timestamp, trades, wins, losses, profit, pf, health
            FROM learning_metrics
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        conn.close()

        return [
            {
                "timestamp": row['timestamp'],
                "trades": row['trades'],
                "wins": row['wins'],
                "losses": row['losses'],
                "profit": row['profit'],
                "pf": row['pf'],
                "health": row['health']
            }
            for row in reversed(rows)
        ]
    except Exception as e:
        log.warning(f"[LEARNING_STORAGE] History load failed: {e}")
        return []


def async_backup_to_firebase():
    """Background task: backup to Firebase without blocking (deferred)."""
    try:
        from src.services.firebase_client import save_batch

        metrics = load_latest_metrics()
        if metrics:
            # Send as async batch (no quota impact if fails)
            save_batch([{
                "type": "learning_state",
                "data": metrics,
                "timestamp": datetime.utcnow().isoformat()
            }])
            log.debug("[LEARNING_STORAGE] Firebase backup sent")
    except Exception as e:
        log.debug(f"[LEARNING_STORAGE] Firebase backup skipped (OK): {e}")


# Auto-init
init_storage()
log.info("[LEARNING_STORAGE] V10.15 local learning storage ready (Firebase-bypass)")
