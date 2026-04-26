"""
Runtime flags — centralized state for operational modes and safe guards.

Provides global state access for bot-wide operational flags without circular imports.
All flags are module-level variables with getter/setter functions.
"""

import logging
import time

# ════════════════════════════════════════════════════════════════════════════════
# EMERGENCY (2026-04-25): Firebase safe degradation mode
# ════════════════════════════════════════════════════════════════════════════════

_DB_DEGRADED_SAFE_MODE = False
_DB_DEGRADED_REASON = None
_DB_DEGRADED_LAST_SKIP_LOG = 0  # Timestamp of last entry-block log (throttle to 60s)
_LAST_FORCED_EXPLORE_LOG = 0  # Throttle forced explore suppression log
_LAST_DECISION_BLOCK_LOG = 0  # Throttle decision block log
_LAST_MICRO_TRADE_LOG = 0  # Throttle micro-trade suppression log
_LAST_ANTI_DEADLOCK_LOG = 0  # Throttle anti-deadlock suppression log


def set_db_degraded_safe_mode(value: bool, reason: str = None):
    """
    Set or clear DB_DEGRADED_SAFE_MODE.

    Args:
        value: True to enable safe mode, False to clear
        reason: Optional reason string (e.g., "quota_429", "unavailable")
    """
    global _DB_DEGRADED_SAFE_MODE, _DB_DEGRADED_REASON
    _DB_DEGRADED_SAFE_MODE = value
    _DB_DEGRADED_REASON = reason

    if value:
        logging.critical(f"[SAFE_MODE] DB_DEGRADED_SAFE_MODE = True (reason={reason})")
    else:
        logging.info(f"[SAFE_MODE] DB_DEGRADED_SAFE_MODE = False (recovered)")


def is_db_degraded_safe_mode() -> bool:
    """Check if safe mode is currently active."""
    return _DB_DEGRADED_SAFE_MODE


def get_db_degraded_reason() -> str:
    """Return the reason for safe mode, or None if not degraded."""
    return _DB_DEGRADED_REASON


def should_skip_entry(symbol: str) -> tuple[bool, str]:
    """
    Check if entry should be blocked due to safe mode.

    Returns (should_skip, reason_code).
    Logs once per 60 seconds to avoid spam.
    """
    global _DB_DEGRADED_LAST_SKIP_LOG

    if not _DB_DEGRADED_SAFE_MODE:
        return False, ""

    now = time.time()
    should_log = (now - _DB_DEGRADED_LAST_SKIP_LOG) >= 60.0

    if should_log:
        logging.warning(
            f"[SAFE_MODE] entry blocked: FIREBASE_DEGRADED_SAFE_MODE "
            f"reason={_DB_DEGRADED_REASON}"
        )
        _DB_DEGRADED_LAST_SKIP_LOG = now

    return True, "FIREBASE_DEGRADED_SAFE_MODE"


def log_suppressed_forced_explore():
    """Log forced explore suppression (throttled to once per 60s)."""
    global _LAST_FORCED_EXPLORE_LOG

    if not _DB_DEGRADED_SAFE_MODE:
        return

    now = time.time()
    should_log = (now - _LAST_FORCED_EXPLORE_LOG) >= 60.0

    if should_log:
        logging.warning(
            f"[SAFE_MODE] forced explore suppressed reason={_DB_DEGRADED_REASON}"
        )
        _LAST_FORCED_EXPLORE_LOG = now


def log_suppressed_micro_trade():
    """Log micro-trade suppression (throttled to once per 60s)."""
    global _LAST_MICRO_TRADE_LOG

    if not _DB_DEGRADED_SAFE_MODE:
        return

    now = time.time()
    should_log = (now - _LAST_MICRO_TRADE_LOG) >= 60.0

    if should_log:
        logging.warning(
            f"[SAFE_MODE] micro-trade suppressed reason={_DB_DEGRADED_REASON}"
        )
        _LAST_MICRO_TRADE_LOG = now


def log_suppressed_anti_deadlock():
    """Log anti-deadlock suppression (throttled to once per 60s)."""
    global _LAST_ANTI_DEADLOCK_LOG

    if not _DB_DEGRADED_SAFE_MODE:
        return

    now = time.time()
    should_log = (now - _LAST_ANTI_DEADLOCK_LOG) >= 60.0

    if should_log:
        logging.warning(
            f"[SAFE_MODE] anti-deadlock suppressed reason={_DB_DEGRADED_REASON}"
        )
        _LAST_ANTI_DEADLOCK_LOG = now


def log_suppressed_decision(decision_code: str):
    """Log suppressed trading decision (throttled to once per 60s)."""
    global _LAST_DECISION_BLOCK_LOG

    if not _DB_DEGRADED_SAFE_MODE:
        return

    now = time.time()
    should_log = (now - _LAST_DECISION_BLOCK_LOG) >= 60.0

    if should_log:
        logging.warning(
            f"[SAFE_MODE] decision={decision_code} reason={_DB_DEGRADED_REASON}"
        )
        _LAST_DECISION_BLOCK_LOG = now


def get_dashboard_status() -> dict:
    """
    Get bot status for dashboard display.

    Returns dict with:
    - state: "SAFE_MODE_FIREBASE_DEGRADED" or operational state
    - entries: "blocked" if safe mode, else normal
    - reason: degradation reason if safe mode
    """
    if _DB_DEGRADED_SAFE_MODE:
        return {
            "state": "SAFE_MODE_FIREBASE_DEGRADED",
            "entries": "blocked",
            "reason": _DB_DEGRADED_REASON or "unknown",
            "note": "existing positions managed normally",
        }
    return {}


def safe_stall_seconds(
    now: float,
    last_trade_ts: float | None,
    runtime_start_ts: float | None,
    last_cycle_ts: float | None,
) -> float:
    """
    STEP 3: Calculate stall duration safely, preventing unix-time-sized values.

    Selects the most recent valid timestamp from candidates and computes elapsed time.
    Never uses invalid/corrupted timestamps as anchors, preventing false STALL anomalies.

    Args:
        now: Current timestamp
        last_trade_ts: Last trade execution time, or None
        runtime_start_ts: Bot runtime start time, or None
        last_cycle_ts: Last decision cycle time, or None

    Returns:
        float: Stall duration in seconds (0.0 if no valid anchor, else max(0, now - anchor))
    """
    candidates = [
        ts for ts in (last_trade_ts, runtime_start_ts, last_cycle_ts)
        if isinstance(ts, (int, float)) and ts > 0 and ts <= now
    ]
    anchor = max(candidates) if candidates else now
    return max(0.0, now - anchor)
