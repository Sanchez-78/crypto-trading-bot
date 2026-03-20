import requests

BASE_URL = "https://api.bybit.com/v5/market/kline"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json"
}


def get_candles(symbol="BTCUSDT", interval="15", limit=100):
    try:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
            "category": "linear"
        }

        r = requests.get(
            BASE_URL,
            params=params,
            headers=HEADERS,
            timeout=10
        )

        if r.status_code != 200:
            print(f"❌ HTTP {r.status_code}")
            return []

        data = r.json()

        if "result" not in data:
            print("❌ Bybit error:", data)
            return []

        candles = []

        for c in data["result"]["list"]:
            candles.append({
                "time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5])
            })

        return candles[::-1]

    except Exception as e:
        print("❌ Market data error:", e)
        return []