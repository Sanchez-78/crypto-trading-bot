class EventBus:

    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event, handler):
        self.subscribers.setdefault(event, []).append(handler)

    def publish(self, event, data):
        print(f"\n📡 EVENT: {event}")

        if event not in self.subscribers:
            print(f"⚠️ No subscribers for {event}")
            return

        for handler in self.subscribers[event]:
            try:
                handler(data)
            except Exception as e:
                print(f"❌ Event error [{event}]: {e}")


event_bus = EventBus()