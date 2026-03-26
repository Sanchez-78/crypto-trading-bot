from src.core.event_bus import subscribe
from src.services.learning_event import update_metrics
from src.services.firebase_client import save_batch
import time, random

BATCH = []

def handle_signal(signal):
    price = signal["price"]

    size = min(0.1, signal["confidence"] * 0.2)

    move = random.gauss(0, 0.003)
    profit = move * size

    if signal["action"] == "SELL":
        profit *= -1

    result = "WIN" if profit > 0 else "LOSS"

    trade = {
        **signal,
        "profit": profit,
        "result": result,
        "timestamp": time.time()
    }

    update_metrics(signal, trade)

    BATCH.append(trade)
    if len(BATCH) >= 10:
        save_batch(BATCH)
        BATCH.clear()

subscribe("signal_created", handle_signal)