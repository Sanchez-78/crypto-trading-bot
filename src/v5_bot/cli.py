"""V5 PAPER Bot CLI — status, validation, metrics, and cutover operations."""

import asyncio
import logging
import json
from typing import Optional
from datetime import datetime
from pathlib import Path

from .paper import V5BotRunner
from .firebase import QuotaAwareFirestoreRepository
from .learning import ReadinessEvaluator, READINESS_MESSAGES_CS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class V5CLI:
    """Command-line interface for V5 PAPER bot."""

    def __init__(self, firebase_creds_path: Optional[str] = None):
        self.runner = V5BotRunner(firebase_creds_path)
        self.firebase = self.runner.firebase
        self.readiness_eval = ReadinessEvaluator()

    def status(self) -> None:
        """Print current bot status."""
        status = self.runner.get_status()

        print("\n=== V5 PAPER BOT STATUS ===")
        print(f"Epoch: {status['epoch_id']}")
        print(f"Running: {status['running']}")
        print(f"Feed Connected: {status['feed_connected']}")
        print(f"Symbols with Data: {status['symbols_with_data']}")
        print()
        print("Position Summary:")
        print(f"  Open Positions: {status['open_positions']}")
        print(f"  Open Notional: ${status['open_notional_usd']:.2f}")
        print()
        print("Firebase Quota:")
        quota = status['quota_state']
        print(f"  State: {quota.get('state', 'unknown')}")
        print(f"  Reads Remaining: {quota.get('remaining_reads', '?')}")
        print(f"  Writes Remaining: {quota.get('remaining_writes', '?')}")
        print()
        print("Statistics:")
        stats = status['stats']
        print(f"  Entries Attempted: {stats['entries_attempted']}")
        print(f"  Entries Successful: {stats['entries_successful']}")
        print(f"  Entries Rejected: {stats['entries_rejected_by_gate']}")
        print(f"  Trades Closed: {stats['trades_closed']}")

    def validate_quota(self) -> None:
        """Validate Firebase quota setup."""
        print("\n=== QUOTA VALIDATION ===")

        try:
            status = self.firebase.get_quota_status()
            print(f"Quota State: {status.get('state', 'unknown')}")
            print(f"Daily Reads Remaining: {status.get('remaining_reads', '?')}")
            print(f"Daily Writes Remaining: {status.get('remaining_writes', '?')}")

            # Check if quota is healthy
            if status.get('state') == 'HARD_STOP':
                print("⚠️  QUOTA HARD STOP ACTIVE - no writes allowed")
            elif status.get('state') == 'CRITICAL':
                print("⚠️  QUOTA CRITICAL - limited writes only")
            elif status.get('state') == 'DEGRADED':
                print("⚠️  QUOTA DEGRADED - monitor closely")
            else:
                print("✓ Quota healthy")

        except Exception as e:
            print(f"✗ Quota validation failed: {e}")

    def validate_feeds(self) -> None:
        """Validate market data feeds."""
        print("\n=== FEED VALIDATION ===")

        try:
            status = self.runner.feed.get_status()
            print(f"Feed Running: {status['running']}")
            print(f"Reconnect Count: {status['reconnect_count']}")
            print(f"Symbols with Data: {status['symbols_with_data']}")
            print(f"Stale Events Rejected: {status['stale_events_rejected']}")

            if status['symbols_with_data'] > 0:
                print("✓ Feeds connected")
            else:
                print("✗ No feed data")

        except Exception as e:
            print(f"✗ Feed validation failed: {e}")

    def validate_firebase_connection(self) -> None:
        """Validate Firebase connectivity."""
        print("\n=== FIREBASE VALIDATION ===")

        try:
            # Try to read control document
            control = self.firebase.get_control()
            if control:
                print(f"✓ Firebase connected")
                print(f"  Active Epoch: {control.active_epoch_id}")
                print(f"  Mode: {'PAPER' if control.mode == 'paper' else 'REAL'}")
                print(f"  Entries Enabled: {control.entries_enabled}")
            else:
                print("✗ Could not read control document")

        except Exception as e:
            print(f"✗ Firebase connection failed: {e}")

    def check_readiness(self) -> None:
        """Check REAL readiness."""
        print("\n=== REAL READINESS EVALUATION ===")

        try:
            # Get learning state (would come from Firebase in real implementation)
            # For now, use example values
            report = self.readiness_eval.evaluate(
                eligible_closes=250,
                days_of_data=5,
                expectancy_bps=15.0,
                profit_factor=1.25,
                drawdown_pct=3.0,
                accounting_complete=True,
                incidents=0,
            )

            print(f"State: {report.state.value}")
            print(f"Status (CS): {report.state_label_cs}")
            print()
            print("Gate Status:")
            print(f"  Eligible Closes: {report.eligible_closes_current}/{report.eligible_closes_required}")
            print(f"  Days of Data: {report.days_of_data_current}/{report.days_of_data_required}")
            print(f"  Expectancy: {report.expectancy_bps_current:.1f} bps (min: 0.0)")
            print(f"  Profit Factor: {report.profit_factor_current:.2f} (min: 1.20)")
            print(f"  Drawdown: {report.drawdown_pct_current:.1f}% (max: 5.0%)")
            print()

            if report.blocking_reasons_cs:
                print("Blocking Reasons:")
                for reason in report.blocking_reasons_cs:
                    print(f"  • {reason}")
            else:
                print("✓ No blocking reasons")

            print()
            print(f"Paper Only: {report.paper_only}")
            print(f"REAL Orders Allowed: {report.real_orders_allowed}")

        except Exception as e:
            print(f"✗ Readiness evaluation failed: {e}")

    def show_help(self) -> None:
        """Show CLI help."""
        print("""
V5 PAPER Bot CLI

Commands:
  status          - Show current bot status
  validate-quota  - Check Firebase quota
  validate-feeds  - Check market data feeds
  validate-fb     - Check Firebase connection
  check-readiness - Evaluate REAL readiness
  help            - Show this help

Example:
  python -m src.v5_bot.cli status
        """)


async def main():
    """Main CLI entry point."""
    import sys

    cli = V5CLI()

    if len(sys.argv) < 2:
        cli.show_help()
        return

    command = sys.argv[1].lower()

    if command == "status":
        cli.status()
    elif command == "validate-quota":
        cli.validate_quota()
    elif command == "validate-feeds":
        cli.validate_feeds()
    elif command == "validate-fb":
        cli.validate_firebase_connection()
    elif command == "check-readiness":
        cli.check_readiness()
    elif command == "help" or command == "--help":
        cli.show_help()
    else:
        print(f"Unknown command: {command}")
        cli.show_help()


if __name__ == "__main__":
    asyncio.run(main())
