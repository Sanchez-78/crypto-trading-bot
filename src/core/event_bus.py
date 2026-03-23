class EventBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event, fn):
        if event not in self.subscribers:
            self.subscribers[event] = []

        self.subscribers[event].append(fn)
        print(f"✅ SUBSCRIBED: {event} -> {fn.__name__}")

    def publish(self, event, data):
        print(f"📤 EVENT: {event}")

        if event not in self.subscribers:
            print(f"⚠️ No subscribers for {event}")
            return

        for fn in self.subscribers[event]:
            try:
                fn(data)
            except Exception as e:
                print(f"❌ Event error [{event}]:", e)


event_bus = EventBus()