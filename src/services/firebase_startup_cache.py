"""
V10.22: Firebase startup bootstrap cache

Solves the 5300+ read startup spike by:
1. Saving trade history to local JSON after Firebase load
2. Loading from JSON on next startup (0 Firebase reads)
3. Syncing only new trades incrementally

Usage:
  from src.services.firebase_startup_cache import (
      load_history_with_cache, save_history_cache,
      get_last_cached_trade_ts
  )

  # At startup in bot2/main.py:
  _history = load_history_with_cache()  # 0 reads if cache exists
"""

import json
import os
import logging
import time
from typing import Optional, List

_log = logging.getLogger(__name__)

STARTUP_CACHE_PATH = "runtime/firebase_startup_cache.json"
STARTUP_CACHE_MAX_TRADES = 2000  # Cache last 2000 trades


def _ensure_cache_dir():
    """Create runtime directory if needed."""
    os.makedirs("runtime", exist_ok=True)


def get_last_cached_trade_ts() -> Optional[float]:
    """
    Get timestamp of newest trade in cache file.

    Returns:
        float: Unix timestamp of last trade, or None if no cache
    """
    _ensure_cache_dir()

    if not os.path.exists(STARTUP_CACHE_PATH):
        return None

    try:
        with open(STARTUP_CACHE_PATH, 'r') as f:
            data = json.load(f)
            if data.get('trades'):
                # Trades are in desc order (newest first)
                newest = data['trades'][0]
                return newest.get('entry_ts') or newest.get('open_ts')
    except Exception as e:
        _log.warning(f"[STARTUP_CACHE] Failed to read cache: {e}")

    return None


def load_history_with_cache(limit: int = 2000) -> Optional[List[dict]]:
    """
    Load trade history from startup cache (fast: 0 Firebase reads).

    Returns:
        list: Trades from cache, or None if load failed
    """
    _ensure_cache_dir()

    if not os.path.exists(STARTUP_CACHE_PATH):
        _log.info(f"[STARTUP_CACHE] No cache found at {STARTUP_CACHE_PATH}")
        return None

    try:
        with open(STARTUP_CACHE_PATH, 'r') as f:
            data = json.load(f)
            trades = data.get('trades', [])
            _log.info(
                f"[STARTUP_CACHE] Loaded {len(trades)} trades from cache "
                f"(cache_ts={data.get('saved_at')}, "
                f"newest_trade_ts={trades[0].get('entry_ts') if trades else 'N/A'})"
            )
            return list(trades[:limit])
    except Exception as e:
        _log.warning(f"[STARTUP_CACHE] Failed to load cache: {e}")
        return None


def save_history_cache(trades: List[dict], source: str = "firebase"):
    """
    Save trade history to startup cache for next restart.

    Args:
        trades: List of trade dicts to cache
        source: Where trades came from (firebase, incremental, etc.)
    """
    _ensure_cache_dir()

    try:
        data = {
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "source": source,
            "trade_count": len(trades),
            "first_trade_ts": trades[-1].get('entry_ts') if trades else None,
            "last_trade_ts": trades[0].get('entry_ts') if trades else None,
            "trades": trades[:STARTUP_CACHE_MAX_TRADES],  # Cache last N trades
        }

        with open(STARTUP_CACHE_PATH, 'w') as f:
            json.dump(data, f, indent=2)

        _log.info(
            f"[STARTUP_CACHE] Saved {len(trades)} trades to {STARTUP_CACHE_PATH} "
            f"(source={source})"
        )
    except Exception as e:
        _log.warning(f"[STARTUP_CACHE] Failed to save cache: {e}")


def clear_cache():
    """Clear startup cache (for testing or manual reset)."""
    _ensure_cache_dir()
    if os.path.exists(STARTUP_CACHE_PATH):
        os.remove(STARTUP_CACHE_PATH)
        _log.info(f"[STARTUP_CACHE] Cleared {STARTUP_CACHE_PATH}")
