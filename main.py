import time
import traceback
from datetime import datetime

from src.services.firebase_client import (
    init_firebase,
    save_signal,
    load_all_signals,
    load_open_signals
)

from src.services.market_data import get_candles
from src.services.feature_extractor import extract_multi_tf_features
from src.services.meta_agent import MetaAgent
from src.services.evaluator import evaluate_signals

# -------------------------------
# CONFIG
# -------------------------------

symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
meta_agent = MetaAgent()

MIN_CONFIDENCE = 0.55
MAX_OPEN_TRADES = 5


# -------------------------------
# RISK MANAGEMENT (BONUS)
# -------------------------------

def should_trade(action, confidence, open_trades):
    if action == "HOLD":
        return False

    if confidence < MIN_CONFIDENCE:
        print("🚫 Low confidence")
        return False

    if len(open_trades) >= MAX_OPEN_TRADES:
        print("🚫 Too many open trades")
        return False

    return True


def bootstrap_mode(total_signals):
    return total_signals < 30


# -------------------------------
# PIPELINE
# -------------------------------

def run_pipeline():
    print("\n=== START PIPELINE ===")

    # 🔥 KRITICKÉ
    init_firebase()

    try:
        all_signals = load_all_signals()
        open_signals = load_open_signals()

        print(f"📂 Loaded all signals: {len(all_signals)}")
        print(f"📂 Open trades: {len(open_signals)}")

        for symbol in symbols:
            print(f"\n🔍 {symbol}")

            try:
                # -------------------------------
                # MARKET DATA
                # -------------------------------

                candles_m15 = get_candles(symbol, "15")
                candles_h1 = get_candles(symbol, "60")
                candles_h4 = get_candles(symbol, "240")

                features = extract_multi_tf_features(
                    candles_m15,
                    candles_h1,
                    candles_h4
                )

                if not features:
                    print("⚠️ Skipping - no features")
                    continue

                print("DEBUG FEATURES:", features)

                # -------------------------------
                # DECISION
                # -------------------------------

                action, confidence = meta_agent.decide(features)

                print(f"🤖 FINAL: {action} ({confidence})")

                # -------------------------------
                # BOOTSTRAP MODE
                # -------------------------------

                if bootstrap_mode(len(all_signals)):
                    print("🚀 Bootstrap mode → allowing trade")
                    allow = True
                else:
                    allow = should_trade(action, confidence, open_signals)

                if not allow:
                    continue

                # -------------------------------
                # EXECUTE TRADE
                # -------------------------------

                price = features.get("price", 0)

                signal = {
                    "symbol": symbol,
                    "signal": action,
                    "confidence": float(confidence),
                    "price": float(price),
                    "features": features,
                    "result": None,
                    "profit": None,
                    "timestamp": datetime.utcnow().isoformat(),
                    "evaluated": False
                }

                print("\n🚀 EXECUTING TRADE")
                print(f"{symbol} {action} @ {price}")

                save_signal(signal)

                print("💾 Signal saved")

            except Exception as e:
                print(f"❌ {symbol} error:", e)
                traceback.print_exc()

        # -------------------------------
        # EVALUATION
        # -------------------------------

        print("\n🧪 Running evaluation...")

        for symbol in symbols:
            try:
                evaluate_signals(symbol)
            except Exception as e:
                print(f"❌ Eval error {symbol}:", e)

        print("\n=== END PIPELINE ===")

    except Exception as e:
        print("❌ PIPELINE ERROR:", e)
        traceback.print_exc()


# -------------------------------
# LOOP
# -------------------------------

if __name__ == "__main__":
    print("🔥 BOT STARTED")

    while True:
        run_pipeline()
        time.sleep(300)