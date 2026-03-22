import time
import random

from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK


def price_feed():
    while True:
        data = {
            "price": 50000 + random.randint(-100, 100),
            "trend": random.choice(["UP", "DOWN"]),
            "volatility": random.random(),
            "atr_m15": random.uniform(0.0005, 0.002)
        }

        event_bus.publish(PRICE_TICK, data)

        time.sleep(1)