from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED
from src.services.learning_event import is_ready

print("💰 TRADE EXECUTOR READY")


def handle_signal(signal):
    print("💰 TRADE EXECUTOR TRIGGERED")

    try:
        if not isinstance(signal, dict):
            print("❌ Invalid signal:", signal)
            return

        trade = {
            "symbol": signal.get("symbol"),
            "action": signal.get("action"),
            "price": signal.get("price"),
            "confidence": signal.get("confidence", 0),
            "features": signal.get("features", {}),
            "status": "OPEN"
        }

        if trade["price"] is None:
            print("❌ Missing price in signal:", signal)
            return

        if not is_ready():
            print("📚 FORCE TRADE (learning mode)")
        else:
            print("🚀 REAL TRADE MODE")

        print("💰 TRADE EXECUTED:", trade)

        event_bus.publish(TRADE_EXECUTED, trade)

    except Exception as e:
        print("❌ handle_signal crash:", e)
        print("❌ SIGNAL:", signal)


event_bus.subscribe(SIGNAL_CREATED, handle_signal)