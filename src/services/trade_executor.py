from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED, TRADE_OPENED

import random
import uuid
import time

# 🔥 IMPORT LEARNING STATUS
from bot2.learning_event import is_ready, AUTO_TRADE_ENABLED


# =========================
# CONFIG
# =========================
MIN_CONFIDENCE = 0.6


def on_signal(signal):
    print("🔥 TRADE EXECUTOR TRIGGERED")

    # =========================
    # AUTO TRADE CONTROL
    # =========================
    if AUTO_TRADE_ENABLED:
        if not is_ready():
            print("⛔ SKIP: bot not ready")
            return

        if signal["confidence"] < MIN_CONFIDENCE:
            print("⛔ SKIP: low confidence")
            return

    # =========================
    # CREATE TRADE
    # =========================
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

print("💰 Trade Executor READY (AUTO MODE)")