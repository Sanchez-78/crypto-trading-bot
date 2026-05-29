"""Timezone-aware UTC datetime utilities for V5 bot.

All V5 timestamps use timezone-aware UTC for proper serialization and comparison.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime.

    Replaces deprecated datetime.utcnow() with timezone-aware implementation.

    Returns:
        datetime.now(timezone.utc) - current time in UTC with timezone info
    """
    return datetime.now(timezone.utc)


def utc_timestamp_iso() -> str:
    """Get current UTC time as ISO 8601 string.

    Returns:
        ISO 8601 formatted UTC timestamp
    """
    return utc_now().isoformat()
