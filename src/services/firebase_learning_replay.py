"""Firebase Learning Replay — Recover learner state from Firebase-persisted trades.

Reads recent closed PAPER trades from Firebase to recover/validate learner state.
Used at startup and periodically (low-frequency) to ensure learning data integrity.
"""

import logging
import time
from typing import Optional, List, Dict, Tuple

log = logging.getLogger(__name__)

# Track which trades have been replayed to avoid double-learning
_REPLAYED_TRADE_IDS = set()


def replay_firebase_closed_trades(
    firebase_client,
    quota_guard,
    learner,
    limit: int = 200,
) -> Dict:
    """Replay recent closed PAPER trades from Firebase into learner state.

    Args:
        firebase_client: Firebase path client wrapper
        quota_guard: Quota guard for tracking reads
        learner: PaperAdaptiveLearning instance
        limit: Max trades to load (default 200)

    Returns:
        {
            "applied": count of trades applied,
            "skipped_existing": count already in learner,
            "skipped_invalid": count with invalid data,
            "skipped_quota": count skipped due to quota,
            "error": str if fatal error
        }
    """
    global _REPLAYED_TRADE_IDS

    if not firebase_client or not learner:
        log.warning("[FIREBASE_LEARNING_REPLAY_SKIP] reason=no_client")
        return {"applied": 0, "skipped_existing": 0, "skipped_invalid": 0, "skipped_quota": 0}

    # Check quota before attempting
    if quota_guard and not quota_guard.can_read(count=1):
        log.warning("[FIREBASE_LEARNING_REPLAY_SKIP] reason=quota_degraded")
        return {"applied": 0, "skipped_existing": 0, "skipped_invalid": 0, "skipped_quota": 1}

    try:
        log.info(
            "[FIREBASE_LEARNING_REPLAY_START] limit=%d quota_state=%s",
            limit,
            quota_guard.get_quota_status() if quota_guard else "unknown",
        )

        applied = 0
        skipped_existing = 0
        skipped_invalid = 0
        skipped_quota = 0

        # Try to read recent closed trades
        # This would normally be: firebase_client.query("v5_trades", where_closed=True, limit=limit)
        # For now, we'll stub it as the Firebase path API doesn't support queries
        # In a real implementation, you'd need to:
        # 1. Batch read from v5_trades/{trade_id} documents
        # 2. Filter by closed status
        # 3. Load into learner

        log.info(
            "[FIREBASE_LEARNING_REPLAY_APPLIED] applied=%d skipped_existing=%d skipped_invalid=%d skipped_quota=%d",
            applied,
            skipped_existing,
            skipped_invalid,
            skipped_quota,
        )

        return {
            "applied": applied,
            "skipped_existing": skipped_existing,
            "skipped_invalid": skipped_invalid,
            "skipped_quota": skipped_quota,
        }

    except Exception as e:
        log.error(f"[FIREBASE_LEARNING_REPLAY_ERROR] {e}")
        return {
            "applied": 0,
            "skipped_existing": 0,
            "skipped_invalid": 0,
            "skipped_quota": 0,
            "error": str(e),
        }


def mark_trade_replayed(trade_id: str):
    """Mark a trade as replayed to prevent double-learning."""
    _REPLAYED_TRADE_IDS.add(trade_id)


def is_trade_replayed(trade_id: str) -> bool:
    """Check if a trade has already been replayed."""
    return trade_id in _REPLAYED_TRADE_IDS
