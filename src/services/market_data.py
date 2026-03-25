from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

import random
import threading
import time

print("📡 MARKET STREAM READY")


def market_loop():
    price = 30000

    while True:
        price += random.uniform(-50, 50)

        data = {
            "symbol": "BTCUSDT",
            "price": round(price, 2),
            "trend": "UP" if random.random() > 0.5 else "DOWN",
            "volatility": random.random()
        }

        print("📈 MARKET:", data)

        event_bus.publish(PRICE_TICK, data)

        time.sleep(1)


def start_market_stream():
    thread = threading.Thread(target=market_loop)
    thread.daemon = True
    thread.start()