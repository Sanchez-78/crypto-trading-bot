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
# LOAD SERVICES
# =========================
print("⚙️ Loading services...")

from src.services.market_data import start_market_stream

import src.services.signal_generator
import src.services.trade_executor
import src.services.portfolio_manager
from src.services.portfolio_manager import process_portfolio

import src.services.evaluator
import src.services.performance_tracker

import src.services.learning_event
from src.services.learning_event import get_metrics

print("✅ ALL SERVICES READY\n")


# =========================
# STATUS PRINT
# =========================
def print_bot_status(metrics):
    print("\n🤖 BOT STATUS")

    trades = metrics.get("trades", 0)
    winrate = metrics.get("winrate", 0)

    if trades < 5:
        print("🟡 WARMUP (sbírá data)")
    elif winrate < 0.4:
        print("🔴 LEARNING (slabá strategie)")
    else:
        print("🟢 READY (profitabilní)")

    print(f"Trades: {trades}")
    print(f"Winrate: {winrate:.2f}")


def print_progress(metrics):
    trades = metrics.get("trades", 0)

    progress = min(trades / 100, 1.0)
    bars = int(progress * 20)

    print("\n🧠 Learning Progress:")
    print("[" + "█" * bars + "-" * (20 - bars) + f"] {int(progress * 100)}%")


def print_performance(metrics):
    print("\n💰 PERFORMANCE")

    print(f"Profit: {metrics.get('profit', 0):.4f}")
    print(f"Wins: {metrics.get('wins', 0)}")
    print(f"Losses: {metrics.get('losses', 0)}")
    print(f"Loss streak: {metrics.get('loss_streak', 0)}")


# =========================
# MAIN LOOP
# =========================
def main():
    print("🟢 BOT RUNNING (REAL DATA MODE)\n")

    tick = 0

    # start market stream (thread)
    start_market_stream()

    while True:
        try:
            # =========================
            # PROCESS PORTFOLIO
            # =========================
            process_portfolio()

            tick += 1

            # =========================
            # PRINT METRICS
            # =========================
            if tick % 10 == 0:
                metrics = get_metrics()

                print("\n============================")

                print_bot_status(metrics)
                print_progress(metrics)
                print_performance(metrics)

                print("\n============================\n")

                # =========================
                # FIREBASE SAVE
                # =========================
                if db:
                    try:
                        save_bot_stats(metrics)
                        print("☁️ Stats saved to Firebase")
                    except Exception as e:
                        print("⚠️ Firebase save error:", e)

            time.sleep(1)

        except Exception as e:
            print("❌ MAIN LOOP ERROR:", e)
            time.sleep(2)


# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    main()