import sys as _sys
from collections import deque

# Windows cp1250 consoles crash on emoji — force utf-8 stdout/stderr at import time.
if hasattr(_sys.stdout, "reconfigure"):
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_subscribers        = {}
_subscription_keys  = set()

# ── Idempotency guard (V10.14.b) ──────────────────────────────────────────────
# Handlers that set data["_event_id"] = <unique_id> are deduplicated.
# Delivery guarantee: AT-LEAST-ONCE per symbol; no global ordering guarantee.
# Handlers MUST be idempotent and tolerate delivery without _event_id.
# deque(maxlen=2000) auto-evicts the *oldest* entry on overflow — a plain set
# had no insertion-order guarantee, so eviction was random (could drop recent
# IDs and pass duplicates through).
_processed_events: deque = deque(maxlen=2000)


def subscribe(event, handler):
    existing = _subscribers.get(event, [])
    if handler in existing:
        print(f"[!] Duplicate subscription prevented: {event} -> {handler.__name__}")
        return
    _subscribers.setdefault(event, []).append(handler)
    print(f"[OK] Subscribed: {event} -> {handler.__name__}")


def subscribe_once(event, handler):
    """Idempotent subscribe — no-op if already registered (prevents double-bind on reload)."""
    key = f"{event}_{handler.__module__}_{handler.__name__}"
    if key in _subscription_keys:
        return
    _subscription_keys.add(key)
    subscribe(event, handler)


def publish(event, data=None):
    # Dedup by _event_id when present — guards against AT-LEAST-ONCE re-delivery
    # (e.g. Redis pubsub reconnect that replays the last message).
    if isinstance(data, dict):
        eid = data.get("_event_id")
        if eid is not None:
            if eid in _processed_events:
                return
            _processed_events.append(eid)   # deque drops oldest entry automatically

    for h in _subscribers.get(event, []):
        try:
            h(data)
        except Exception as e:
            print(f"❌ Event error [{event}]:", e)


# Namespace object for backward compatibility with code that uses event_bus.method() syntax
class _EventBusNamespace:
    """Namespace for event_bus functions — allows both function and object syntax."""
    subscribe = staticmethod(subscribe)
    subscribe_once = staticmethod(subscribe_once)
    publish = staticmethod(publish)


event_bus = _EventBusNamespace()
