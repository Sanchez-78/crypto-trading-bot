"""
V10.13j: Boot-Time Fail-Fast Guardian

Validates all critical runtime modules can be imported before live trading starts.
Prevents "bot alive but internally broken" scenarios.

Scope: Import validation only (no runtime checks).
"""

import sys
import logging
from typing import List, Tuple

log = logging.getLogger(__name__)

# Critical modules that must be importable for live trading
CRITICAL_MODULES = [
    "src.services.smart_exit_engine",
    "src.services.trade_executor",
    "src.services.realtime_decision_engine",
    "src.services.signal_engine",
    "src.services.market_stream",
    "src.services.risk_engine",
    "bot2.main",
    "bot2.auditor",
]


def validate_critical_imports() -> Tuple[bool, List[str]]:
    """
    Validate all critical modules can be imported.
    
    Returns:
        (success: bool, failures: list of module names that failed)
        
    If any module cannot be imported, returns (False, [failed_modules])
    """
    failed = []
    
    for module_name in CRITICAL_MODULES:
        try:
            __import__(module_name)
            log.debug(f"✓ Import OK: {module_name}")
        except Exception as e:
            failed.append(module_name)
            log.error(f"✗ Import FAILED: {module_name} — {type(e).__name__}: {str(e)}")
    
    success = len(failed) == 0
    return success, failed


def assert_safe_boot(strict: bool = True) -> bool:
    """
    Assert boot safety. Raises or logs based on `strict` mode.
    
    Args:
        strict: If True, raise SystemExit on validation failure.
                If False, log error and return False.
    
    Returns:
        True if all critical imports succeeded.
    """
    success, failures = validate_critical_imports()
    
    if not success:
        banner = "\n" + ("="*70)
        banner += f"\n🚨 CRITICAL BOOT FAILURE\n"
        banner += f"   {len(failures)} critical module(s) failed to import:\n"
        for mod in failures:
            banner += f"   - {mod}\n"
        banner += f"\n   Do not proceed to live trading without fixing.\n"
        banner += ("="*70) + "\n"
        
        if strict:
            log.critical(banner)
            sys.exit(1)
        else:
            log.error(banner)
            return False
    else:
        log.info(f"✅ All {len(CRITICAL_MODULES)} critical modules import successfully")
        return True


if __name__ == "__main__":
    # Test the guardian
    success, failures = validate_critical_imports()
    print(f"Boot validation: {'PASS' if success else 'FAIL'}")
    if failures:
        print(f"Failed modules: {failures}")
    sys.exit(0 if success else 1)
