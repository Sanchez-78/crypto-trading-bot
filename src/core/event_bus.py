# =========================
# SIMPLE EVENT BUS (STABLE)
# =========================

_subscribers = {}


def subscribe(event_name, handler):
    if event_name not in _subscribers:
        _subscribers[event_name] = []

    _subscribers[event_name].append(handler)
    print(f"🔗 Subscribed to {event_name}: {handler.__name__}")


def publish(event_name, data=None):
    handlers = _subscribers.get(event_name, [])

    if not handlers:
        print(f"⚠️ No listeners for {event_name}")
        return

    for h in handlers:
        try:
            h(data)
        except Exception as e:
            print(f"❌ Handler error in {event_name}:", e)


# OPTIONAL (debug)
def get_subscribers():
    return _subscribers