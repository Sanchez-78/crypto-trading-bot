import time

print("🚀 Starting multi-symbol event-driven BOT SYSTEM")

# =========================
# FIREBASE
# =========================
try:
    from src.services.firebase_client import init_firebase, save_bot_stats
    db = init_firebase()
    print("🔥 Firebase initialized OK")
except Exception as e:
    print("⚠️ Firebase OFF:", e)
    db = None


# =========================
# LOAD CORE
# =========================
print("⚙️ Loading services...")

# MARKET (REALISTIC SIMULATION)
from src.services.market_data import start_market_stream

# SIGNAL (SMART)
import src.services.signal_generator

# TRADE
import src.services.trade_executor

# PORTFOLIO
import src.services.portfolio_manager
from src.services.portfolio_manager import process_portfolio

# EVALUATION
import src.services.evaluator

# LEARNING (bandit + scoring)
import src.services.learning_event
from src.services.learning_event import get_metrics

# PERFORMANCE
import src.services.performance_tracker

print("✅ ALL SERVICES READY\n")


# =========================
# MAIN LOOP
# =========================
def main():
    print("🟢 BOT RUNNING (REAL DATA MODE)\n")

    tick = 0

    # start market stream (thread / async style)
    start_market_stream()

    while True:
        try:
            # =========================
            # PORTFOLIO (close trades)
            # =========================
            process_portfolio()

            tick += 1

            # =========================
            # LEARNING METRICS
            # =========================
            if tick % 10 == 0:
                metrics = get_metrics()

                print("\n📊 LEARNING STATUS")
                print(f"Trades: {metrics['trades']}")
                print(f"Winrate: {metrics['winrate']:.2f}")
                print(f"Epsilon: {metrics['epsilon']:.4f}")

                # progress bar
                progress = int(metrics["progress"] * 20)
                print("🧠 [" + "█" * progress + "-" * (20 - progress) + "]")

                # Firebase log
                if db:
                    save_bot_stats(metrics)

            time.sleep(1)

        except Exception as e:
            print("❌ MAIN LOOP ERROR:", e)
            time.sleep(2)


# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    main()