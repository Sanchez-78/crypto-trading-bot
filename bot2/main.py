import time
import traceback
import random

print("🚨 MAIN START")

# =========================
# CORE
# =========================
from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

# =========================
# SERVICES (KRITICKÉ !!!)
# =========================
import src.services.signal_generator   # 👈 registruje PRICE_TICK
import src.services.trade_executor     # 👈 registruje SIGNAL_CREATED
import src.services.evaluator          # 👈 registruje TRADE_CLOSED
import src.services.portfolio_manager  # (pokud máš)

# =========================
# LEARNING + DB
# =========================
from src.services.learning_event import get_metrics, is_ready
from src.services.firebase_client import init_firebase

print("🚨 SERVICES LOADED")


# =========================
# FAKE MARKET (nech zatím)
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

    print(f"📈 MARKET TICK: {round(price, 2)}")

    event_bus.publish(PRICE_TICK, data)


# =========================
# MAIN
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

        # 🔥 DEBUG: ověř listeners
        event_bus.debug_listeners()

        while True:
            try:
                fake_market_tick()

                metrics = get_metrics()

                if metrics:
                    print("\n🧠 ===== LEARNING =====")
                    print(f"Trades: {metrics.get('trades')}")
                    print(f"Winrate: {round(metrics.get('winrate', 0)*100, 2)}%")
                    print(f"Epsilon: {metrics.get('epsilon')}")

                    if is_ready():
                        print("🚀 READY")
                    else:
                        print("📚 LEARNING...")

                    print("======================\n")

                time.sleep(2)

            except Exception as e:
                print("❌ LOOP ERROR:", e)
                traceback.print_exc()
                time.sleep(5)

    except Exception as e:
        print("💥 MAIN CRASH:", e)
        traceback.print_exc()