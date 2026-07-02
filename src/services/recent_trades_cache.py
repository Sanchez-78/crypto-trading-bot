#!/usr/bin/env python3
"""
Recent Trades Cache - Real-time trade logging for dashboard

Maintains a JSON cache of the 30 most recent closed trades.
Gets updated by trade_executor.py whenever a trade closes.
Dashboard reads from this cache instead of trying to parse logs.

This ensures the dashboard ALWAYS shows fresh trade data.
"""

import json
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional

CACHE_PATH = "/opt/cryptomaster/runtime/recent_trades_cache.json"
MAX_TRADES = 30

# Thread-safe access
_lock = threading.Lock()


def ensure_cache_exists():
    """Create cache file if it doesn't exist."""
    Path(CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
    if not Path(CACHE_PATH).exists():
        with open(CACHE_PATH, 'w') as f:
            json.dump([], f)


def add_closed_trade(trade_data: Dict[str, Any]) -> bool:
    """
    Add a closed trade to the recent trades cache.
    Called by trade_executor.py when a trade closes.

    Args:
        trade_data: Dictionary with trade info:
            - trade_id (str)
            - symbol (str)
            - side (str): BUY or SELL
            - entry_price (float)
            - exit_price (float)
            - pnl_pct (float)
            - pnl_usd (float)
            - exit_reason (str)
            - hold_s (int)
            - exit_timestamp (str, ISO8601)
    """
    try:
        with _lock:
            ensure_cache_exists()

            # Read existing trades
            try:
                with open(CACHE_PATH, 'r') as f:
                    trades = json.load(f)
            except:
                trades = []

            # Add new trade to front
            trades.insert(0, {
                'trade_id': trade_data.get('trade_id', ''),
                'symbol': trade_data.get('symbol', ''),
                'side': trade_data.get('side', 'BUY'),
                'entry_price': float(trade_data.get('entry_price', 0)),
                'exit_price': float(trade_data.get('exit_price', 0)),
                'pnl_pct': float(trade_data.get('pnl_pct', 0)),
                'pnl_usd': float(trade_data.get('pnl_usd', 0)),
                'exit_reason': trade_data.get('exit_reason', 'UNKNOWN'),
                'hold_s': int(trade_data.get('hold_s', 0)),
                'exit_timestamp': trade_data.get('exit_timestamp', datetime.now(timezone.utc).isoformat()),
                'entry_timestamp': trade_data.get('entry_timestamp', ''),
            })

            # Keep only last 30 trades
            trades = trades[:MAX_TRADES]

            # Write back
            with open(CACHE_PATH, 'w') as f:
                json.dump(trades, f, indent=2)

            return True
    except Exception as e:
        print(f"[CACHE] Error adding trade: {e}")
        return False


def get_recent_trades(limit: int = 30) -> list:
    """Get the N most recent closed trades."""
    try:
        with _lock:
            ensure_cache_exists()
            with open(CACHE_PATH, 'r') as f:
                trades = json.load(f)
            return trades[:limit]
    except:
        return []


def clear_cache():
    """Clear the cache (useful for testing)."""
    try:
        with _lock:
            with open(CACHE_PATH, 'w') as f:
                json.dump([], f)
            return True
    except:
        return False


if __name__ == "__main__":
    # Test
    ensure_cache_exists()
    trades = get_recent_trades()
    print(f"Recent trades cache: {len(trades)} trades")
