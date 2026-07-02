#!/usr/bin/env python3
"""
Firebase Trade Hydration - Load historical trades on startup

Populates the SQLite trades table and recent_trades_cache from Firebase
when the bot starts, ensuring metrics are accurate and dashboard shows data.
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any


def hydrate_trades_from_firebase():
    """
    Load all historical trades from Firebase into local storage.
    Called once at bot startup to initialize metrics.
    """
    try:
        from src.services.firebase_client import db

        print("[HYDRATION] Starting Firebase trade hydration...")

        # Get all trades from Firebase
        trades_ref = db.collection('trades')
        docs = trades_ref.stream()

        loaded_count = 0
        recent_trades = []

        db_path = "/opt/cryptomaster/local_learning_storage/learning_database.sqlite"
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Create table if doesn't exist
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id TEXT UNIQUE,
                symbol TEXT,
                side TEXT,
                entry_price REAL,
                exit_price REAL,
                pnl_pct REAL,
                pnl_usd REAL,
                exit_reason TEXT,
                entry_ts REAL,
                exit_ts REAL,
                hold_s INTEGER
            )
        """)

        # Load trades from Firebase
        for doc in docs:
            try:
                trade = doc.to_dict()

                entry_ts = trade.get('entry_ts', 0)
                exit_ts = trade.get('exit_ts', 0)

                # Insert or update
                c.execute("""
                    INSERT OR IGNORE INTO trades
                    (trade_id, symbol, side, entry_price, exit_price,
                     pnl_pct, pnl_usd, exit_reason, entry_ts, exit_ts, hold_s)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade.get('trade_id', doc.id),
                    trade.get('symbol', ''),
                    trade.get('side', 'BUY'),
                    float(trade.get('entry_price', 0)),
                    float(trade.get('exit_price', 0)),
                    float(trade.get('pnl_pct', 0)),
                    float(trade.get('pnl_usd', 0)),
                    trade.get('exit_reason', 'UNKNOWN'),
                    float(entry_ts),
                    float(exit_ts),
                    int(trade.get('hold_s', 0))
                ))

                loaded_count += 1

                # Keep most recent for cache
                if len(recent_trades) < 30:
                    recent_trades.append({
                        'trade_id': trade.get('trade_id', doc.id),
                        'symbol': trade.get('symbol', ''),
                        'side': trade.get('side', 'BUY'),
                        'entry_price': float(trade.get('entry_price', 0)),
                        'exit_price': float(trade.get('exit_price', 0)),
                        'pnl_pct': float(trade.get('pnl_pct', 0)),
                        'pnl_usd': float(trade.get('pnl_usd', 0)),
                        'exit_reason': trade.get('exit_reason', 'UNKNOWN'),
                        'hold_s': int(trade.get('hold_s', 0)),
                        'exit_timestamp': datetime.fromtimestamp(
                            float(exit_ts), tz=timezone.utc
                        ).isoformat() if exit_ts else '',
                        'entry_timestamp': datetime.fromtimestamp(
                            float(entry_ts), tz=timezone.utc
                        ).isoformat() if entry_ts else '',
                    })

            except Exception as e:
                print(f"[HYDRATION] Error loading trade: {e}")
                continue

        conn.commit()
        conn.close()

        # Update recent trades cache
        cache_path = "/opt/cryptomaster/runtime/recent_trades_cache.json"
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, 'w') as f:
            json.dump(recent_trades, f, indent=2)

        print(f"[HYDRATION] ✅ Loaded {loaded_count} trades from Firebase")
        return loaded_count

    except Exception as e:
        print(f"[HYDRATION] ❌ Error: {e}")
        return 0


def get_trade_count():
    """Get current trade count from local database."""
    try:
        db_path = "/opt/cryptomaster/local_learning_storage/learning_database.sqlite"
        if not Path(db_path).exists():
            return 0

        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM trades")
        count = c.fetchone()[0]
        conn.close()
        return count
    except:
        return 0


if __name__ == "__main__":
    count = hydrate_trades_from_firebase()
    total = get_trade_count()
    print(f"Total trades in database: {total}")
