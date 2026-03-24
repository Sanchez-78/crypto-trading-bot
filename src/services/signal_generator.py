from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED

from src.services.learning_event import select_action

print("📡 SIGNAL GENERATOR READY")


def generate_signal(data):
    price = data.get("price")

    if price is None:
        print("❌ Missing price in data:", data)
        return

    # =========================
    # FEATURES
    # =========================
    features = {
        "ema_short": data.get("ema_short"),
        "ema_long": data.get("ema_long"),
        "rsi": data.get("rsi"),
        "volatility": data.get("volatility")
    }

    # =========================
    # AI DECISION (bandit)
    # =========================
    action = select_action(features)

    signal = {
        "symbol": data.get("symbol", "BTCUSDT"),
        "action": action,
        "confidence": 0.6,
        "price": price,
        "features": features
    }

    print("📡 SIGNAL:", signal)

    event_bus.publish(SIGNAL_CREATED, signal)


# =========================
# EVENT SUBSCRIBE
# =========================
event_bus.subscribe(PRICE_TICK, generate_signal)