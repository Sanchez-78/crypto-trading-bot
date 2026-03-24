print("🧠 LOADING EVENT BUS...")

class EventBus:
    def __init__(self):
        self.listeners = {}
        print("🧠 EventBus created")

    # =========================
    # SUBSCRIBE
    # =========================
    def subscribe(self, event_type, handler):
        if event_type not in self.listeners:
            self.listeners[event_type] = []

        self.listeners[event_type].append(handler)

        print(f"🔗 Subscribed to {event_type}: {handler.__name__}")

    # =========================
    # PUBLISH
    # =========================
    def publish(self, event_type, data):
        if event_type not in self.listeners:
            print(f"⚠️ No listeners for {event_type}")
            return

        print(f"📣 EVENT: {event_type}")

        for handler in self.listeners[event_type]:
            try:
                handler(data)
            except Exception as e:
                print(f"❌ Handler error in {handler.__name__}: {e}")

    # =========================
    # DEBUG
    # =========================
    def debug_listeners(self):
        print("🧠 CURRENT LISTENERS:")
        for event, handlers in self.listeners.items():
            print(f"{event}: {[h.__name__ for h in handlers]}")


# =========================
# 🔥 GLOBAL INSTANCE (KRITICKÉ)
# =========================
event_bus = EventBus()

print("🧠 EVENT BUS INITIALIZED:", event_bus)