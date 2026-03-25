import random
import time
from config import SYMBOLS
from src.core.event_bus import publish


def get_fake_price(symbol):
    base = {
        "BTCUSDT": 30000,
        "ETHUSDT": 2000,
        "ADAUSDT": 0.5
    }.get(symbol, 100)

    return base + random.uniform(-100, 100)


def get_trend():
    return random.choice(["UP", "DOWN"])


def get_volatility():
    return random.uniform(0.0005, 0.01)


def start_market_stream():
    print("📡 MARKET STREAM STARTED (MULTI-ASSET)")

    while True:
        for symbol in SYMBOLS:
            price = get_fake_price(symbol)

            data = {
                "symbol": symbol,
                "price": price,
                "trend": get_trend(),
                "volatility": get_volatility()
            }

            print(f"📈 MARKET: {data}")

            publish("price_tick", data)

        time.sleep(1)