from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED, TRADE_OPENED
import random


def on_signal(signal):
    print("🔥 TRADE EXECUTOR TRIGGERED")

    trade = {
        "symbol": signal["symbol"],
        "action": signal["action"],
        "confidence": signal["confidence"],
        "price": random.uniform(100, 50000)
    }

    print("💰 TRADE EXECUTED:", trade)

    # 🔥 publish BOTH (kompatibilita)
    event_bus.publish(TRADE_EXECUTED, trade)
    event_bus.publish(TRADE_OPENED, trade)


event_bus.subscribe(SIGNAL_CREATED, on_signal)

print("💰 Trade Executor READY")