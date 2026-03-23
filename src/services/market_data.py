import requests
import time

_cache = None
_last_fetch = 0
CACHE_TTL = 30


def get_all_prices():
    global _cache, _last_fetch

    if _cache and time.time() - _last_fetch < CACHE_TTL:
        return _cache

    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin,ethereum,cardano,solana,ripple",
            "vs_currencies": "usd"
        }

        r = requests.get(url, params=params, timeout=10)

        if r.status_code == 200:
            data = r.json()

            _cache = {
                "BTCUSDT": float(data.get("bitcoin",  {}).get("usd", 0)),
                "ETHUSDT": float(data.get("ethereum", {}).get("usd", 0)),
                "ADAUSDT": float(data.get("cardano",  {}).get("usd", 0)),
                "SOLUSDT": float(data.get("solana",   {}).get("usd", 0)),
                "XRPUSDT": float(data.get("ripple",   {}).get("usd", 0)),
            }

            # Vyfiltruj nuly
            _cache = {k: v for k, v in _cache.items() if v > 0}
            _last_fetch = time.time()
            return _cache

        if r.status_code == 429:
            print("⚠️ Rate limit, backing off...")
            time.sleep(3)

    except Exception as e:
        print("⚠️ Market data error:", e)

    if _cache:
        print("⚠️ Using cached prices")
        return _cache

    print("⚠️ Using fallback prices")
    return {
        "BTCUSDT": 60000,
        "ETHUSDT": 3000,
        "ADAUSDT": 0.5,
        "SOLUSDT": 150,
        "XRPUSDT": 0.55,
    }
