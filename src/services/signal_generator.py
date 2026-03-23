from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK, SIGNAL_CREATED
import random


def generate_signal(market_data):
    signals = []

    for symbol, data in market_data.items():
        action = "BUY" if data["trend"] == "UP" else "SELL"

        signal = {
            "symbol": symbol,
            "action": action,
            "confidence": random.uniform(0.5, 1.0)
        }

        signals.append(signal)

    return signals


def on_price_tick(market_data):
    print("🔥 SIGNAL GENERATOR TRIGGERED")

    signals = generate_signal(market_data)

    for s in signals:
        print("📡 SIGNAL:", s)
        event_bus.publish(SIGNAL_CREATED, s)


event_bus.subscribe(PRICE_TICK, on_price_tick)

print("📡 Signal Generator READY")