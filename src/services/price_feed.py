import time
import random
from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

SYMBOLS = ["BTCUSDT", "ADAUSDT", "ETHUSDT"]

def price_feed():
    last_price = {s: 50000 if s=="BTCUSDT" else 1 if s=="ADAUSDT" else 4000 for s in SYMBOLS}

    while True:
        data = {}
        for s in SYMBOLS:
            delta = random.uniform(-0.05, 0.05)
            price = last_price[s] * (1 + delta)
            last_price[s] = price
            trend = "UP" if delta > 0 else "DOWN"
            volatility = abs(delta)

            data[s] = {
                "price": price,
                "trend": trend,
                "volatility": volatility
            }

        print(f"🔹 PRICE UPDATE: {data}")
        event_bus.publish(PRICE_TICK, data)
        time.sleep(1)