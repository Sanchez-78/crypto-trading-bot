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

    for symbol in SYMBOLS:
        print(f"\n🔹 {symbol}")

        candles = fetch_candles(symbol, INTERVAL)
        if not candles:
            print(f"  ❌ No candles for {symbol}")
            continue

        features = extract_features(candles)
        if not features:
            print(f"  ❌ No features for {symbol}")
            continue

        price = prices.get(symbol, candles[-1]["close"])
        atr = features.get("atr", 0)
        macd = features.get("macd", 0)
        trend = "UP" if macd > 0 else "DOWN"

        if trend == "UP":
            signal = "BUY"
            confidence = min(0.95, 0.55 + abs(macd) * 10)
        else:
            signal = "HOLD"
            confidence = 0.5

        print(f"  signal={signal} confidence={confidence:.2f} price={price:.4f}")

        doc_id = save_signal({
            "symbol": symbol,
            "signal": signal,
            "confidence": confidence,
            "price": price,
            "atr": atr,
            "trend": trend,
            "strategy": "TREND",
            "regime": "BULL_TREND" if trend == "UP" else "RANGE",
            "evaluated": False,
            "timestamp": time.time(),
        })

        if doc_id:
            print(f"  ✅ saved: {doc_id}")
        else:
            print(f"  ⚠️ save failed")


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
