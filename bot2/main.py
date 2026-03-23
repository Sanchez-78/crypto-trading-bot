from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

from src.services.firebase_client import init_firebase

# 🔥 KLÍČOVÉ IMPORTY (pipeline)
import src.services.signal_generator
import src.services.trade_executor
import src.services.evaluator
import src.services.portfolio_event
import bot2.learning_event

import time
import random


def generate_market_data():
    symbols = ["BTC", "ETH", "ADA"]

    data = {}

    for s in symbols:
        data[s] = {
            "price": random.uniform(100, 50000),
            "trend": random.choice(["UP", "DOWN"]),
            "volatility": random.uniform(0.01, 0.05)
        }

    return data


def main():
    print("🔥 MAIN STARTED")

    init_firebase()

    print("📡 Event system running...\n")

    while True:
        try:
            market_data = generate_market_data()

            print("📈 TICK:", market_data)

            event_bus.publish(PRICE_TICK, market_data)

            time.sleep(1)

        except Exception as e:
            print("❌ MAIN LOOP ERROR:", e)
            time.sleep(5)