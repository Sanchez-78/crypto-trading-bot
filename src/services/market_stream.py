import requests, time
from src.core.event_bus import publish
from src.services.learning_event import track_price
from src.services.portfolio_discovery import get_active_symbols

def start():
    print("📡 MARKET LIVE")

    while True:
        for s in get_active_symbols():
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
