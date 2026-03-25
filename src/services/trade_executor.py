from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED

from src.services.learning_event import is_ready

print("💰 TRADE EXECUTOR READY")


def handle_signal(signal):
    print("💰 TRADE EXECUTOR TRIGGERED")

    # =========================
    # VALIDACE
    # =========================
    if not isinstance(signal, dict):
        print("❌ Invalid signal:", signal)
        return

    symbol = signal.get("symbol")
    action = signal.get("action")
    price = signal.get("price")
    confidence = signal.get("confidence", 0)
    features = signal.get("features", {})

    if price is None:
        print("❌ Missing price in signal:", signal)
        return

    # =========================
    # MODE
    # =========================
    if not is_ready():
        print("📚 FORCE TRADE (learning mode)")
    else:
        print("🚀 REAL TRADE MODE")

    # =========================
    # TRADE OBJECT
    # =========================
    trade = {
        "symbol": symbol,
        "action": action,
        "price": price,
        "confidence": confidence,
        "features": features,
        "status": "OPEN"
    }

    print("💰 TRADE EXECUTED:", trade)

    # =========================
    # EVENT
    # =========================
    event_bus.publish(TRADE_EXECUTED, trade)


# ✅ JEDINÝ HANDLER
event_bus.subscribe(SIGNAL_CREATED, handle_signal)