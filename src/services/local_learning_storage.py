"""
CryptoMaster Local Learning Storage
Purpose: Replace Firebase for learning/metrics (unlimited reads, zero quota cost)
Status: ✅ PRODUCTION

Architecture:
- Local SQLite database on network share (\\MYCLOUD-G07Y2M\Public\Cryptomaster)
- Trades stored locally (instant writes, no Firebase latency)
- Learning metrics computed locally (no Firebase reads)
- Optional background sync to Firebase (1x/hour batch)
"""

import sqlite3
import time
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import contextmanager
from threading import Lock
import json

log = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Try to detect network share path
NETWORK_PATHS = [
    r"\\MYCLOUD-G07Y2M\Public\Cryptomaster",  # Windows UNC path
    "/mnt/cryptomaster",  # Linux mount point (if mounted)
    "/opt/cryptomaster/network_cache",  # Local fallback (Hetzner)
]

# Determine active path
STORAGE_PATH = None
for path in NETWORK_PATHS:
    if Path(path).exists():
        STORAGE_PATH = Path(path)
        log.info(f"[LOCAL_STORAGE] Found storage at: {STORAGE_PATH}")
        break

if not STORAGE_PATH:
    # Fallback: create local directory
    STORAGE_PATH = Path("/opt/cryptomaster/local_learning_storage")
    STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    log.warning(f"[LOCAL_STORAGE] Network share unavailable, using local fallback: {STORAGE_PATH}")

DB_PATH = STORAGE_PATH / "learning_database.sqlite"
BACKUP_DIR = STORAGE_PATH / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

# Connection pooling
DB_TIMEOUT = 5.0  # seconds
DB_PRAGMA = {
    "journal_mode": "WAL",
    "synchronous": "NORMAL",
    "cache_size": "10000",
    "temp_store": "MEMORY",
}

# ============================================================================
# LOCAL LEARNING STORAGE CLASS
# ============================================================================

class LocalLearningStorage:
    """SQLite-based learning storage (replaces Firebase for learning data)"""

    def __init__(self):
        self.db_path = str(DB_PATH)
        self.lock = Lock()
        self._init_db()
        log.info(f"[LOCAL_STORAGE] Initialized at {self.db_path}")

    def _init_db(self):
        """Initialize database and create schema"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)

            # Apply PRAGMAs
            for key, value in DB_PRAGMA.items():
                conn.execute(f"PRAGMA {key} = {value}")

            # Create trades table (V10.15l: Inline schema instead of schema.sql)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    side TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    entry_ts REAL,
                    exit_ts REAL,
                    pnl_pct REAL,
                    pnl_usd REAL,
                    mfe_pct REAL,
                    mae_pct REAL,
                    exit_reason TEXT,
                    regime TEXT,
                    size_usd REAL,
                    cost_edge_ok INTEGER,
                    learning_source TEXT,
                    synced INTEGER DEFAULT 0,
                    created_at REAL,
                    mode TEXT DEFAULT 'PAPER',
                    trade_environment TEXT DEFAULT 'paper_train'
                )
            ''')

            # Create indices for common queries
            conn.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_trades_exit_ts ON trades(exit_ts)')

            # Load schema from file (if exists)
            schema_path = Path(__file__).parent.parent.parent / "schema.sql"
            if schema_path.exists():
                with open(schema_path) as f:
                    conn.executescript(f.read())

            conn.commit()
            conn.close()
            log.info("[LOCAL_STORAGE] Database initialized with trades table")
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to init DB: {e}")
            raise

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ========================================================================
    # TRADE RECORDING
    # ========================================================================

    def record_trade_close(self, trade_dict: Dict[str, Any]) -> bool:
        """
        Record a closed paper trade to local storage

        Args:
            trade_dict: {
                'trade_id': str,
                'symbol': str,
                'side': str,  # BUY/SELL
                'entry_price': float,
                'exit_price': float,
                'entry_ts': int,
                'exit_ts': int,
                'pnl_pct': float,
                'pnl_usd': float,
                'mfe_pct': float,  # optional
                'mae_pct': float,  # optional
                'exit_reason': str,  # TP/SL/timeout/stagnation
                'regime': str,  # BULL_TREND/BEAR_TREND/NEUTRAL
                'size_usd': float,
                'cost_edge_ok': bool,
                'learning_source': str,  # optional
            }

        Returns:
            True if successful, False if failed
        """
        try:
            with self.lock:
                with self._get_connection() as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO trades (
                            trade_id, symbol, side, entry_price, exit_price,
                            entry_ts, exit_ts, pnl_pct, pnl_usd, mfe_pct, mae_pct,
                            exit_reason, regime, size_usd, cost_edge_ok, learning_source,
                            synced, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """, (
                        trade_dict['trade_id'],
                        trade_dict['symbol'],
                        trade_dict['side'],
                        trade_dict['entry_price'],
                        trade_dict['exit_price'],
                        trade_dict['entry_ts'],
                        trade_dict['exit_ts'],
                        trade_dict.get('pnl_pct', 0.0),
                        trade_dict.get('pnl_usd', 0.0),
                        trade_dict.get('mfe_pct', 0.0),
                        trade_dict.get('mae_pct', 0.0),
                        trade_dict.get('exit_reason', 'unknown'),
                        trade_dict.get('regime', 'NEUTRAL'),
                        trade_dict.get('size_usd', 0.0),
                        int(trade_dict.get('cost_edge_ok', False)),
                        trade_dict.get('learning_source', 'paper'),
                        int(time.time()),
                    ))
                    conn.commit()

            log.info(
                f"[LOCAL_TRADE_RECORDED] trade_id={trade_dict['trade_id']} "
                f"symbol={trade_dict['symbol']} pnl_pct={trade_dict.get('pnl_pct', 0):.4f}"
            )
            return True
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to record trade: {e}")
            return False

    # ========================================================================
    # LEARNING METRICS
    # ========================================================================

    def get_learning_metrics(self, symbol: str) -> Dict[str, float]:
        """
        Get learning metrics for a symbol (INSTANT, NO FIREBASE READ!)

        Returns:
            {
                'closed_trades': int,
                'profit_factor': float,
                'win_rate': float,
                'expectancy': float,
                'pnl_total': float,
            }
        """
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM learning_metrics WHERE symbol = ?",
                    (symbol,)
                ).fetchone()

                if row:
                    return {
                        'closed_trades': row['closed_trades'],
                        'profit_factor': row['profit_factor'] or 0.0,
                        'win_rate': row['win_rate'] or 0.0,
                        'expectancy': row['expectancy'] or 0.0,
                        'pnl_total': row['pnl_total'] or 0.0,
                    }
                else:
                    return {
                        'closed_trades': 0,
                        'profit_factor': 0.0,
                        'win_rate': 0.0,
                        'expectancy': 0.0,
                        'pnl_total': 0.0,
                    }
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to get metrics for {symbol}: {e}")
            return {}

    def get_all_metrics(self) -> Dict[str, Dict[str, float]]:
        """Get metrics for ALL symbols"""
        try:
            with self._get_connection() as conn:
                rows = conn.execute("SELECT * FROM learning_metrics").fetchall()
                return {
                    row['symbol']: {
                        'closed_trades': row['closed_trades'],
                        'profit_factor': row['profit_factor'] or 0.0,
                        'win_rate': row['win_rate'] or 0.0,
                        'expectancy': row['expectancy'] or 0.0,
                        'pnl_total': row['pnl_total'] or 0.0,
                    }
                    for row in rows
                }
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to get all metrics: {e}")
            return {}

    # ========================================================================
    # CALIBRATION STATE
    # ========================================================================

    def update_calibration(self, symbol: str, regime: str, side: str, result: str):
        """
        Update calibration state (W/L) for learning

        Args:
            symbol: e.g. 'BTCUSDT'
            regime: 'BULL_TREND' / 'BEAR_TREND' / 'NEUTRAL'
            side: 'BUY' / 'SELL'
            result: 'WIN' / 'LOSS' / 'BREAKEVEN'
        """
        try:
            with self.lock:
                with self._get_connection() as conn:
                    # Get current state
                    row = conn.execute(
                        "SELECT * FROM calibration_state WHERE symbol=? AND regime=? AND side=?",
                        (symbol, regime, side)
                    ).fetchone()

                    if row:
                        win_count = row['win_count'] + (1 if result == 'WIN' else 0)
                        loss_count = row['loss_count'] + (1 if result == 'LOSS' else 0)
                        sample_size = row['sample_size'] + 1
                    else:
                        win_count = 1 if result == 'WIN' else 0
                        loss_count = 1 if result == 'LOSS' else 0
                        sample_size = 1

                    # Calculate confidence (based on sample size)
                    confidence = min(sample_size / 50.0, 1.0)  # max 50 trades for 100% confidence

                    # Update
                    conn.execute("""
                        INSERT OR REPLACE INTO calibration_state
                        (symbol, regime, side, win_count, loss_count, sample_size, model_confidence, last_update)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        symbol, regime, side, win_count, loss_count, sample_size, confidence,
                        int(time.time())
                    ))
                    conn.commit()
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to update calibration: {e}")

    def get_calibration(self, symbol: str, regime: str, side: str) -> Optional[Dict]:
        """Get calibration state for segment"""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM calibration_state WHERE symbol=? AND regime=? AND side=?",
                    (symbol, regime, side)
                ).fetchone()

                if row:
                    return {
                        'win_count': row['win_count'],
                        'loss_count': row['loss_count'],
                        'win_rate': row['win_count'] / max(row['sample_size'], 1),
                        'model_confidence': row['model_confidence'],
                        'sample_size': row['sample_size'],
                    }
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to get calibration: {e}")

        return None

    # ========================================================================
    # HEALTH MONITORING
    # ========================================================================

    def record_health_status(self, health_dict: Dict[str, Any]) -> bool:
        """Record bot health snapshot"""
        try:
            with self.lock:
                with self._get_connection() as conn:
                    conn.execute("""
                        INSERT INTO health_status
                        (timestamp, open_positions, closed_today, profit_factor, net_pnl,
                         firebase_quota_used, learning_updates, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        int(time.time()),
                        health_dict.get('open_positions', 0),
                        health_dict.get('closed_today', 0),
                        health_dict.get('profit_factor', 0.0),
                        health_dict.get('net_pnl', 0.0),
                        health_dict.get('firebase_quota_used', 0),
                        health_dict.get('learning_updates', 0),
                        health_dict.get('status', 'normal'),
                    ))
                    conn.commit()
            return True
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to record health: {e}")
            return False

    # ========================================================================
    # ANALYTICS & REPORTING
    # ========================================================================

    def get_recent_trades(self, symbol: Optional[str] = None, hours: int = 24) -> List[Dict]:
        """Get recent closed trades"""
        try:
            with self._get_connection() as conn:
                cutoff_ts = int(time.time()) - (hours * 3600)

                if symbol:
                    rows = conn.execute(
                        "SELECT * FROM trades WHERE symbol=? AND exit_ts > ? ORDER BY exit_ts DESC",
                        (symbol, cutoff_ts)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM trades WHERE exit_ts > ? ORDER BY exit_ts DESC",
                        (cutoff_ts,)
                    ).fetchall()

                return [dict(row) for row in rows]
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to get recent trades: {e}")
            return []

    def get_exit_distribution(self) -> Dict[str, int]:
        """Get distribution of exit reasons"""
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT exit_reason, COUNT(*) as count FROM trades GROUP BY exit_reason"
                ).fetchall()
                return {row['exit_reason']: row['count'] for row in rows}
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to get exit distribution: {e}")
            return {}

    # ========================================================================
    # BACKUP & MAINTENANCE
    # ========================================================================

    def create_backup(self) -> bool:
        """Create hourly backup of database"""
        try:
            import shutil
            from datetime import datetime

            timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
            backup_path = BACKUP_DIR / f"learning_db_{timestamp}.sqlite"

            # Copy database file
            shutil.copy2(self.db_path, str(backup_path))

            # Keep only last 24 hourly backups
            backups = sorted(BACKUP_DIR.glob("learning_db_*.sqlite"))
            for old_backup in backups[:-24]:
                old_backup.unlink()

            log.info(f"[LOCAL_STORAGE] Backup created: {backup_path}")
            return True
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Backup failed: {e}")
            return False

    def get_db_size(self) -> int:
        """Get database file size in bytes"""
        try:
            return os.path.getsize(self.db_path)
        except:
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics"""
        try:
            with self._get_connection() as conn:
                trade_count = conn.execute("SELECT COUNT(*) as cnt FROM trades").fetchone()['cnt']
                symbol_count = conn.execute("SELECT COUNT(*) as cnt FROM learning_metrics").fetchone()['cnt']

                return {
                    'db_path': str(self.db_path),
                    'db_size_mb': self.get_db_size() / (1024 * 1024),
                    'total_trades': trade_count,
                    'tracked_symbols': symbol_count,
                    'available': True,
                }
        except Exception as e:
            log.error(f"[LOCAL_STORAGE_ERROR] Failed to get stats: {e}")
            return {'available': False, 'error': str(e)}


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_storage_instance = None

def get_storage() -> LocalLearningStorage:
    """Get global storage instance (singleton)"""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = LocalLearningStorage()
    return _storage_instance
