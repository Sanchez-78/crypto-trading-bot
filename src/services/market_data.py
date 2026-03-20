import requests

BASE_URL = "https://api.coingecko.com/api/v3/simple/price"


def get_all_prices():
    try:
        params = {
            "ids": "bitcoin,ethereum,cardano",
            "vs_currencies": "usd"
        }

        r = requests.get(BASE_URL, params=params, timeout=10)

        if r.status_code != 200:
            print("❌ HTTP error:", r.status_code)
            return {}

        data = r.json()

        return {
            "BTCUSDT": float(data["bitcoin"]["usd"]),
            "ETHUSDT": float(data["ethereum"]["usd"]),
            "ADAUSDT": float(data["cardano"]["usd"])
        }

    except Exception as e:
        print("❌ Price error:", e)
        return {}