import time
from threading import Thread

import bot1.execution_event
import src.services.portfolio_event
import src.services.evaluator_event
import bot2.learning_event

from src.services.price_feed import price_feed

print("🚀 SYSTEM START")

Thread(target=price_feed,daemon=True).start()

while True:
    time.sleep(1)