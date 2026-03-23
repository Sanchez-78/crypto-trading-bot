import sys
import time
from config import SYMBOLS, INTERVAL

from src.services.firebase_client import init_firebase, save_signal, get_db
from src.services.binance_client import fetch_candles
from src.services.feature_extractor import extract_features
from src.services.evaluator import evaluate_signals
from src.services.market_data import get_all_prices


def run_signals():
    print("📡 MODE: signals")

    prices = get_all_prices()
    saved_signals = []

    for symbol in SYMBOLS:
        print(f"\n🔹 {symbol}")

        candles = fetch_candles(symbol, INTERVAL)
        price   = prices.get(symbol, 0)

        if not candles:
            # Bez svíček použij jen cenu z CoinGecko
            if price <= 0:
                print(f"  ❌ No candles or price for {symbol}")
                continue

            signal     = "HOLD"
            confidence = 0.5
            atr        = 0.0
            trend      = "UNKNOWN"
        else:
            features = extract_features(candles)
            if not features:
                print(f"  ❌ No features for {symbol}")
                continue

            if price <= 0:
                price = candles[-1]["close"]

            atr   = features.get("atr", 0)
            macd  = features.get("macd", 0)
            rsi   = features.get("rsi", 50)
            trend = "UP" if macd > 0 else "DOWN"

            if trend == "UP" and rsi < 70:
                signal     = "BUY"
                confidence = min(0.95, 0.55 + abs(macd) * 10)
            elif trend == "DOWN" and rsi > 30:
                signal     = "HOLD"
                confidence = 0.5
            else:
                signal     = "HOLD"
                confidence = 0.5

        print(f"  signal={signal} confidence={confidence:.2f} price={price:.4f}")

        doc_id = save_signal({
            "symbol":     symbol,
            "signal":     signal,
            "confidence": confidence,
            "price":      price,
            "atr":        atr,
            "trend":      trend,
            "strategy":   "TREND",
            "regime":     "BULL_TREND" if trend == "UP" else "RANGE",
            "evaluated":  False,
            "timestamp":  time.time(),
        })

        if doc_id:
            print(f"  ✅ saved: {doc_id}")
            saved_signals.append({"symbol": symbol, "signal": signal, "price": price})
        else:
            print(f"  ⚠️ save failed")

    # Zapiš stav běhu do metrics/latest (merge — nemazat learning data)
    _write_run_status(saved_signals, prices)


def _write_run_status(saved_signals, prices):
    """Zapíše základní info o posledním běhu do metrics/latest (merge)."""
    db = get_db()
    if db is None:
        return
    try:
        prices_map = {s["symbol"]: s["price"] for s in saved_signals}
        db.collection("metrics").document("latest").set({
            "last_run":      time.time(),
            "signals_saved": len(saved_signals),
            "prices":        prices_map,
            "timestamp":     time.time(),
        }, merge=True)
        print(f"\n📊 metrics updated ({len(saved_signals)} signals)")
    except Exception as e:
        print(f"⚠️ metrics write error: {e}")


def run_evaluate():
    print("📊 MODE: evaluate")

    for symbol in SYMBOLS:
        print(f"\n🔎 evaluating {symbol}")
        evaluate_signals(symbol)

    print("✅ evaluation done")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "signals"

    init_firebase()

    if mode == "evaluate":
        run_evaluate()
    else:
        run_signals()
