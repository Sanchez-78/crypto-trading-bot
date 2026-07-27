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
    """Move the newest checkpoint into the durable archive outbox."""
    try:
        from src.services.learning_archive import (
            archive_learning_event,
            flush_learning_archive,
        )
    except ImportError:
        log.warning("[LEARNING_ARCHIVE] durable archive not available")
        return

    while True:
        time.sleep(300)  # Every 5 minutes
        with _firebase_sync_lock:
            if not _firebase_sync_queue:
                continue
            data = _firebase_sync_queue[-1]
        try:
            appended = archive_learning_event(
                "adaptive_learning_checkpoint",
                data,
            )
            if not (
                appended.get("accepted")
                or appended.get("duplicate")
            ):
                log.warning(
                    "[LEARNING_ARCHIVE_SYNC_REJECTED] reason=%s",
                    appended.get("reason"),
                )
                continue
            with _firebase_sync_lock:
                if _firebase_sync_queue and _firebase_sync_queue[-1] is data:
                    _firebase_sync_queue.clear()
            flush_result = flush_learning_archive(limit=50)
            log.info(
                "[LEARNING_ARCHIVE_SYNC] checkpoint durable flush=%s pending=%s",
                flush_result.get("flush"),
                flush_result.get("pending_events"),
            )
        except Exception as e:
            # The SQLite outbox retains an appended event across remote errors.
            log.warning("[LEARNING_ARCHIVE_SYNC_ERROR] %s", e)


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
            data = dict(learning_obj or {})
            data["timestamp"] = datetime.utcnow().isoformat()
            data["schema_version"] = 2

            # Atomic local checkpoint remains the fast startup source.
            temp_file = (
                f"{self.state_file}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, self.state_file)

            self.last_save_ts = time.time()

            # Bound memory to one superseding snapshot.
            with _firebase_sync_lock:
                _firebase_sync_queue.clear()
                _firebase_sync_queue.append(data)

            lifetime = learning_obj.get("lifetime_metrics", {})
            log.info(f"[LEARNING_PERSIST] Saved: {lifetime.get('trades_closed', 0)} trades, "
                    f"PF {lifetime.get('profit_factor', 0):.2f}x")
            return True

        except Exception as e:
            log.error(f"[LEARNING_PERSIST_ERROR] {str(e)}")
            return False

    def load_learning_state(self) -> Optional[Dict[str, Any]]:
        """Load local checkpoint, then bounded archive/Firebase fallback."""
        try:
            if not os.path.exists(self.state_file):
                return self._load_archive_checkpoint()

            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate age (< 24 hours)
            ts_str = data.get("timestamp", "")
            if ts_str and not self._is_recent(ts_str):
                log.warning("[LEARNING_LOAD] State is stale (>24h)")
                return self._load_archive_checkpoint()

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
            return self._load_archive_checkpoint()

    def _load_archive_checkpoint(self) -> Optional[Dict[str, Any]]:
        try:
            from src.services.learning_archive import get_learning_archive

            archive = get_learning_archive()
            hydrate_limit = min(
                max(int(os.getenv("FIREBASE_LEARNING_ARCHIVE_HYDRATE_LIMIT", "2000")), 100),
                5000,
            )
            archive.hydrate(limit=hydrate_limit)
            rows = archive.recent("adaptive_learning_checkpoint", limit=1)
            if not rows:
                log.info("[LEARNING_LOAD] No archived checkpoint found")
                return None
            data = rows[0].get("payload") or {}
            lifetime = data.get("lifetime_metrics", {})
            if int(lifetime.get("trades_closed", 0) or 0) < 20:
                log.info("[LEARNING_LOAD] Archived checkpoint has insufficient data")
                return None
            log.info(
                "[LEARNING_LOAD] Restored archived checkpoint: %s trades",
                lifetime.get("trades_closed", 0),
            )
            return data
        except Exception as exc:
            log.warning("[LEARNING_ARCHIVE_LOAD_ERROR] %s", exc)
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
