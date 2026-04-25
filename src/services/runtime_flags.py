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
