import requests, time
from src.core.event_bus import publish
from src.services.learning_event import track_price

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
                track_price(s, p)
                publish("price_tick", {"symbol": s, "price": p})
            except:
                pass

        time.sleep(2)
