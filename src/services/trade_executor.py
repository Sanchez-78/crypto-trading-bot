from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED
import random


def on_signal(signal):
    trade = {
        "symbol": signal["symbol"],
        "action": signal["action"],
        "confidence": signal["confidence"],
        "price": random.uniform(100, 50000)
    }

    print("💰 TRADE EXECUTED:", trade)

    event_bus.publish(TRADE_EXECUTED, trade)


event_bus.subscribe(SIGNAL_CREATED, on_signal)

print("💰 Trade Executor READY")