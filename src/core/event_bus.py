_subscribers = {}

def subscribe(event, handler):
    _subscribers.setdefault(event, []).append(handler)
    print(f"🔗 Subscribed: {event} -> {handler.__name__}")

def publish(event, data=None):
    for h in _subscribers.get(event, []):
        try:
            h(data)
        except Exception as e:
            print(f"❌ Event error [{event}]:", e)