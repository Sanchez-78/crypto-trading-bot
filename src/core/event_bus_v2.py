"""
PATCH: Event Bus v2 — Single source of truth for all subsystem communication.

NO module is allowed to call print() directly.
All output, state changes, and cross-module signals must flow through event_bus.

This enforces:
- Deterministic execution (replay-able event log)
- No race conditions (single point of serialization)
- Clean audit trail (all decisions timestamped)
- Testability (mock event handlers)
"""

from collections import defaultdict
import threading
import time
import logging

log = logging.getLogger(__name__)

class EventBus:
    """Central event dispatcher for all subsystems."""
    
    def __init__(self):
        self.subscribers = defaultdict(list)  # event_type -> [handler, ...]
        from collections import deque
        self.event_log = deque(maxlen=50_000)  # BUG-017 fix: bounded to prevent OOM
        self.lock = threading.Lock()
        self.event_count = [0]
    
    def subscribe(self, event_type, handler, priority=0):
        """
        Register a handler for event_type.
        
        Args:
            event_type: str like "SIGNAL_GENERATED", "TRADE_CLOSED", "STATE_UPDATED"
            handler: callable(payload) — synchronous, must return quickly
            priority: int, higher = executed first
        """
        self.subscribers[event_type].append((priority, handler))
        # Sort by priority descending
        self.subscribers[event_type].sort(key=lambda x: -x[0])
    
    def emit(self, event_type, payload=None, timestamp=None):
        """
        Emit an event (synchronous dispatch).
        
        Args:
            event_type: str identifier
            payload: dict or any serializable data
            timestamp: float, auto-fills if None
        
        Returns:
            event_id: int for audit logging
        """
        if timestamp is None:
            timestamp = time.time()
        
        with self.lock:
            self.event_count[0] += 1
            event_id = self.event_count[0]
            
            event = {
                "id": event_id,
                "type": event_type,
                "payload": payload,
                "timestamp": timestamp,
            }
            
            self.event_log.append(event)
        
        # Dispatch to all subscribers (outside lock to avoid deadlock)
        for priority, handler in self.subscribers.get(event_type, []):
            try:
                handler(payload)
            except Exception as e:
                log.error(f"Event handler error [{event_type}]: {e}")
        
        return event_id
    
    def get_log(self, limit=None):
        """Return audit log (last `limit` events or all)."""
        with self.lock:
            if limit:
                return self.event_log[-limit:]
            return list(self.event_log)
    
    def clear_log(self):
        """Clear audit log (use sparingly for testing)."""
        with self.lock:
            self.event_log.clear()


# Global singleton
_event_bus = None

def get_event_bus():
    """Get or initialize the global event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus

def init_event_bus():
    """Explicitly initialize event bus."""
    global _event_bus
    _event_bus = EventBus()
    return _event_bus
