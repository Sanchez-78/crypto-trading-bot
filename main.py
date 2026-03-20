import time
import traceback
from datetime import datetime, UTC

from src.services.firebase_client import (
    init_firebase,
    save_signal,
    load_recent_trades
)

from src.services.market_data import get_all_prices
from src.services.meta_agent import MetaAgent
from src.services.evaluator import evaluate_signals


symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
meta_agent = MetaAgent()

last_prices = {}


# ---------------- MULTI-TF FEATURES ----------------

def build_features(symbol, price):
    prev = last_prices.get(symbol, {})

    def calc_tf(tf, multiplier):
        prev_price = prev.get(tf)

        change = 0 if not prev_price else (price - prev_price) / prev_price
        trend = 1 if change > 0 else -1
        volatility = 1 if abs(change) > (0.005 * multiplier) else 0

        prev[tf] = price

        return {
            f"{tf}_change": change,
            f"{tf}_trend": trend,
            f"{tf}_volatility": volatility
        }

    m15 = calc_tf("m15", 1)
    h1 = calc_tf("h1", 2)
    h4 = calc_tf("h4", 4)

    last_prices[symbol] = prev

    return {
        "price": price,
        **m15,
        **h1,
        **h4
    }


# ---------------- PIPELINE ----------------

def run_pipeline():
    print("\n=== START PIPELINE ===")

    init_firebase()

    try:
        # 🔥 LEARNING
        trades = load_recent_trades(100)
        meta_agent.learn_from_history(trades)

        prices = get_all_prices()

        if not prices:
            print("⚠️ fallback prices")
            prices = {
                "BTCUSDT": 60000,
                "ETHUSDT": 3000,
                "ADAUSDT": 0.5
            }

        for symbol in symbols:
            try:
                price = prices.get(symbol)
                if not price:
                    continue

                features = build_features(symbol, price)

                result = meta_agent.decide(features)

                if not result or not isinstance(result, tuple):
                    action, confidence = "HOLD", 0.0
                else:
                    action, confidence = result

                print(f"{symbol} | {action} | {confidence:.2f}")

                signal = {
                    "symbol": symbol,
                    "signal": action,
                    "confidence": float(confidence),
                    "price": float(price),
                    "features": features,
                    "result": None,
                    "profit": None,
                    "age": 0,
                    "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                    "evaluated": False,
                    "mode": "learning"
                }

                save_signal(signal)

            except Exception as e:
                print(f"❌ {symbol} error:", e)
                traceback.print_exc()

        print("\n🧪 Evaluating...")

        for symbol in symbols:
            evaluate_signals(symbol)

    except Exception as e:
        print("❌ PIPELINE ERROR:", e)
        traceback.print_exc()


if __name__ == "__main__":
    print("🔥 BOT STARTED")

    while True:
        run_pipeline()
        time.sleep(60)