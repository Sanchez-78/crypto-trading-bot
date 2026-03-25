import time

print("🚀 BOT STARTING...")


# =========================
# FIREBASE
# =========================
from src.services.firebase_client import init_firebase

init_firebase()


# =========================
# LOAD SERVICES
# =========================
from src.services.market_data import start_market_stream

import src.services.signal_generator
import src.services.trade_executor
import src.services.portfolio_manager
from src.services.portfolio_manager import process_portfolio

import src.services.evaluator
import src.services.performance_tracker

import src.services.learning_event
from src.services.learning_event import get_metrics, bootstrap_learning


print("⚙️ Bootstrapping learning from DB...")
bootstrap_learning()

print("✅ SYSTEM READY\n")


def main():
    start_market_stream()

    tick = 0

    while True:
        process_portfolio()

        tick += 1

        if tick % 10 == 0:
            metrics = get_metrics()

            print("\n📊 STATUS")
            print(f"Trades: {metrics['trades']}")
            print(f"Winrate: {metrics['winrate']:.2f}")
            print(f"Profit: {metrics['profit']:.4f}")

        time.sleep(1)


if __name__ == "__main__":
    main()