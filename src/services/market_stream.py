import requests, time
from src.core.event_bus import publish
from src.services.learning_event import track_price
from src.services.portfolio_discovery import get_active_symbols

def start():
    print("📡 MARKET LIVE (Level 2 OBI)")

    while True:
        for s in get_active_symbols():
            try:
                r = requests.get(
                    "https://api.binance.com/api/v3/ticker/bookTicker",
                    params={"symbol": s},
                    timeout=2
                )
                data = r.json()
                
                bid_price = float(data["bidPrice"])
                ask_price = float(data["askPrice"])
                bid_qty   = float(data["bidQty"])
                ask_qty   = float(data["askQty"])
                
                # Střední cena je stabilnější než 'last traded price'
                p = (bid_price + ask_price) / 2.0
                
                # Order Book Imbalance (Volume Bid vs Volume Ask)
                vol_b = bid_price * bid_qty
                vol_a = ask_price * ask_qty
                
                total_vol = vol_b + vol_a
                obi = (vol_b - vol_a) / total_vol if total_vol > 0 else 0.0
                
                track_price(s, p)
                publish("price_tick", {"symbol": s, "price": p, "obi": obi})
            except:
                pass

        time.sleep(1)
