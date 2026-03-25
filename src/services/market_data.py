import requests
import time
from config import SYMBOLS
from src.core.event_bus import publish

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price"


def get_price(symbol):
    try:
        res = requests.get(BINANCE_URL, params={"symbol": symbol}, timeout=5)
        data = res.json()
        return float(data["price"])
    except Exception as e:
        print(f"❌ Price error {symbol}:", e)
        return None


def get_volatility(symbol, prices):
    if len(prices) < 2:
        return 0

    return abs(prices[-1] - prices[-2]) / prices[-2]


price_history = {}


def start_market_stream():
    print("📡 LIVE MARKET (BINANCE)")

    while True:
        for symbol in SYMBOLS:
            price = get_price(symbol)

            if price is None:
                continue

            if symbol not in price_history:
                price_history[symbol] = []

            price_history[symbol].append(price)

            if len(price_history[symbol]) > 50:
                price_history[symbol] = price_history[symbol][-50:]

            volatility = get_volatility(symbol, price_history[symbol])

            data = {
                "symbol": symbol,
                "price": price,
                "volatility": volatility
            }

            print(f"📈 {symbol}: {price:.2f} vol={volatility:.4f}")

            publish("price_tick", data)

        time.sleep(2)  # 🔥 snížení loadu