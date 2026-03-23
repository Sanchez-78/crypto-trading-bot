import requests
import time

from src.core.event_bus import event_bus
from src.core.events import PRICE_TICK

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

BINANCE_URL = "https://api.binance.com/api/v3/ticker/price"


def fetch_prices():
    data = requests.get(BINANCE_URL).json()

    prices = {}
    for item in data:
        if item["symbol"] in SYMBOLS:
            prices[item["symbol"]] = float(item["price"])

    return prices


def build_market_data(prices, prev_prices):
    market = {}

    for symbol, price in prices.items():
        prev = prev_prices.get(symbol, price)

        trend = "UP" if price > prev else "DOWN"
        volatility = abs(price - prev) / prev if prev != 0 else 0

        market[symbol.replace("USDT", "")] = {
            "price": price,
            "trend": trend,
            "volatility": volatility
        }

    return market


def run():
    print("🌐 MARKET DATA SERVICE STARTED")

    prev_prices = {}

    while True:
        try:
            prices = fetch_prices()
            market_data = build_market_data(prices, prev_prices)

            print("📡 REAL MARKET:", market_data)

            event_bus.publish(PRICE_TICK, market_data)

            prev_prices = prices

            time.sleep(5)

        except Exception as e:
            print("❌ Market data error:", e)
            time.sleep(2)