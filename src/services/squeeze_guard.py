import requests
import time

_cache_time = 0.0
_cached_rates = {}
CACHE_DURATION = 900  # 15 minut (funding data se moc rychle nemeni)

def get_funding_rates():
    global _cache_time, _cached_rates
    
    if time.time() - _cache_time < CACHE_DURATION and _cached_rates:
        return _cached_rates
        
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=5)
        if r.status_code == 200:
            data = r.json()
            rates = {}
            for item in data:
                rates[item["symbol"]] = float(item.get("lastFundingRate", 0.0))
            
            _cached_rates = rates
            _cache_time = time.time()
            return _cached_rates
    except Exception as e:
        print(f"⚠️ Squeeze Guard error: {e}")
        
    return _cached_rates

def is_safe_long(symbol: str) -> bool:
    """
    Vrátí False, pokud je trh nebezpečný pro LONGing.
    Trh je nebezpečný, když drtivá většina lidí používá páku na nákup, což nutí Funding Rate jít do extrémů (> 0.05% za 8H).
    Při long squeeze by náš spotový nákup okamžitě zasáhl likvidační knot do záporu.
    """
    rates = get_funding_rates()
    rate = rates.get(symbol, 0.0)
    
    # 0.05% za 8h = 54% p.a. -> Obrovská pravděpodobnost margin-call kaskády (Squeeze dolů)
    if rate >= 0.0005:
        return False
    return True

def is_safe_short(symbol: str) -> bool:
    """
    Vrátí False, pokud je funding rate extrémně negativní (< -0.05%), hrozí Short Squeeze (vystřelení nahoru).
    V našem SPOT botovi sice jen prodáváme existující zisk, ale pro celistvost logiky by se neměly brát shortové short-lived signály.
    """
    rates = get_funding_rates()
    rate = rates.get(symbol, 0.0)
    
    if rate <= -0.0005:
        return False
    return True
