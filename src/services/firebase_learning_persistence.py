"""Firebase Persistence Layer for Adaptive Learning System

PHASE 1 SIMPLIFIED APPROACH:
- Primary: Local JSON file (reliable, fast, no quota cost)
- Secondary: Async Firebase backup (eventual consistency, quota-safe)
- No cold-start metrics reset due to persistent local state

Eliminates the "metrics reset on restart" problem by maintaining local persistence.
"""

import json
import logging
import time
import threading
import os
from typing import Optional, Dict, Any
from datetime import datetime

log = logging.getLogger(__name__)

# Async Firebase sync thread (background, non-blocking)
_firebase_sync_thread = None
_firebase_sync_queue = []
_firebase_sync_lock = threading.Lock()


def _async_firebase_sync():
    """Background thread to sync learning state to Firebase (best effort)."""
    try:
        from src.services.firebase_client import save_batch
    except ImportError:
        log.warning("[LEARNING_FIREBASE] Firebase not available for async sync")
        return

    while True:
        time.sleep(300)  # Every 5 minutes
        with _firebase_sync_lock:
            if not _firebase_sync_queue:
                continue

            data = _firebase_sync_queue.pop(0)
            try:
                # Save learning state as a "document" in Firebase
                batch = [{
                    "collection": "learning_state",
                    "doc_id": "regime_tp_strategy",
                    "data": data,
                    "timestamp": time.time()
                }]
                save_batch(batch)
                log.info("[LEARNING_FIREBASE_SYNC] Async Firebase sync completed")
            except Exception as e:
                log.warning(f"[LEARNING_FIREBASE_SYNC_ERROR] {e}")
                # Put it back in queue for retry
                with _firebase_sync_lock:
                    _firebase_sync_queue.insert(0, data)


def start_async_firebase_sync():
    """Start background Firebase sync thread."""
    global _firebase_sync_thread
    if not _firebase_sync_thread:
        _firebase_sync_thread = threading.Thread(target=_async_firebase_sync, daemon=True)
        _firebase_sync_thread.start()
        log.info("[LEARNING_FIREBASE] Async sync thread started")


class FirebaseLearningPersistence:
    """Simplified learning persistence: Local JSON + async Firebase backup."""

    def __init__(self, state_file: str = "server_local_backups/learning_state_phase1.json"):
        self.state_file = state_file
        self.last_save_ts = 0
        start_async_firebase_sync()

    def save_learning_state(self, learning_obj: Dict[str, Any]) -> bool:
        """Save learning state to local JSON (fast, reliable).

        Also queue for async Firebase sync (best effort).
        """
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)

            # Prepare data in Firebase-compatible format
            data = {
                "timestamp": datetime.utcnow().isoformat(),
                "schema_version": 1,
                "lifetime_metrics": learning_obj.get("lifetime_metrics", {}),
                "regime_tp_strategy": learning_obj.get("regime_tp_strategy", {}),
                "rolling_windows": learning_obj.get("rolling_windows", {}),
            }

            # Save to local JSON (synchronous, guaranteed)
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)

            self.last_save_ts = time.time()

            # Queue for async Firebase sync (best effort, non-blocking)
            with _firebase_sync_lock:
                _firebase_sync_queue.append(data)

            lifetime = learning_obj.get("lifetime_metrics", {})
            log.info(f"[LEARNING_PERSIST] Saved: {lifetime.get('trades_closed', 0)} trades, "
                    f"PF {lifetime.get('profit_factor', 0):.2f}x")
            return True

        except Exception as e:
            log.error(f"[LEARNING_PERSIST_ERROR] {str(e)}")
            return False

    def load_learning_state(self) -> Optional[Dict[str, Any]]:
        """Load learning state from local JSON (fast, reliable)."""
        try:
            if not os.path.exists(self.state_file):
                log.info("[LEARNING_LOAD] No prior learning state found")
                return None

            with open(self.state_file, 'r') as f:
                data = json.load(f)

            # Validate age (< 24 hours)
            ts_str = data.get("timestamp", "")
            if ts_str and not self._is_recent(ts_str):
                log.warning("[LEARNING_LOAD] State is stale (>24h)")
                return None

            # Validate min data (at least 20 trades)
            lifetime = data.get("lifetime_metrics", {})
            if lifetime.get("trades_closed", 0) < 20:
                log.info(f"[LEARNING_LOAD] Insufficient data ({lifetime.get('trades_closed', 0)} trades)")
                return None

            log.info(f"[LEARNING_LOAD] Restored: {lifetime.get('trades_closed', 0)} trades, "
                    f"PF {lifetime.get('profit_factor', 0):.2f}x")
            return data

        except Exception as e:
            log.error(f"[LEARNING_LOAD_ERROR] {str(e)}")
            return None

    def validate_regime_tp_strategy(self, regime_tp: Dict) -> bool:
        """Validate learned TP values before using them."""
        COST_FLOOR_BPS = 0.18
        MAX_TP_BPS = 1.0
        MIN_CLOSES = 20

        for regime, vol_bands in regime_tp.items():
            for vol_band, data in vol_bands.items():
                tp_pct = data.get("tp_pct", 0)
                closes = data.get("n", 0)
                wr = data.get("wr", 0)

                tp_bps = tp_pct * 100

                if tp_bps < COST_FLOOR_BPS or tp_bps > MAX_TP_BPS or closes < MIN_CLOSES:
                    log.warning(f"[VALIDATE_TP] {regime}/{vol_band} validation failed: "
                               f"tp_bps={tp_bps:.1f}, n={closes}, wr={wr:.2f}")
                    return False

        log.info("[VALIDATE_TP] All learned TP values passed validation")
        return True

    def _is_recent(self, timestamp_str: str) -> bool:
        """Check if timestamp is within 24 hours."""
        try:
            ts = datetime.fromisoformat(timestamp_str)
            age_hours = (datetime.utcnow() - ts).total_seconds() / 3600
            return age_hours < 24
        except Exception:
            return False


# Singleton instance
_persistence = FirebaseLearningPersistence()

def save_learning(learning_obj: Dict[str, Any]) -> bool:
    return _persistence.save_learning_state(learning_obj)

def load_learning() -> Optional[Dict[str, Any]]:
    return _persistence.load_learning_state()

def validate_learned_tp(regime_tp: Dict) -> bool:
    return _persistence.validate_regime_tp_strategy(regime_tp)

# Placeholder for removed functions (backward compat)
def learning_heartbeat() -> bool:
    return True
