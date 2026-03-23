# =========================
# IMPORTS
# =========================
print("🚀 BOOTING BOT...")

from src.services.firebase_client import init_firebase

# 🔥 INIT FIREBASE
db = init_firebase()

if not db:
    print("⚠️ DB NOT READY (bot poběží bez ukládání)")
else:
    print("✅ DB READY")


# =========================
# LOAD SERVICES (EVENT PIPELINE)
# =========================
import src.services.signal_generator
import src.services.trade_executor
import src.services.evaluator
import src.services.portfolio_event
import bot2.learning_event  # 🔥 důležité!

print("🔥 ALL SERVICES LOADED")


# =========================
# SIMULACE MARKETU
# =========================
from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

import time
import random


def generate_market_data():
    return {
        "BTC": {
            "trend": random.choice(["UP", "DOWN"]),
            "volatility": random.uniform(0.01, 0.05),
            "price": random.uniform(20000, 50000)
        },
        "ETH": {
            "trend": random.choice(["UP", "DOWN"]),
            "volatility": random.uniform(0.01, 0.05),
            "price": random.uniform(1000, 4000)
        }
    }


# =========================
# MAIN LOOP
# =========================
print("📈 START MARKET LOOP")

while True:
    try:
        market_data = generate_market_data()

        print("\n📈 TICK:", market_data)

        event_bus.publish(PRICE_TICK, market_data)

        time.sleep(5)  # 🔥 kontrola rychlosti (důležité kvůli writes)

    except Exception as e:
        print("❌ MAIN LOOP ERROR:", e)
        time.sleep(2)