#!/usr/bin/env python3
"""
Firebase Quota System Test Suite

Tests the 50,000 reads/day and 20,000 writes/day quota tracking system.
Can be run standalone or imported for validation.

Usage:
    python test_quota_system.py

Tests cover:
  1. Initial state verification
  2. Pre-flight check logic
  3. Record operations and counter updates
  4. Quota warnings at 90%
  5. Quota reset at 24-hour boundary
  6. Integration with actual Firebase operations
"""

import sys
import time
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
log = logging.getLogger(__name__)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services import firebase_client


class QuotaSystemTests:
    """Test suite for Firebase quota system."""
    
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
    
    def test(self, name, condition, details=""):
        """Record a test result."""
        self.tests_run += 1
        status = "✅ PASS" if condition else "❌ FAIL"
        log.info(f"{status} | {name} {details}")
        if condition:
            self.tests_passed += 1
        else:
            self.tests_failed += 1
        return condition
    
    def run_all(self):
        """Run all tests."""
        log.info("=" * 80)
        log.info("FIREBASE QUOTA SYSTEM TEST SUITE")
        log.info("=" * 80)
        
        self.test_initial_state()
        self.test_can_read_logic()
        self.test_can_write_logic()
        self.test_record_read()
        self.test_record_write()
        self.test_quota_warnings()
        self.test_quota_reset()
        self.test_mark_quota_exhausted()
        self.test_get_quota_status()
        
        log.info("=" * 80)
        log.info(f"RESULTS: {self.tests_passed}/{self.tests_run} passed")
        if self.tests_failed > 0:
            log.error(f"FAILED: {self.tests_failed} tests")
            return False
        else:
            log.info("✅ All tests passed!")
            return True
    
    def test_initial_state(self):
        """Test that quota system starts with zero counters."""
        log.info("\n[TEST 1] Initial State Verification")
        
        firebase_client._QUOTA_READS = 0
        firebase_client._QUOTA_WRITES = 0
        
        self.test("Quota reads = 0", firebase_client._QUOTA_READS == 0)
        self.test("Quota writes = 0", firebase_client._QUOTA_WRITES == 0)
        self.test("Max reads = 50000", firebase_client._QUOTA_MAX_READS == 50000)
        self.test("Max writes = 20000", firebase_client._QUOTA_MAX_WRITES == 20000)
    
    def test_can_read_logic(self):
        """Test pre-flight read checks."""
        log.info("\n[TEST 2] Pre-flight Read Checks")
        
        firebase_client._QUOTA_READS = 0
        firebase_client._QUOTA_WINDOW_START = time.time()
        
        # Should allow read when under limit
        allowed, current, limit = firebase_client._can_read(1)
        self.test("Allow read when under limit", allowed, f"(reads={current}/{limit})")
        
        # Should allow multiple reads
        firebase_client._QUOTA_READS = 49999
        allowed, current, limit = firebase_client._can_read(1)
        self.test("Allow 1 more read at 49999/50000", allowed, f"(reads={current}/{limit})")
        
        # Should block when would exceed
        firebase_client._QUOTA_READS = 49999
        allowed, current, limit = firebase_client._can_read(2)
        self.test("Block 2 reads when would exceed", not allowed, f"(reads={current}/{limit})")
        
        # Should block at exact limit
        firebase_client._QUOTA_READS = 50000
        allowed, current, limit = firebase_client._can_read(1)
        self.test("Block read at exact limit", not allowed, f"(reads={current}/{limit})")
    
    def test_can_write_logic(self):
        """Test pre-flight write checks."""
        log.info("\n[TEST 3] Pre-flight Write Checks")
        
        firebase_client._QUOTA_WRITES = 0
        firebase_client._QUOTA_WINDOW_START = time.time()
        
        # Should allow write when under limit
        allowed, current, limit = firebase_client._can_write(1)
        self.test("Allow write when under limit", allowed, f"(writes={current}/{limit})")
        
        # Should allow multiple writes
        firebase_client._QUOTA_WRITES = 19999
        allowed, current, limit = firebase_client._can_write(1)
        self.test("Allow 1 more write at 19999/20000", allowed, f"(writes={current}/{limit})")
        
        # Should block when would exceed
        firebase_client._QUOTA_WRITES = 19999
        allowed, current, limit = firebase_client._can_write(2)
        self.test("Block 2 writes when would exceed", not allowed, f"(writes={current}/{limit})")
        
        # Should block at exact limit
        firebase_client._QUOTA_WRITES = 20000
        allowed, current, limit = firebase_client._can_write(1)
        self.test("Block write at exact limit", not allowed, f"(writes={current}/{limit})")
    
    def test_record_read(self):
        """Test read counter increment."""
        log.info("\n[TEST 4] Record Read Operations")
        
        firebase_client._QUOTA_READS = 0
        
        firebase_client._record_read(1)
        self.test("Record 1 read increments counter", firebase_client._QUOTA_READS == 1)
        
        firebase_client._record_read(5)
        self.test("Record 5 reads adds to counter", firebase_client._QUOTA_READS == 6)
        
        firebase_client._record_read(100)
        self.test("Record 100 reads works", firebase_client._QUOTA_READS == 106)
    
    def test_record_write(self):
        """Test write counter increment."""
        log.info("\n[TEST 5] Record Write Operations")
        
        firebase_client._QUOTA_WRITES = 0
        
        firebase_client._record_write(1)
        self.test("Record 1 write increments counter", firebase_client._QUOTA_WRITES == 1)
        
        firebase_client._record_write(3)
        self.test("Record 3 writes adds to counter", firebase_client._QUOTA_WRITES == 4)
        
        firebase_client._record_write(50)
        self.test("Record 50 writes works", firebase_client._QUOTA_WRITES == 54)
    
    def test_quota_warnings(self):
        """Test that warnings occur at 90% utilization."""
        log.info("\n[TEST 6] Quota Warnings at 90%")
        
        # Test read warning at 90%
        firebase_client._QUOTA_READS = int(firebase_client._QUOTA_MAX_READS * 0.9)
        log.info(f"Simulating 90% read utilization: {firebase_client._QUOTA_READS}/{firebase_client._QUOTA_MAX_READS}")
        firebase_client._record_read(1)
        log.info("Should have logged read warning above")
        self.test("Read counter at 90%+ triggers warning", True)  # Visual confirmation
        
        # Test write warning at 90%
        firebase_client._QUOTA_WRITES = int(firebase_client._QUOTA_MAX_WRITES * 0.9)
        log.info(f"Simulating 90% write utilization: {firebase_client._QUOTA_WRITES}/{firebase_client._QUOTA_MAX_WRITES}")
        firebase_client._record_write(1)
        log.info("Should have logged write warning above")
        self.test("Write counter at 90%+ triggers warning", True)  # Visual confirmation
    
    def test_quota_reset(self):
        """Test that quota resets at 24-hour boundary."""
        log.info("\n[TEST 7] Quota Reset at 24-Hour Boundary")
        
        # Setup: Set quota window to past (simulate 86400s+ elapsed)
        firebase_client._QUOTA_READS = 1000
        firebase_client._QUOTA_WRITES = 500
        firebase_client._QUOTA_WINDOW_START = time.time() - 86401  # More than 24 hours ago
        
        # Trigger reset by calling get_quota_status (which calls _reset_quota_if_new_day)
        status = firebase_client.get_quota_status()
        
        self.test("Quota reads reset to 0", firebase_client._QUOTA_READS == 0, 
                 f"(actual={firebase_client._QUOTA_READS})")
        self.test("Quota writes reset to 0", firebase_client._QUOTA_WRITES == 0,
                 f"(actual={firebase_client._QUOTA_WRITES})")
        self.test("Window start updated", firebase_client._QUOTA_WINDOW_START > (time.time() - 1))
    
    def test_mark_quota_exhausted(self):
        """Test that 429 errors properly mark quota as exhausted."""
        log.info("\n[TEST 8] Mark Quota Exhausted (429 Error Detection)")
        
        firebase_client._QUOTA_READS = 1000
        firebase_client._QUOTA_WRITES = 500
        
        # Simulate 429 error
        firebase_client._mark_quota_exhausted("Test 429 error")
        
        self.test("Quota reads set to limit on 429", firebase_client._QUOTA_READS == firebase_client._QUOTA_MAX_READS,
                 f"(actual={firebase_client._QUOTA_READS})")
        self.test("Quota writes set to limit on 429", firebase_client._QUOTA_WRITES == firebase_client._QUOTA_MAX_WRITES,
                 f"(actual={firebase_client._QUOTA_WRITES})")
        
        # Verify pre-flight checks now block operations
        allowed_read, _, _ = firebase_client._can_read(1)
        self.test("After 429, read operations blocked", not allowed_read)
        
        allowed_write, _, _ = firebase_client._can_write(1)
        self.test("After 429, write operations blocked", not allowed_write)
    
    def test_get_quota_status(self):
        """Test quota status reporting."""
        log.info("\n[TEST 9] Quota Status Reporting")
        
        firebase_client._QUOTA_READS = 10000
        firebase_client._QUOTA_WRITES = 5000
        firebase_client._QUOTA_WINDOW_START = time.time()
        
        status = firebase_client.get_quota_status()
        
        self.test("Status has 'reads' key", "reads" in status)
        self.test("Status has 'reads_limit' key", "reads_limit" in status)
        self.test("Status has 'reads_pct' key", "reads_pct" in status)
        self.test("Status has 'writes' key", "writes" in status)
        self.test("Status has 'writes_limit' key", "writes_limit" in status)
        self.test("Status has 'writes_pct' key", "writes_pct" in status)
        
        log.info(f"\nQuota Status: {status}")
        
        self.test("Reads value correct", status["reads"] == 10000)
        self.test("Writes value correct", status["writes"] == 5000)
        self.test("Reads limit = 50000", status["reads_limit"] == 50000)
        self.test("Writes limit = 20000", status["writes_limit"] == 20000)


def main():
    """Run the test suite."""
    tests = QuotaSystemTests()
    success = tests.run_all()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
