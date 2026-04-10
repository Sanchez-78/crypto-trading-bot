_subscribers        = {}
_subscription_keys  = set()

# ── Idempotency guard (V10.14.b) ──────────────────────────────────────────────
# Handlers that set data["_event_id"] = <unique_id> are deduplicated.
# Delivery guarantee: AT-LEAST-ONCE per symbol; no global ordering guarantee.
# Handlers MUST be idempotent and tolerate delivery without _event_id.
_processed_events: set = set()
_MAX_PROCESSED_EVENTS = 2000    # bounded; evict oldest half on overflow


def subscribe(event, handler):
    _subscribers.setdefault(event, []).append(handler)
    print(f"🔗 Subscribed: {event} -> {handler.__name__}")


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
            _processed_events.add(eid)
            if len(_processed_events) > _MAX_PROCESSED_EVENTS:
                keep = list(_processed_events)[-(  _MAX_PROCESSED_EVENTS // 2):]
                _processed_events.clear()
                _processed_events.update(keep)

    for h in _subscribers.get(event, []):
        try:
            h(data)
        except Exception as e:
            print(f"❌ Event error [{event}]:", e)
