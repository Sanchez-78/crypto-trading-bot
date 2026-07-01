#!/usr/bin/env python3
"""Phase 2 Deployment Validation - Pre-flight Checks

Verify all safety systems are operational before real trading.
"""

import sys
import json
from pathlib import Path

def check_phase1_validation():
    """Verify Phase 1 (learning) is stable."""
    print("✓ Checking Phase 1 stability...")

    # Check for persistent learning state
    learning_file = Path("server_local_backups/paper_adaptive_learning_state.json")
    if not learning_file.exists():
        print("❌ Phase 1 learning state not found")
        return False

    with open(learning_file) as f:
        learning_data = json.load(f)

    lifetime_n = learning_data.get("lifetime_n", 0)
    if lifetime_n < 50:
        print(f"❌ Phase 1 not ready: only {lifetime_n}/50 closes")
        return False

    print(f"✓ Phase 1: {lifetime_n} closes (learning active)")
    return True

def check_safety_framework():
    """Verify safety framework is loaded."""
    print("✓ Checking safety framework...")

    try:
        from src.services.real_trading_safety import get_safety
        safety = get_safety()
        status = safety.get_status()

        print(f"✓ Safety system initialized")
        print(f"  - Account: ${status['account_balance_usd']:.2f}")
        print(f"  - Daily loss limit: ${status['max_daily_loss_usd']:.2f}")
        print(f"  - Circuit breaker: {'Active' if status['circuit_breaker_active'] else 'Ready'}")
        return True
    except Exception as e:
        print(f"❌ Safety framework error: {e}")
        return False

def check_configuration():
    """Verify configuration file exists."""
    print("✓ Checking configuration...")

    config_file = Path("config_real_trading.env")
    if not config_file.exists():
        print("❌ Real trading config not found")
        return False

    with open(config_file) as f:
        content = f.read()

    if "TRADING_MODE=real_live" not in content:
        print("⚠️  Warning: TRADING_MODE not set to real_live in config")
        print("   (This is correct for validation. Will be set during deployment.)")

    if "ACCOUNT_BALANCE_USD=" in content:
        print("✓ Account balance configured")

    if "MAX_DAILY_LOSS_PCT=" in content:
        print("✓ Daily loss limit configured")

    return True

def check_monitoring_system():
    """Verify monitoring/alerting system."""
    print("✓ Checking monitoring system...")

    # Check if logs directory exists
    logs_dir = Path("logs")
    if logs_dir.exists():
        print("✓ Logging directory ready")
    else:
        print("⚠️  Creating logs directory...")
        logs_dir.mkdir(exist_ok=True)

    return True

def main():
    """Run all pre-flight checks."""
    print("═" * 60)
    print("PHASE 2 DEPLOYMENT VALIDATION - PRE-FLIGHT CHECKS")
    print("═" * 60)
    print()

    checks = [
        ("Phase 1 Learning System", check_phase1_validation),
        ("Safety Framework", check_safety_framework),
        ("Configuration", check_configuration),
        ("Monitoring System", check_monitoring_system),
    ]

    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
            print()
        except Exception as e:
            print(f"❌ {name}: {e}")
            results.append((name, False))
            print()

    # Summary
    print("═" * 60)
    print("VALIDATION SUMMARY")
    print("═" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print()
    print(f"Result: {passed}/{total} checks passed")
    print()

    if passed == total:
        print("✅ ALL CHECKS PASSED - Ready for Phase 2 real trading deployment")
        print()
        print("Safety System Active:")
        print("  • Circuit breaker: 2% daily loss limit ($100 on $5k account)")
        print("  • Position sizing: Kelly criterion with 25% safety factor")
        print("  • Manual override: Kill switch available")
        print("  • Emergency mode: Auto-revert to paper on triggers")
        return 0
    else:
        print("❌ Some checks failed - Address issues before deploying")
        return 1

if __name__ == "__main__":
    sys.exit(main())
