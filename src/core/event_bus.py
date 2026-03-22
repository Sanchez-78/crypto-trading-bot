from collections import defaultdict


class EventBus:
    def __init__(self):
        self.listeners = defaultdict(list)

    def subscribe(self, event_type, handler):
        self.listeners[event_type].append(handler)

    def publish(self, event_type, data=None):
        if event_type not in self.listeners:
            return

        for handler in self.listeners[event_type]:
            try:
                handler(data)
            except Exception as e:
                print(f"❌ Event error [{event_type}]: {e}")


event_bus = EventBus()