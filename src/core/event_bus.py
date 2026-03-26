_subscribers        = {}
_subscription_keys  = set()


def subscribe(event, handler):
    _subscribers.setdefault(event, []).append(handler)
    print(f"🔗 Subscribed: {event} -> {handler.__name__}")


def subscribe_once(event, handler):
    """Idempotent subscribe — no-op if already registered (prevents double-bind on reload)."""
    key = f"{event}_{handler.__name__}"
    if key in _subscription_keys:
        return
    _subscription_keys.add(key)
    subscribe(event, handler)


def publish(event, data=None):
    for h in _subscribers.get(event, []):
        try:
            h(data)
        except Exception as e:
            print(f"❌ Event error [{event}]:", e)
