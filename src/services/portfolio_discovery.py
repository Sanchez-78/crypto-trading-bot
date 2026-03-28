import requests
import time

BASE_SYMBOLS = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]

# Caches the active symbols to avoid aggressive polling
_cached_symbols = []
_last_update    = 0.0
UPDATE_INTERVAL = 300   # 5 minut (Alpha Discovery: Volume Shock Hunter)

def get_active_symbols(top_n=5) -> list[str]:
    """
    Returns BASE_SYMBOLS + top N altcoins by 24h volume and price momentum.
    Excludes stablecoins and leverages (UP/DOWN/BULL/BEAR).
    """
    global _cached_symbols, _last_update
    
    if _cached_symbols and (time.time() - _last_update < UPDATE_INTERVAL):
        return _cached_symbols

    SYMBOLS = list(BASE_SYMBOLS)
    print("🌍 Portfolio Discovery: Hledám Top Mince na Binance...")
    
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=10)
        data = r.json()
        
        # Filtr: Musí končit na USDT, nesmí to být stablecoin nebo pákový token
        candidates = []
        for tick in data:
            sym = tick["symbol"]
            if not sym.endswith("USDT"): continue
            
            # Exclude stablecoins and weird tokens
            invalid_substrings = ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT", "USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "EURUSDT"]
            if any(x in sym for x in invalid_substrings):
                continue
                
            if sym in BASE_SYMBOLS:
                continue
                
            vol  = float(tick["quoteVolume"])  # Volume in USDT
            pct  = float(tick["priceChangePercent"])
            last = float(tick["lastPrice"])
            
            if vol > 10_000_000 and last > 0.001:  # Min $10M denní volume
                candidates.append({
                    "symbol": sym,
                    "vol": vol,
                    "abs_pct": abs(pct)
                })
                
        # Získáme nejvolatilnější mince z těch, které mají největší obrat (top 50 by vol)
        candidates.sort(key=lambda x: x["vol"], reverse=True)
        top_liquidity = candidates[:50]
        
        # Z nejlikvidnějších 50 vybereme top 5 podle volatility
        top_liquidity.sort(key=lambda x: x["abs_pct"], reverse=True)
        
        added = [c["symbol"] for c in top_liquidity[:top_n]]
        
        # Dynamický warmup pro minci chycenou během letu
        try:
            from src.services.signal_generator import warmup, prices
            new_syms = [s for s in added if s not in prices and s not in BASE_SYMBOLS]
            if new_syms:
                print(f"🔥 Alpha Discovery detekoval Volume Shock! Žhavím zaměřovače: {new_syms}")
                warmup(new_syms, candles=80)
        except Exception as e:
            print(f"⚠️ Alpha Discovery warmup chyba: {e}")

        SYMBOLS.extend(added)
        
        print(f"🌍 Discovery přidáno: {', '.join(added)}")
        
        _cached_symbols = SYMBOLS
        _last_update = time.time()
        return SYMBOLS
        
    except Exception as e:
        print(f"🌍 Discovery chyba (Fallback na BASE): {e}")
        return BASE_SYMBOLS

if __name__ == "__main__":
    print(get_active_symbols())
