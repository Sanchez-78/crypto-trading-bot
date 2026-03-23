import time, random
from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

SYMBOLS = ["BTCUSDT","ADAUSDT","ETHUSDT"]

last = {"BTCUSDT":50000,"ADAUSDT":1,"ETHUSDT":4000}

def price_feed():
    while True:
        data = {}

        for s in SYMBOLS:
            delta = random.uniform(-0.03,0.03)
            price = last[s]*(1+delta)
            last[s] = price

            data[s] = {
                "price": price,
                "trend": "UP" if delta>0 else "DOWN",
                "volatility": abs(delta)
            }

        print(f"\n🔹 PRICE {data}")
        event_bus.publish(PRICE_TICK,data)

        time.sleep(1)