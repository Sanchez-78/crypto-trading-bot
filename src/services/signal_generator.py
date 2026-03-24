from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED
from src.services.firebase_client import save_signal

import random

print("📡 Signal Generator READY")

MIN_CONFIDENCE = 0.55
FORCE_SIGNAL_EVERY = 5

tick_counter = 0
last_price = None


def generate_signal(price):
    global last_price

    if last_price is None:
        last_price = price
        return None

    change = (price - last_price) / last_price

    if change > 0.001:
        action = "BUY"
        confidence = min(0.6 + change * 10, 0.9)

    elif change < -0.001:
        action = "SELL"
        confidence = min(0.6 + abs(change) * 10, 0.9)

    else:
        action = None
        confidence = 0

    last_price = price

    if not action:
        return None

    return {
        "symbol": "BTC",
        "action": action,
        "confidence": confidence,
        "price": price
    }


def on_price_tick(data):
    global tick_counter

    tick_counter += 1

    print("📡 RAW DATA:", data)

    # 🔥 FIX: správné parsování multi-symbol dat
    if isinstance(data, dict) and "BTC" in data:
        price = data["BTC"].get("price")
    else:
        price = None

    print("📡 PRICE:", price)

    if price is None:
        print("❌ No valid price")
        return

    signal = generate_signal(price)

    if signal and signal["confidence"] >= MIN_CONFIDENCE:
        print("🚀 SIGNAL:", signal)

        save_signal(signal)
        event_bus.publish(SIGNAL_CREATED, signal)
        return

    # fallback
    if tick_counter % FORCE_SIGNAL_EVERY == 0:
        fallback_signal = {
            "symbol": "BTC",
            "action": random.choice(["BUY", "SELL"]),
            "confidence": 0.55,
            "price": price
        }

        print("⚠️ FALLBACK SIGNAL:", fallback_signal)

        save_signal(fallback_signal)
        event_bus.publish(SIGNAL_CREATED, fallback_signal)


event_bus.subscribe(PRICE_TICK, on_price_tick)