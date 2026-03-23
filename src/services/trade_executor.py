from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED, TRADE_OPENED
import random
import uuid
import time


def on_signal(signal):
    print("🔥 TRADE EXECUTOR TRIGGERED")

    trade = {
        "id": str(uuid.uuid4()),

        "symbol": signal["symbol"],
        "action": signal["action"],
        "confidence": signal["confidence"],

        "entry_price": random.uniform(100, 50000),
        "exit_price": None,

        "status": "OPEN",
        "risk": 0.01,

        "result": None,
        "profit": 0,

        "timestamp": time.time()
    }

    print("💰 TRADE EXECUTED:", trade)

    event_bus.publish(TRADE_EXECUTED, trade)
    event_bus.publish(TRADE_OPENED, trade)


event_bus.subscribe(SIGNAL_CREATED, on_signal)

print("💰 Trade Executor READY")