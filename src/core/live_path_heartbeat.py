"""
V10.13j: Live-Path Heartbeat Counter

Tracks key metrics for the live trading pipeline to detect where the path breaks:
  - ticks received
  - candidates generated
  - candidates sent to RDE
  - candidates passed RDE
  - execution attempts
  - live exceptions

Emits diagnostic every N seconds so breakage is visible immediately.
"""

import time
import logging
from threading import Lock
from typing import Dict, Optional

log = logging.getLogger(__name__)

# Emit heartbeat every N seconds
HEARTBEAT_INTERVAL = 30


class LivePathHeartbeat:
    """Tracks live pipeline health."""
    
    def __init__(self):
        self.lock = Lock()
        self.ticks_received = 0
        self.ticks_processed = 0
        self.candidates_generated = 0
        self.candidates_sent_to_rde = 0
        self.candidates_passed_rde = 0
        self.execution_attempts = 0
        self.live_exceptions = 0
        
        self.last_tick_time = 0.0
        self.last_process_time = 0.0
        self.last_candidate_time = 0.0
        self.last_passed_time = 0.0
        
        self.last_heartbeat = time.time()
    
    def record_tick_received(self) -> None:
        """Record tick arrival."""
        with self.lock:
            self.ticks_received += 1
            self.last_tick_time = time.time()
    
    def record_tick_processed(self) -> None:
        """Record tick was processed successfully."""
        with self.lock:
            self.ticks_processed += 1
            self.last_process_time = time.time()
    
    def record_candidate_generated(self) -> None:
        """Record signal candidate generated."""
        with self.lock:
            self.candidates_generated += 1
            self.last_candidate_time = time.time()
    
    def record_candidate_sent_to_rde(self) -> None:
        """Record candidate sent to decision engine."""
        with self.lock:
            self.candidates_sent_to_rde += 1
    
    def record_candidate_passed_rde(self) -> None:
        """Record candidate passed decision engine."""
        with self.lock:
            self.candidates_passed_rde += 1
            self.last_passed_time = time.time()
    
    def record_execution_attempt(self) -> None:
        """Record order placement attempt."""
        with self.lock:
            self.execution_attempts += 1
    
    def record_exception(self) -> None:
        """Record live exception."""
        with self.lock:
            self.live_exceptions += 1
    
    def emit_heartbeat(self, force: bool = False) -> Optional[str]:
        """
        Emit diagnostic if interval elapsed.
        
        Args:
            force: If True, emit regardless of interval.
        
        Returns:
            Diagnostic string or None if not time yet.
        """
        now = time.time()
        elapsed = now - self.last_heartbeat
        
        if not force and elapsed < HEARTBEAT_INTERVAL:
            return None
        
        with self.lock:
            # Calculate rates
            tick_rate = self.ticks_received / max(elapsed, 0.1) if elapsed > 0 else 0
            process_rate = self.ticks_processed / max(elapsed, 0.1) if elapsed > 0 else 0
            
            # Check pipeline breaks
            last_tick_age = now - self.last_tick_time if self.last_tick_time else float('inf')
            last_process_age = now - self.last_process_time if self.last_process_time else float('inf')
            last_candidate_age = now - self.last_candidate_time if self.last_candidate_time else float('inf')
            last_passed_age = now - self.last_passed_time if self.last_passed_time else float('inf')
            
            diag = (
                f"\n[LIVE_PATH_HEARTBEAT] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  Ticks received:        {self.ticks_received:8d}  ({tick_rate:6.1f}/s)\n"
                f"  Ticks processed:       {self.ticks_processed:8d}  ({process_rate:6.1f}/s)\n"
                f"  Candidates generated:  {self.candidates_generated:8d}  (last {last_candidate_age:6.1f}s ago)\n"
                f"  Candidates→RDE:        {self.candidates_sent_to_rde:8d}\n"
                f"  Candidates passed RDE: {self.candidates_passed_rde:8d}  (last {last_passed_age:6.1f}s ago)\n"
                f"  Execution attempts:    {self.execution_attempts:8d}\n"
                f"  Live exceptions:       {self.live_exceptions:8d}\n"
                f"  Last tick age:         {last_tick_age:8.1f}s\n"
                f"  Last process age:      {last_process_age:8.1f}s\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            )
            
            # Check for breaks
            breaks = []
            if last_tick_age > 60:
                breaks.append("⚠️  No ticks received in 60s")
            if self.candidates_generated == 0 and last_process_age < 60:
                breaks.append("⚠️  Ticks processed but no candidates generated")
            if self.candidates_passed_rde == 0 and self.candidates_sent_to_rde > 0:
                breaks.append("⚠️  Candidates generated but none passed RDE")
            if self.live_exceptions > 10:
                breaks.append(f"⚠️  High exception rate: {self.live_exceptions} exceptions")
            
            if breaks:
                diag += "ISSUES DETECTED:\n"
                for br in breaks:
                    diag += f"  {br}\n"
            
            self.last_heartbeat = now
            return diag


# Global singleton
_heartbeat = LivePathHeartbeat()


def record_tick_received() -> None:
    """Record tick arrival."""
    _heartbeat.record_tick_received()


def record_tick_processed() -> None:
    """Record tick was processed successfully."""
    _heartbeat.record_tick_processed()


def record_candidate_generated() -> None:
    """Record signal candidate generated."""
    _heartbeat.record_candidate_generated()


def record_candidate_sent_to_rde() -> None:
    """Record candidate sent to decision engine."""
    _heartbeat.record_candidate_sent_to_rde()


def record_candidate_passed_rde() -> None:
    """Record candidate passed decision engine."""
    _heartbeat.record_candidate_passed_rde()


def record_execution_attempt() -> None:
    """Record order placement attempt."""
    _heartbeat.record_execution_attempt()


def record_exception() -> None:
    """Record live exception."""
    _heartbeat.record_exception()


def emit_heartbeat(force: bool = False) -> Optional[str]:
    """Emit diagnostic if interval elapsed."""
    return _heartbeat.emit_heartbeat(force=force)


def get_heartbeat_snapshot() -> Dict:
    """Get current state snapshot."""
    with _heartbeat.lock:
        return {
            "ticks_received": _heartbeat.ticks_received,
            "ticks_processed": _heartbeat.ticks_processed,
            "candidates_generated": _heartbeat.candidates_generated,
            "candidates_sent_to_rde": _heartbeat.candidates_sent_to_rde,
            "candidates_passed_rde": _heartbeat.candidates_passed_rde,
            "execution_attempts": _heartbeat.execution_attempts,
            "live_exceptions": _heartbeat.live_exceptions,
        }
