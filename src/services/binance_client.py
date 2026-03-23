import time
import requests
from config import CANDLE_LIMIT

BASE_URLS = [
    "https://api.binance.com/api/v3/klines",
    "https://api.binance.us/api/v3/klines",
]


def fetch_candles(symbol: str, interval: str) -> list[dict]:
    """Fetch OHLCV candles from Binance."""

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": CANDLE_LIMIT,
    }

    data = None
    for url in BASE_URLS:
        data = _safe_request(url, params)
        if data:
            break

    if not data:
        return []

    candles = []
    for c in data:
        try:
            candles.append({
                "open_time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            })
        except (ValueError, IndexError):
            continue

    return candles


def _safe_request(url: str, params: dict, retries: int = 3, delay: int = 2):
    """Retry wrapper for API calls."""

    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                return response.json()

            print(f"Binance API error: {response.status_code}")

        except requests.RequestException as e:
            print(f"Request failed: {e}")

        time.sleep(delay)

    print("Failed to fetch data from Binance after retries.")
    return None