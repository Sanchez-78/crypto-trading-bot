"""
V10.13j: Event Exception Circuit Breaker

Detects runaway event handler exceptions and stops live trading to prevent
false recovery loops (watchdog lowering thresholds while actual error persists).

Behavior:
  - Track exception count per event type
  - If N exceptions in T seconds → circuit breaker OPEN
  - When OPEN, log fatal banner and halt live trading
  - Prevents self-heal from masking the real problem
"""

import time
import logging
from typing import Dict, Optional
from collections import deque

log = logging.getLogger(__name__)

# Tunable thresholds
EXCEPTION_WINDOW_SECONDS = 60  # Rolling window size
EXCEPTION_THRESHOLD = 10  # Exceptions before break
MIN_RECOVERY_SECONDS = 300  # Minimum before auto-reset (5 min)


class EventExceptionBreaker:
    """Circuit breaker for event handler exceptions."""
    
    def __init__(self):
        self.event_exceptions: Dict[str, deque] = {}  # event_type -> deque of timestamps
        self.circuit_state: Dict[str, str] = {}  # event_type -> CLOSED/OPEN
        self.state_changed_at: Dict[str, float] = {}  # when state changed
        self.fatal_logged: Dict[str, bool] = {}  # prevent log spam
    
    def record_exception(self, event_type: str) -> None:
        """Record an exception for this event type."""
        now = time.time()
        
        if event_type not in self.event_exceptions:
            self.event_exceptions[event_type] = deque(maxlen=EXCEPTION_THRESHOLD * 2)
            self.circuit_state[event_type] = "CLOSED"
            self.state_changed_at[event_type] = now
            self.fatal_logged[event_type] = False
        
        self.event_exceptions[event_type].append(now)
        
        # Check if we've exceeded threshold
        self._check_breaker(event_type, now)
    
    def _check_breaker(self, event_type: str, now: float) -> None:
        """Check if breaker should trip."""
        if self.circuit_state[event_type] == "OPEN":
            return  # Already open
        
        # Count exceptions in window
        cutoff = now - EXCEPTION_WINDOW_SECONDS
        recent = [t for t in self.event_exceptions[event_type] if t > cutoff]
        
        if len(recent) >= EXCEPTION_THRESHOLD:
            self.circuit_state[event_type] = "OPEN"
            self.state_changed_at[event_type] = now
            self.fatal_logged[event_type] = False
            self._log_fatal_break(event_type, len(recent))
    
    def _log_fatal_break(self, event_type: str, exception_count: int) -> None:
        """Log fatal circuit break event."""
        banner = "\n" + ("🔴" * 35)
        banner += "\n🔴 FATAL: EVENT EXCEPTION CIRCUIT BREAKER OPEN\n"
        banner += f"🔴 Event type: {event_type}\n"
        banner += f"🔴 Exceptions: {exception_count} in {EXCEPTION_WINDOW_SECONDS}s\n"
        banner += f"🔴 Live trading HALTED until manual recovery\n"
        banner += ("🔴" * 35) + "\n"
        
        log.critical(banner)
        self.fatal_logged[event_type] = True
    
    def is_open(self, event_type: str) -> bool:
        """Check if breaker is OPEN for this event type."""
        if event_type not in self.circuit_state:
            return False
        
        state = self.circuit_state[event_type]
        
        # Auto-reset after recovery window
        if state == "OPEN":
            elapsed = time.time() - self.state_changed_at.get(event_type, 0)
            if elapsed > MIN_RECOVERY_SECONDS:
                log.warning(f"[RECOVERY] Event breaker {event_type} auto-reset after {elapsed:.0f}s")
                self.reset(event_type)
                return False
        
        return state == "OPEN"
    
    def reset(self, event_type: str) -> None:
        """Manually reset breaker."""
        if event_type in self.circuit_state:
            self.circuit_state[event_type] = "CLOSED"
            self.state_changed_at[event_type] = time.time()
            self.fatal_logged[event_type] = False
            log.info(f"[RESET] Event breaker {event_type} reset")
    
    def get_status(self) -> Dict[str, str]:
        """Get current state of all breakers."""
        return dict(self.circuit_state)


# Global singleton
_breaker = EventExceptionBreaker()


def record_event_exception(event_type: str) -> None:
    """Record an exception for the given event type."""
    _breaker.record_exception(event_type)


def is_event_breaker_open(event_type: str) -> bool:
    """Check if event type has tripped circuit breaker."""
    return _breaker.is_open(event_type)


def get_breaker_status() -> Dict[str, str]:
    """Get current breaker status for all event types."""
    return _breaker.get_status()


def reset_breaker(event_type: str) -> None:
    """Manually reset a breaker."""
    _breaker.reset(event_type)
