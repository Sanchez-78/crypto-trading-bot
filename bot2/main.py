import time
import traceback
import random

print("🚨 MAIN START")

# =========================
# IMPORTS
# =========================
from src.services.firebase_client import init_firebase
from src.services.learning_event import get_metrics, is_ready

from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

print("🚨 IMPORTS DONE")


# =========================
# FAKE MARKET (DEBUG FEED)
# =========================
def fake_market_tick():
    price = random.uniform(30000, 35000)

    data = {
        "symbol": "BTCUSDT",
        "price": price,
        "ema_short": price * random.uniform(0.99, 1.01),
        "ema_long": price * random.uniform(0.99, 1.01),
        "rsi": random.uniform(10, 90),
        "volatility": random.uniform(0.001, 0.01)
    }

    print("📈 MARKET TICK:", round(price, 2))

    event_bus.publish(PRICE_TICK, data)


# =========================
# MAIN FUNCTION
# =========================
def main():
    print("🚀 BOT STARTING...")

    try:
        db = init_firebase()

        if db:
            print("🔥 DB READY")
        else:
            print("⚠️ DB NOT READY")

        print("🧠 LEARNING SYSTEM ACTIVE")

        # =========================
        # MAIN LOOP
        # =========================
        while True:
            try:
                # 🔥 GENERATE DATA
                fake_market_tick()

                # 📊 LEARNING STATUS
                metrics = get_metrics()

                if metrics:
                    print("\n🧠 ===== LEARNING STATUS =====")
                    print(f"Trades: {metrics.get('trades')}")
                    print(f"Winrate: {round(metrics.get('winrate', 0)*100, 2)}%")
                    print(f"Epsilon: {round(metrics.get('epsilon', 0), 4)}")

                    if is_ready():
                        print("🚀 BOT READY FOR TRADING")
                    else:
                        print("📚 BOT LEARNING...")

                    print("============================\n")

                time.sleep(2)

            except Exception as loop_error:
                print("❌ LOOP ERROR:", loop_error)
                traceback.print_exc()
                time.sleep(5)

    except Exception as e:
        print("💥 MAIN CRASH:", e)
        traceback.print_exc()