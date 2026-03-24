import time
import traceback

print("🚨 MAIN START")

# =========================
# IMPORTS (SAFE DEBUG)
# =========================
try:
    from src.services.firebase_client import init_firebase
    print("✅ firebase_client OK")
except Exception as e:
    print("❌ firebase import failed:", e)

try:
    from src.services.learning_event import get_metrics, is_ready
    print("✅ learning_event OK")
except Exception as e:
    print("❌ learning_event import failed:", e)

try:
    from src.services.signal_generator import generate_signal
    print("✅ signal_generator OK")
except Exception as e:
    print("❌ signal_generator import failed:", e)

try:
    from src.services.evaluator import evaluate_trade
    print("✅ evaluator OK")
except Exception as e:
    print("❌ evaluator import failed:", e)

print("🚨 IMPORTS DONE")


# =========================
# MAIN FUNCTION
# =========================
def main():
    print("🚀 BOT STARTING...")

    try:
        # =========================
        # INIT FIREBASE
        # =========================
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

            except Exception as loop_error:
                print("❌ LOOP ERROR:", loop_error)
                traceback.print_exc()
                time.sleep(5)

    except Exception as e:
        print("💥 MAIN CRASH:", e)
        traceback.print_exc()