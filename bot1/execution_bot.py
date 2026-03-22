import time
import random
import sys, os

sys.path.append(os.getcwd())

from src.services.firebase_client import save_signal, load_config
from bot1.trade_manager import get_open_trades, close_trade


# =========================
# 📊 MARKET FEATURES (mock)
# =========================
def get_market_features():
    return {
        "price": 50000 + random.randint(-500, 500),
        "trend": random.choice(["UP", "DOWN"]),
        "volatility": random.random()
    }


# =========================
# 🧠 REGIME DETECTION
# =========================
def detect_regime(features):
    if features["volatility"] > 0.7:
        return "VOLATILE"
    if features["trend"] == "UP":
        return "TREND"
    return "RANGE"


# =========================
# 📈 TREND STRATEGY
# =========================
def trend_strategy(features):
    if features["trend"] == "UP":
        return "BUY", random.uniform(0.5, 1.0)
    return "HOLD", random.uniform(0.0, 0.5)


# =========================
# 🔄 REVERSAL STRATEGY
# =========================
def reversal_strategy(features):
    if features["volatility"] > 0.7:
        return "BUY", random.uniform(0.5, 1.0)
    return "HOLD", random.uniform(0.0, 0.5)


# =========================
# 🧠 CONTEXTUAL BANDIT (FEATURE AWARE)
# =========================
def select_strategy_contextual(strategies, regime, features, config):
    scores = config.get("bandit_scores", {})
    epsilon = config.get("epsilon", 0.1)

    vol = features["volatility"]
    trend = features["trend"]

    if vol > 0.7:
        vol_bucket = "HIGH"
    elif vol > 0.3:
        vol_bucket = "MID"
    else:
        vol_bucket = "LOW"

    feature_key = f"{trend}_{vol_bucket}"

    # exploration
    if random.random() < epsilon:
        return random.choice(list(strategies.keys()))

    best = None
    best_score = -999

    for name in strategies.keys():
        key = f"{regime}_{name}_{feature_key}"
        score = scores.get(key, 0)

        if score > best_score:
            best_score = score
            best = name

    return best or random.choice(list(strategies.keys()))


# =========================
# 🧠 SIGNAL GENERATOR
# =========================
def generate_signal(features, config):
    strategies = {
        "TREND": trend_strategy,
        "REVERSAL": reversal_strategy
    }

    regime = detect_regime(features)

    chosen = select_strategy_contextual(strategies, regime, features, config)

    signal, confidence = strategies[chosen](features)

    return signal, confidence, chosen, regime


# =========================
# 🚀 MAIN LOOP
# =========================
def run_execution():
    print("🟢 Execution started (Contextual + Feature Bandit)")

    while True:
        config = load_config() or {}

        features = get_market_features()

        signal, confidence, strategy, regime = generate_signal(features, config)

        # =========================
        # 🟢 OPEN SIGNAL
        # =========================
        if signal == "BUY":
            signal_data = {
                "symbol": "BTCUSDT",
                "signal": "BUY",
                "price": features["price"],
                "strategy": strategy,
                "regime": regime,
                "confidence": confidence,
                "features": features,
                "evaluated": False,
                "age": 0,
                "config_version": config.get("version", 0),
                "timestamp": time.time()
            }

            save_signal(signal_data)

            print(f"✅ BUY {round(confidence, 2)} | {strategy} | {regime}")

        # =========================
        # 🔒 CLOSE TRADES (mock)
        # =========================
        open_trades = get_open_trades()

        for t in open_trades:
            entry = t["entry_price"]
            current_price = features["price"]

            change = (current_price - entry) / entry

            if change > 0.01 or change < -0.01:
                close_trade(t["id"], current_price)
                print(f"🔒 Closed {t['id']} PnL: {round(change,4)}")

        time.sleep(60)