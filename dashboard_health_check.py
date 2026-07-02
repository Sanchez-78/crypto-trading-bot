#!/usr/bin/env python3
"""
Dashboard Health Check Agent

Automatically tests dashboard after every deployment.
Validates all endpoints, data correctness, and freshness.
Reports failures immediately.
"""

import urllib.request
import json
import sys
from datetime import datetime, timezone, timedelta


class DashboardHealthCheck:
    """Comprehensive dashboard health validation."""

    def __init__(self, base_url="http://localhost:5001"):
        self.base_url = base_url
        self.checks_passed = 0
        self.checks_failed = 0
        self.errors = []

    def test_endpoint(self, endpoint: str, expected_keys: list = None) -> bool:
        """Test if endpoint returns valid JSON with expected keys."""
        try:
            url = f"{self.base_url}{endpoint}"
            response = urllib.request.urlopen(url, timeout=5)
            data = json.loads(response.read().decode())

            # Validate expected keys if provided
            if expected_keys:
                missing = [k for k in expected_keys if k not in data]
                if missing:
                    self.errors.append(f"  ❌ {endpoint}: Missing keys: {missing}")
                    self.checks_failed += 1
                    return False

            self.checks_passed += 1
            return True

        except Exception as e:
            self.errors.append(f"  ❌ {endpoint}: {str(e)}")
            self.checks_failed += 1
            return False

    def validate_metrics(self) -> bool:
        """Validate metrics endpoint returns correct data."""
        try:
            response = urllib.request.urlopen(f"{self.base_url}/api/dashboard/metrics", timeout=5)
            metrics = json.loads(response.read().decode())

            # Check required fields
            required = ['closed_trades', 'win_rate_pct', 'net_pnl', 'profit_factor']
            missing = [k for k in required if k not in metrics]
            if missing:
                self.errors.append(f"  ❌ Metrics: Missing fields: {missing}")
                self.checks_failed += 1
                return False

            # Validate metric ranges
            wr = metrics.get('win_rate_pct', 0)
            if wr < 0 or wr > 100:
                self.errors.append(f"  ❌ Metrics: Invalid WR {wr}%")
                self.checks_failed += 1
                return False

            # Check that closed trades > 0 (indicates live data)
            trades = metrics.get('closed_trades', 0)
            if trades == 0:
                self.errors.append(f"  ❌ Metrics: No closed trades (stale data?)")
                self.checks_failed += 1
                return False

            self.checks_passed += 1
            return True

        except Exception as e:
            self.errors.append(f"  ❌ Metrics validation: {str(e)}")
            self.checks_failed += 1
            return False

    def validate_trades(self) -> bool:
        """Validate recent trades endpoint returns fresh data."""
        try:
            response = urllib.request.urlopen(f"{self.base_url}/api/trades/recent", timeout=5)
            trades = json.loads(response.read().decode())

            if not isinstance(trades, list):
                self.errors.append(f"  ❌ Trades: Not a list")
                self.checks_failed += 1
                return False

            if len(trades) == 0:
                self.errors.append(f"  ❌ Trades: Empty list (no recent trades)")
                self.checks_failed += 1
                return False

            # Validate first trade structure
            first_trade = trades[0]
            required_fields = ['trade_id', 'symbol', 'entry_price', 'exit_price', 'pnl_pct', 'exit_timestamp']
            missing = [k for k in required_fields if k not in first_trade]
            if missing:
                self.errors.append(f"  ❌ Trades: Missing fields: {missing}")
                self.checks_failed += 1
                return False

            # Check data freshness (most recent trade should be recent)
            try:
                exit_time_str = first_trade.get('exit_timestamp', '')
                if exit_time_str:
                    exit_time = datetime.fromisoformat(exit_time_str.replace('Z', '+00:00'))
                    age_minutes = (datetime.now(timezone.utc) - exit_time).total_seconds() / 60
                    if age_minutes > 120:  # More than 2 hours old
                        self.errors.append(f"  ⚠️  Trades: Oldest visible trade is {age_minutes:.0f} min old")
                        # Don't fail for this, just warn
            except:
                pass

            self.checks_passed += 1
            return True

        except Exception as e:
            self.errors.append(f"  ❌ Trades validation: {str(e)}")
            self.checks_failed += 1
            return False

    def validate_frontend(self) -> bool:
        """Validate main dashboard frontend is accessible."""
        try:
            response = urllib.request.urlopen(f"{self.base_url}/", timeout=5)
            html = response.read().decode()

            if 'CryptoMaster' not in html or 'dashboard' not in html.lower():
                self.errors.append(f"  ❌ Frontend: Missing expected content")
                self.checks_failed += 1
                return False

            self.checks_passed += 1
            return True

        except Exception as e:
            self.errors.append(f"  ❌ Frontend: {str(e)}")
            self.checks_failed += 1
            return False

    def run_all_checks(self) -> bool:
        """Run all health checks and return overall status."""
        print("\n" + "="*70)
        print("🏥 DASHBOARD HEALTH CHECK")
        print("="*70)

        self.validate_frontend()
        self.validate_metrics()
        self.validate_trades()
        self.test_endpoint('/api/dashboard/readiness')

        # Print results
        print(f"\n✅ Passed: {self.checks_passed}")
        print(f"❌ Failed: {self.checks_failed}")

        if self.errors:
            print(f"\nErrors:")
            for error in self.errors:
                print(error)

        print("="*70)

        return self.checks_failed == 0


def main():
    """Run dashboard health check."""
    checker = DashboardHealthCheck()
    success = checker.run_all_checks()

    if success:
        print("\n✅ DASHBOARD HEALTHY - All checks passed!")
        return 0
    else:
        print("\n❌ DASHBOARD ISSUES DETECTED - See errors above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
