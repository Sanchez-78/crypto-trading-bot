"""
V10.13s.4: Canonical State Oracle — Single Source of Truth at Startup

Initializes authoritative trade counts from Firestore before any decision logic
runs. Eliminates stale/conflicting global state at startup.

Structure:
  {
    "source": "firestore" | "redis" | "history" | "empty" | "error",
    "trades_total": int,
    "trades_won": int,
    "trades_lost": int,
    "validation": "ok" | "mismatch" | "error",
    "mismatch_gap": int,  # if validation="mismatch"
    "timestamp": float,
  }
"""

import logging
import time as _time

_canonical_state = {
    "source": "empty",
    "trades_total": 0,
    "trades_won": 0,
    "trades_lost": 0,
    "validation": "pending",
    "mismatch_gap": 0,
    "timestamp": 0.0,
}


def get_canonical_state() -> dict:
    """Get current canonical state (read-only)."""
    return _canonical_state.copy()


def get_authoritative_trade_count() -> int:
    """Get authoritative total trade count (for execution.py bootstrap_mode)."""
    return _canonical_state.get("trades_total", 0)


def _load_from_firestore() -> dict:
    """Load metrics from Firestore metrics collection."""
    try:
        from src.services.firebase_client import db

        if not db:
            return None

        doc = db.collection("metrics_full").document("global").get()
        if not doc.exists:
            return None

        data = doc.to_dict() or {}
        return {
            "source": "firestore",
            "trades_total": data.get("trades", 0),
            "trades_won": data.get("trades_won", 0),
            "trades_lost": data.get("trades_lost", 0),
        }
    except Exception as e:
        logging.warning(f"[CANONICAL] Failed to load from Firestore: {e}")
        return None


def _load_from_redis() -> dict:
    """Load metrics from Redis cache (faster than Firestore on warm start)."""
    try:
        from src.services.redis_pool import get_redis
        r = get_redis()
        if not r:
            return None

        metrics_json = r.get("metrics:global")
        if not metrics_json:
            return None

        import json
        data = json.loads(metrics_json)
        return {
            "source": "redis",
            "trades_total": data.get("trades", 0),
            "trades_won": data.get("trades_won", 0),
            "trades_lost": data.get("trades_lost", 0),
        }
    except Exception as e:
        logging.debug(f"[CANONICAL] Failed to load from Redis: {e}")
        return None


def _load_from_history(history: list) -> dict:
    """Compute canonical state from loaded trade history."""
    if not history:
        return {
            "source": "history",
            "trades_total": 0,
            "trades_won": 0,
            "trades_lost": 0,
        }

    won = sum(1 for t in history if t.get("pnl_closed", 0) > 0)
    lost = sum(1 for t in history if t.get("pnl_closed", 0) <= 0)

    return {
        "source": "history",
        "trades_total": len(history),
        "trades_won": won,
        "trades_lost": lost,
    }


def _validate_consistency(trades_total: int, trades_won: int, trades_lost: int) -> tuple[str, int]:
    """
    Validate trades_won + trades_lost ≈ trades_total.

    Returns: (status: "ok" | "mismatch" | "error", gap: int)
    """
    if trades_total == 0:
        return "ok", 0

    computed_total = trades_won + trades_lost
    gap = abs(computed_total - trades_total)

    max_gap = max(1, int(trades_total * 0.05))

    if gap > max_gap:
        return "mismatch", gap

    return "ok", 0


def initialize_canonical_state(history: list = None) -> dict:
    """
    V10.13s.4: Initialize canonical state at startup.

    Priority order:
    1. Redis (fastest, warm start)
    2. Firestore (authoritative, cold start)
    3. History (computed from loaded trades)
    4. Empty (first run)

    Args:
        history: Optional loaded trade history (fallback source)

    Returns:
        Initialized canonical state dict
    """
    global _canonical_state

    logging.info("[CANONICAL] Initializing source-of-truth state...")

    result = _load_from_redis()
    if result:
        logging.info(f"[CANONICAL] Loaded from Redis: {result['trades_total']} trades")
    else:
        result = _load_from_firestore()
        if result:
            logging.info(f"[CANONICAL] Loaded from Firestore: {result['trades_total']} trades")
        else:
            result = _load_from_history(history)
            logging.info(f"[CANONICAL] Computed from history: {result['trades_total']} trades")

    validation, gap = _validate_consistency(
        result["trades_total"],
        result["trades_won"],
        result["trades_lost"]
    )

    if validation == "ok":
        logging.info(f"[CANONICAL] OK - State consistent")
    else:
        logging.warning(
            f"[CANONICAL] MISMATCH: total={result['trades_total']}, "
            f"won+lost={result['trades_won']+result['trades_lost']}, gap={gap}"
        )

    _canonical_state.update({
        "source": result["source"],
        "trades_total": result["trades_total"],
        "trades_won": result["trades_won"],
        "trades_lost": result["trades_lost"],
        "validation": validation,
        "mismatch_gap": gap,
        "timestamp": _time.time(),
    })

    return _canonical_state.copy()


def print_canonical_state():
    """Log canonical state for diagnostics."""
    state = get_canonical_state()

    print("\n" + "="*70)
    print("CANONICAL STATE AUDIT (Startup)")
    print("="*70)
    print(f"  Source:        {state['source']}")
    print(f"  Trades Total:  {state['trades_total']}")
    print(f"  Trades Won:    {state['trades_won']}")
    print(f"  Trades Lost:   {state['trades_lost']}")
    print(f"  Validation:    {state['validation']}")
    if state['mismatch_gap'] > 0:
        print(f"  Mismatch Gap:  {state['mismatch_gap']}")
    print("="*70 + "\n")
