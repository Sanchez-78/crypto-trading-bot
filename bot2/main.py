from src.services.firebase_client import init_firebase
from src.services.learning_event import get_metrics, is_ready

# INIT FIREBASE
init_firebase()

print("🚀 BOT STARTED")

# =========================
# MAIN LOOP (příklad)
# =========================
import time

while True:
    try:
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

        time.sleep(10)

    except Exception as e:
        print("❌ MAIN LOOP ERROR:", e)
        time.sleep(5)