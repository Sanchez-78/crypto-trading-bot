import sys
import os
import time
from threading import Thread

# =========================
# FIX PATH
# =========================
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

print("🚀 EVENT DRIVEN SYSTEM STARTED")

# =========================
# IMPORT EVENT HANDLERS
# =========================
import bot1.execution_event
import src.services.portfolio_event
import src.services.evaluator_event
import bot2.learning_event
import src.services.config_event

# =========================
# IMPORT PRICE FEED
# =========================
from src.services.price_feed import price_feed

# =========================
# SPUŠTĚNÍ FEEDU V THREADU
# =========================
Thread(target=price_feed, daemon=True).start()

# =========================
# Hlavní smyčka
# =========================
while True:
    time.sleep(1)  # lepší než "pass", dává šanci threadům běžet