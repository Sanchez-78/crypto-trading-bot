import requests, time
from src.core.event_bus import publish

SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]

def start():
    print("📡 MARKET LIVE")

    while True:
        for s in SYMBOLS:
            try:
                r = requests.get(
                    "https://api.binance.com/api/v3/ticker/price",
                    params={"symbol": s},
                    timeout=2
                )
                p = float(r.json()["price"])
                publish("price_tick", {"symbol": s, "price": p})
            except:
                pass

        time.sleep(2)