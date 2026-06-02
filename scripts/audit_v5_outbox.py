#!/usr/bin/env python3
"""
Audit V5 Legacy Bridge Outbox

Shows:
1. Pending event count by type
2. Event age (how long waiting)
3. Retry history (attempts and backoff)
4. Error patterns
5. Firebase connection status
6. Quota usage
"""

import sys
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.services.v5_legacy_bridge.outbox import DurableOutbox
from src.services.v5_legacy_bridge import config


def audit_outbox() -> None:
    """Run complete outbox audit."""
    print("\n" + "=" * 80)
    print("V5 LEGACY BRIDGE OUTBOX AUDIT")
    print("=" * 80)
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    print(f"Database: {config.V5_OUTBOX_DB_PATH}")
    print()

    # Connect to DB
    try:
        conn = sqlite3.connect(config.V5_OUTBOX_DB_PATH)
        cursor = conn.cursor()
    except Exception as e:
        print(f"ERROR: Failed to connect to outbox DB: {e}")
        return

    # 1. Overall statistics
    print("1. OVERALL STATISTICS")
    print("-" * 80)
    cursor.execute("SELECT COUNT(*) FROM outbox")
    total = cursor.fetchone()[0]
    print(f"Total pending events: {total}")

    cursor.execute("SELECT COUNT(*) FROM outbox WHERE retry_count = 0")
    never_retried = cursor.fetchone()[0]
    print(f"Never retried (fresh): {never_retried}")

    cursor.execute("SELECT COUNT(*) FROM outbox WHERE retry_count > 0")
    retried = cursor.fetchone()[0]
    print(f"Retried at least once: {retried}")

    cursor.execute("SELECT MAX(retry_count) FROM outbox")
    max_retries = cursor.fetchone()[0]
    print(f"Max retry attempts: {max_retries if max_retries else 'N/A'}")
    print()

    # 2. Count by event type
    print("2. PENDING BY EVENT TYPE")
    print("-" * 80)
    cursor.execute(
        """
        SELECT event_type, COUNT(*) as count
        FROM outbox
        GROUP BY event_type
        ORDER BY count DESC
        """
    )
    total_by_type = 0
    for event_type, count in cursor.fetchall():
        pct = (count / total * 100) if total > 0 else 0
        print(f"  {event_type:20s} {count:5d} ({pct:5.1f}%)")
        total_by_type += count
    print()

    # 3. Age analysis
    print("3. EVENT AGE ANALYSIS")
    print("-" * 80)
    now = datetime.utcnow()
    cursor.execute(
        """
        SELECT
            event_type,
            COUNT(*) as count,
            MIN(created_at) as oldest,
            MAX(created_at) as newest
        FROM outbox
        GROUP BY event_type
        ORDER BY created_at ASC
        """
    )

    oldest_timestamp = None
    for event_type, count, created_at, newest_at in cursor.fetchall():
        if created_at:
            created = datetime.fromisoformat(created_at)
            age_seconds = (now - created).total_seconds()
            age_hours = age_seconds / 3600
            age_days = age_seconds / 86400

            if age_seconds < 60:
                age_str = f"{int(age_seconds)}s"
            elif age_seconds < 3600:
                age_str = f"{int(age_seconds / 60)}m"
            elif age_seconds < 86400:
                age_str = f"{age_hours:.1f}h"
            else:
                age_str = f"{age_days:.1f}d"

            print(f"  {event_type:20s} oldest={age_str} (since {created.strftime('%Y-%m-%d %H:%M:%S')})")

            if oldest_timestamp is None or created < oldest_timestamp:
                oldest_timestamp = created

    if oldest_timestamp:
        oldest_age_seconds = (now - oldest_timestamp).total_seconds()
        oldest_age_hours = oldest_age_seconds / 3600
        print(f"\n  Oldest event: {oldest_age_hours:.1f} hours ({oldest_age_seconds / 60:.0f} minutes)")
    print()

    # 4. Retry history
    print("4. RETRY BACKOFF ANALYSIS")
    print("-" * 80)
    cursor.execute(
        """
        SELECT retry_count, COUNT(*) as count
        FROM outbox
        GROUP BY retry_count
        ORDER BY retry_count ASC
        """
    )
    for retry_count, count in cursor.fetchall():
        if retry_count == 0:
            status = "Not yet attempted"
        else:
            # Exponential backoff: 60s * 2^(retry-1), max 900s
            backoff = min(60 * (2 ** (retry_count - 1)), 900)
            status = f"Retry #{retry_count}, next backoff: {backoff}s"
        print(f"  Attempt {retry_count}: {count:5d} events — {status}")
    print()

    # 5. Recent entries (last 10)
    print("5. RECENT ENTRIES (Last 10)")
    print("-" * 80)
    cursor.execute(
        """
        SELECT id, event_type, idempotency_key, retry_count, created_at, error
        FROM outbox
        ORDER BY created_at DESC
        LIMIT 10
        """
    )
    for row_id, event_type, idempotency_key, retry_count, created_at, error in cursor.fetchall():
        created = datetime.fromisoformat(created_at) if created_at else None
        age = (now - created).total_seconds() if created else 0
        if age < 60:
            age_str = f"{int(age)}s ago"
        elif age < 3600:
            age_str = f"{int(age / 60)}m ago"
        else:
            age_str = f"{age / 3600:.1f}h ago"

        error_str = f" | Error: {error[:50]}" if error else ""
        print(f"  [{row_id:3d}] {event_type:15s} {idempotency_key:30s} R{retry_count} {age_str}{error_str}")
    print()

    # 6. Error patterns
    print("6. ERROR PATTERNS")
    print("-" * 80)
    cursor.execute(
        """
        SELECT error, COUNT(*) as count
        FROM outbox
        WHERE error IS NOT NULL
        GROUP BY error
        ORDER BY count DESC
        LIMIT 10
        """
    )
    error_rows = cursor.fetchall()
    if error_rows:
        for error, count in error_rows:
            truncated = (error[:60] + "...") if len(error) > 60 else error
            print(f"  {count:3d}x {truncated}")
    else:
        print("  (No errors recorded)")
    print()

    # 7. Status summary
    print("7. STATUS SUMMARY")
    print("-" * 80)
    if total == 0:
        print("✅ Outbox is EMPTY — all events flushed to Firebase")
    elif never_retried == total:
        print("⚠️  All events are FRESH (never retried) — check if flush worker is running")
    elif retried > 0 and retried == total:
        print("⚠️  All events have been RETRIED — possible persistent Firebase issue")
    else:
        print(f"📊 Mixed state: {never_retried} fresh, {retried} retried")

    # Check Firebase client
    try:
        from src.services import firebase_client as fb_module
        fb_available = hasattr(fb_module, 'db') and fb_module.db is not None
        print(f"Firebase client: {'✅ Connected' if fb_available else '❌ Unavailable'}")
    except Exception as e:
        print(f"Firebase client: ❌ Error checking ({e})")

    print()
    conn.close()


def count_by_state() -> None:
    """Show state distribution."""
    print("\n" + "=" * 80)
    print("OUTBOX STATE DISTRIBUTION")
    print("=" * 80)

    try:
        conn = sqlite3.connect(config.V5_OUTBOX_DB_PATH)
        cursor = conn.cursor()
    except Exception as e:
        print(f"ERROR: {e}")
        return

    # Count entries ready for retry vs waiting
    now = datetime.utcnow().isoformat()
    cursor.execute(
        f"""
        SELECT
            CASE
                WHEN retry_count >= 10 THEN 'EXHAUSTED (max retries)'
                WHEN next_retry_at IS NULL OR next_retry_at <= '{now}' THEN 'READY_TO_RETRY'
                ELSE 'WAITING_FOR_BACKOFF'
            END as state,
            COUNT(*) as count
        FROM outbox
        GROUP BY state
        ORDER BY state
        """
    )

    print()
    for state, count in cursor.fetchall():
        print(f"  {state:25s} {count:5d}")
    print()

    conn.close()


if __name__ == "__main__":
    audit_outbox()
    count_by_state()
