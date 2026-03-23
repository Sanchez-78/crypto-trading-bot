import time
import random
from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

# =========================
# SYMBOLY, které chceme sledovat
# =========================
SYMBOLS = ["BTCUSDT", "ADAUSDT", "ETHUSDT"]

# =========================
# PRICE FEED (simulace)
# =========================
def price_feed():
    while True:
        # generujeme náhodné ceny
        data = {}
        for s in SYMBOLS:
            if s == "BTCUSDT":
                price = 50000 + random.randint(-100, 100)
            elif s == "ADAUSDT":
                price = 1 + random.uniform(-0.05, 0.05)
            elif s == "ETHUSDT":
                price = 4000 + random.randint(-20, 20)
            data[s] = price

        # debug log
        print(f"🔹 PRICE UPDATE: {data}")

        # publish do event bus
        event_bus.publish(PRICE_TICK, data)

        # 1 sekunda mezi ticky
        time.sleep(1)