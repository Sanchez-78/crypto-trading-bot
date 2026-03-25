import time

from src.core.event_bus import EventBus
from src.services.firebase_client import init_firebase
from src.services.learning_event import get_metrics
from src.services.realtime_decision_engine import evaluate_signal

# auto registrace modulů
import src.services.signal_generator
import src.services.trade_executor

print("🚀 BOT STARTING...")


# =========================
# INIT
# =========================
def main():
    try:
        print("🔥 INIT FIREBASE...")
        init_firebase()
        print("🔥 Firebase ready")

        print("🧠 Loading systems...")

        last_status = 0

        # =========================
        # MAIN LOOP
        # =========================
        while True:
            time.sleep(2)

            # fake market data (zatím)
            symbol = random_symbol()
            price = random_price()

            signal = {
                "symbol": symbol,
                "action": random_action(),
                "price": price,
                "confidence": 0.6,
                "features": generate_features(price)
            }

            # =========================
            # DECISION ENGINE
            # =========================
            signal = evaluate_signal(signal)

            if signal:
                from src.core.event_bus import publish
                publish("signal_created", signal)

            # =========================
            # STATUS PRINT
            # =========================
            if time.time() - last_status > 10:
                last_status = time.time()
                print_status()

    except Exception as e:
        print("💥 CRASH:", e)


# =========================
# HELPERS
# =========================
import random

def random_symbol():
    return random.choice(["BTCUSDT", "ETHUSDT", "ADAUSDT"])


def random_action():
    return random.choice(["BUY", "SELL"])


def random_price():
    return random.uniform(25000, 35000)


def generate_features(price):
    return {
        "ema_short": price * random.uniform(0.99, 1.01),
        "ema_long": price * random.uniform(0.98, 1.02),
        "rsi": random.uniform(20, 80),
        "volatility": random.uniform(0.001, 0.02)
    }


# =========================
# STATUS
# =========================
def print_status():
    m = get_metrics()

    print("\n📊 ===== BOT STATUS =====")
    print(f"Trades: {m.get('trades', 0)}")
    print(f"Winrate: {m.get('winrate', 0)*100:.2f}%")
    print(f"Profit: {m.get('profit', 0)}")
    print(f"Confidence: {m.get('confidence', 0)}")
    print(f"Learning score: {m.get('learning_score', 0)}")
    print(f"READY: {'✅ YES' if m.get('ready') else '❌ NO'}")
    print("========================\n")


# =========================
# RUN
# =========================
if __name__ == "__main__":
    main()