# bot2/main.py

from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

from src.services.firebase_client import init_firebase

# 🔥 důležité – importy spouští subscribery
import src.services.portfolio_event
import bot2.learning_event

import time
import random


# =========================
# MOCK DATA (nebo real feed)
# =========================
def generate_market_data():
    symbols = ["BTC", "ETH", "ADA"]

    data = {}

    for s in symbols:
        price = random.uniform(100, 50000)
        vol = random.uniform(0.1, 1.0)

        data[s] = {
            "price": price,
            "volatility": vol
        }

    return data


# =========================
# MAIN LOOP
# =========================
def main():
    print("🔥 MAIN STARTED")

    # Firebase init
    init_firebase()

    print("📡 Event system running...\n")

    while True:
        try:
            market_data = generate_market_data()

            # publish prices
            event_bus.publish(PRICE_TICK, market_data)

            time.sleep(1)

        except Exception as e:
            print("❌ MAIN LOOP ERROR:", e)
            time.sleep(5)