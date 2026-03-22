import sys
import os
from threading import Thread

# =========================
# 🔥 FIX PATH (KRITICKÉ)
# =========================
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

print("🚀 EVENT DRIVEN SYSTEM STARTED")

# =========================
# 🔥 IMPORTY = registrace eventů
# =========================
import bot1.execution_event
import src.services.portfolio_event
import src.services.evaluator_event
import bot2.learning_event
import src.services.config_event

from src.services.price_feed import price_feed


# =========================
# 🚀 MAIN
# =========================
def main():
    # price feed (později websocket)
    Thread(target=price_feed, daemon=True).start()

    # drží proces
    while True:
        pass


if __name__ == "__main__":
    main()