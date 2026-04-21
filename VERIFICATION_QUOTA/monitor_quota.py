#!/usr/bin/env python3
"""
Firebase Quota System - Live Monitoring & Diagnostics

Provides real-time visibility into quota usage and health.
Can be run continuously or on-demand to check quota status.

Usage:
    # One-time check
    python monitor_quota.py

    # Continuous monitoring (every 30 seconds)
    python monitor_quota.py --continuous

    # With custom interval
    python monitor_quota.py --continuous --interval 60

    # JSON output for dashboard integration
    python monitor_quota.py --json

    # Verbose diagnostics
    python monitor_quota.py --verbose
"""

import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
import io

# Force UTF-8 output encoding on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services import firebase_client


def format_percentage(current, limit):
    """Format usage as percentage with color."""
    if limit == 0:
        return "N/A"
    pct = (current / limit) * 100
    if pct >= 100:
        return f"❌ {pct:.1f}%"
    elif pct >= 90:
        return f"🔴 {pct:.1f}%"
    elif pct >= 70:
        return f"🟠 {pct:.1f}%"
    elif pct >= 50:
        return f"🟡 {pct:.1f}%"
    else:
        return f"🟢 {pct:.1f}%"


def get_time_until_reset():
    """Calculate time remaining until quota reset."""
    elapsed = time.time() - firebase_client._QUOTA_WINDOW_START
    remaining = 86400 - elapsed
    
    if remaining < 0:
        return "RESET PENDING (should happen on next check)"
    
    hours = int(remaining // 3600)
    minutes = int((remaining % 3600) // 60)
    seconds = int(remaining % 60)
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def print_status(status, verbose=False):
    """Print human-readable quota status."""
    print("\n" + "=" * 70)
    print("📊 FIREBASE QUOTA STATUS")
    print("=" * 70)
    
    print(f"\n📖 READ QUOTA (Daily Limit: 50,000)")
    print(f"   Used:      {status['reads']:,} / {status['reads_limit']:,}")
    print(f"   Usage:     {format_percentage(status['reads'], status['reads_limit'])}")
    print(f"   Available: {status['reads_limit'] - status['reads']:,}")
    
    print(f"\n✍️  WRITE QUOTA (Daily Limit: 20,000)")
    print(f"   Used:      {status['writes']:,} / {status['writes_limit']:,}")
    print(f"   Usage:     {format_percentage(status['writes'], status['writes_limit'])}")
    print(f"   Available: {status['writes_limit'] - status['writes']:,}")
    
    print(f"\n⏱️  QUOTA WINDOW")
    print(f"   Time Until Reset: {get_time_until_reset()}")
    
    # Calculate projection
    if status['reads'] > 0 and firebase_client._QUOTA_WINDOW_START:
        elapsed = time.time() - firebase_client._QUOTA_WINDOW_START
        hours_elapsed = elapsed / 3600
        if hours_elapsed > 0:
            reads_per_hour = status['reads'] / hours_elapsed
            projected_daily = reads_per_hour * 24
            print(f"   Reads/Hour:  {reads_per_hour:.1f}")
            print(f"   Projected:   {projected_daily:,.0f} reads/day")
            
            if projected_daily > status['reads_limit']:
                print(f"   ⚠️  WARNING: Projected usage exceeds daily limit!")
    
    if status['writes'] > 0 and firebase_client._QUOTA_WINDOW_START:
        elapsed = time.time() - firebase_client._QUOTA_WINDOW_START
        hours_elapsed = elapsed / 3600
        if hours_elapsed > 0:
            writes_per_hour = status['writes'] / hours_elapsed
            projected_daily = writes_per_hour * 24
            print(f"   Writes/Hour: {writes_per_hour:.1f}")
            print(f"   Projected:   {projected_daily:,.0f} writes/day")
            
            if projected_daily > status['writes_limit']:
                print(f"   ⚠️  WARNING: Projected usage exceeds daily limit!")
    
    print("\n" + "=" * 70)
    
    if verbose:
        print("\n🔍 DETAILED DIAGNOSTICS")
        print(f"   Firebase DB connected: {firebase_client.db is not None}")
        print(f"   Window start time: {firebase_client._QUOTA_WINDOW_START}")
        print(f"   Current time: {time.time()}")
        print(f"   Retry queue size: {len(firebase_client._RETRY_QUEUE)}")
        print(f"   Max retry size: {firebase_client._MAX_RETRY_SIZE}")


def print_json_status(status):
    """Print quota status as JSON (for dashboard/API integration)."""
    output = {
        "timestamp": time.time(),
        "timestamp_iso": datetime.utcnow().isoformat() + "Z",
        "reads": {
            "used": status['reads'],
            "limit": status['reads_limit'],
            "usage_percent": (status['reads'] / status['reads_limit'] * 100) if status['reads_limit'] > 0 else 0,
            "available": status['reads_limit'] - status['reads'],
        },
        "writes": {
            "used": status['writes'],
            "limit": status['writes_limit'],
            "usage_percent": (status['writes'] / status['writes_limit'] * 100) if status['writes_limit'] > 0 else 0,
            "available": status['writes_limit'] - status['writes'],
        },
        "window": {
            "start_time": firebase_client._QUOTA_WINDOW_START,
            "time_until_reset_seconds": max(0, 86400 - (time.time() - firebase_client._QUOTA_WINDOW_START)),
        },
        "health": {
            "db_connected": firebase_client.db is not None,
            "retry_queue_size": len(firebase_client._RETRY_QUEUE),
            "retry_queue_full": len(firebase_client._RETRY_QUEUE) >= firebase_client._MAX_RETRY_SIZE,
        }
    }
    print(json.dumps(output, indent=2))


def monitor_continuous(interval=30, verbose=False):
    """Continuously monitor quota status."""
    print(f"\n🔄 CONTINUOUS MONITORING (interval: {interval}s)")
    print("Press Ctrl+C to stop\n")
    
    try:
        while True:
            status = firebase_client.get_quota_status()
            
            # Clear screen (Unix/Linux/Mac only, skip on Windows)
            # print("\033[2J\033[H", end="")
            
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]", end=" ")
            print(f"Reads: {status['reads']:,}/{status['reads_limit']:,} | ", end="")
            print(f"Writes: {status['writes']:,}/{status['writes_limit']:,} | ", end="")
            print(f"Reset in: {get_time_until_reset()}")
            
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n\n✋ Monitoring stopped")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor Firebase quota usage and health"
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Continuous monitoring (runs until Ctrl+C)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Monitoring interval in seconds (default: 30)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON (for dashboard integration)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed diagnostics"
    )
    
    args = parser.parse_args()
    
    if args.continuous:
        monitor_continuous(args.interval, args.verbose)
    else:
        status = firebase_client.get_quota_status()
        if args.json:
            print_json_status(status)
        else:
            print_status(status, args.verbose)


if __name__ == "__main__":
    main()
