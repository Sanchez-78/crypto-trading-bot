import time
import traceback
from datetime import datetime

from src.services.firebase_client import (
    init_firebase,
    save_signal,
    load_all_signals,
    load_open_signals
)

from src.services.market_data import get_all_prices
from src.services.meta_agent import MetaAgent
from src.services.evaluator import evaluate_signals


symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
meta_agent = MetaAgent()

LEARNING_ONLY = True  # 🔥 KLÍČOVÉ

MAX_OPEN_TRADES = 5
MAX_DAILY_DRAWDOWN = -0.05

last_prices = {}
kill_switch_active_until = 0


# -------------------------------
# CONFIDENCE
# -------------------------------

def dynamic_confidence_threshold(signals):
    if len(signals) < 50:
        return 0.55
    if len(signals) < 200:
        return 0.6
    return 0.65


# -------------------------------
# POSITION SIZE
# -------------------------------

def compute_position_size(confidence):
    return round(confidence, 3)


# -------------------------------
# FEATURES
# -------------------------------

def build_features(symbol, price):
    prev_price = last_prices.get(symbol)

    change = 0 if not prev_price else (price - prev_price) / prev_price

    trend = 1 if change > 0 else -1
    volatility = 1 if abs(change) > 0.01 else 0

    last_prices[symbol] = price

    return {
        "price": price,
        "change": change,
        "trend": trend,
        "volatility": volatility
    }


# -------------------------------
# KILL SWITCH (rolling window)
# -------------------------------

def check_kill_switch(signals):
    global kill_switch_active_until

    if time.time() < kill_switch_active_until:
        return True

    recent = [
        s for s in signals
        if s.get("evaluated") and s.get("profit") is not None
    ][-20:]

    if len(recent) < 10:
        return False

    total = sum(s["profit"] for s in recent)

    if total < -0.05:
        kill_switch_active_until = time.time() + 3600
        print(f"🛑 KILL SWITCH ACTIVE | recent pnl={round(total,4)}")
        return True

    return False


# -------------------------------
# PIPELINE
# -------------------------------

def run_pipeline():
    print("\n=== START PIPELINE ===")

    init_firebase()

    try:
        all_signals = load_all_signals()
        open_signals = load_open_signals()

        kill = check_kill_switch(all_signals)

        MIN_CONFIDENCE = dynamic_confidence_threshold(all_signals)

        prices = get_all_prices()
        if not prices:
            print("❌ No prices")
            return

        for symbol in symbols:
            try:
                price = prices.get(symbol)
                if not price:
                    continue

                features = build_features(symbol, price)

                action, confidence = meta_agent.decide(features)

                if features["trend"] == 1:
                    confidence += 0.05

                print(f"{symbol} | {action} | conf={confidence:.2f}")

                # 🔥 ALWAYS CREATE SIGNAL (learning)
                signal = {
                    "symbol": symbol,
                    "signal": action,
                    "confidence": float(confidence),
                    "size": compute_position_size(confidence),
                    "price": float(price),
                    "features": features,
                    "result": None,
                    "profit": None,
                    "age": 0,
                    "timestamp": datetime.utcnow().isoformat(),
                    "evaluated": False,
                    "mode": "learning"
                }

                # 🔥 LEARNING MODE
                if LEARNING_ONLY:
                    save_signal(signal)
                    continue

                # 🔥 TRADING MODE (disabled now)
                if not kill:
                    if confidence < MIN_CONFIDENCE:
                        continue

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