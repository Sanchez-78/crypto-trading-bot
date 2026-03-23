import sys
import os
import time
from threading import Thread

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

print("🚀 EVENT DRIVEN SYSTEM STARTED")

# import event handlers
import bot1.execution_event
import src.services.portfolio_event
import src.services.evaluator_event
import bot2.learning_event
import src.services.config_event

# start price feed in a separate thread
from src.services.price_feed import price_feed
Thread(target=price_feed, daemon=True).start()

# keep main thread alive
while True:
    time.sleep(1)