import time
import random
import sys, os

sys.path.append(os.getcwd())

from src.services.firebase_client import save_trade, load_config
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
# ⚖️ STRATEGY WEIGHT
# =========================
def apply_strategy_weight(strategy, confidence, config):
    weights = config.get("strategy_weights", {})
    weight = weights.get(strategy, 0.5)

    return confidence * weight


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
    # vysoká volatilita → možný obrat
    if features["volatility"] > 0.7:
        return "BUY", random.uniform(0.5, 1.0)

    return "HOLD", random.uniform(0.0, 0.5)


# =========================
# 🧠 SIGNAL GENERATOR
# =========================
def generate_signal(features, config):
    strategies = {
        "TREND": trend_strategy,
        "REVERSAL": reversal_strategy
    }

    best_signal = "HOLD"
    best_conf = 0
    best_strategy = None

    for name, strat_fn in strategies.items():
        signal, confidence = strat_fn(features)

        # aplikace váhy
        confidence = apply_strategy_weight(name, confidence, config)

        if confidence > best_conf:
            best_conf = confidence
            best_signal = signal
            best_strategy = name

    return best_signal, best_conf, best_strategy


# =========================
# 🚀 MAIN LOOP
# =========================
def run_execution():
    print("🟢 Execution started")

    while True:
        config = load_config() or {}

        features = get_market_features()

        signal, confidence, strategy = generate_signal(features, config)

        # =========================
        # 🟢 OPEN TRADE
        # =========================
        if signal == "BUY":
            trade = {
                "symbol": "BTCUSDT",
                "entry_price": features["price"],
                "exit_price": None,
                "status": "OPEN",
                "strategy": strategy,
                "confidence": confidence,
                "features": features,  # 🔥 důležité pro learning
                "timestamp": time.time()
            }

            save_trade(trade)
            print(f"✅ BUY {round(confidence, 2)} | strat: {strategy}")

        # =========================
        # 🔒 CLOSE TRADES
        # =========================
        open_trades = get_open_trades()

        for t in open_trades:
            entry = t["entry_price"]
            current_price = features["price"]

            change = (current_price - entry) / entry

            if change > 0.01 or change < -0.01:
                close_trade(t["id"], current_price)
                print(f"🔒 Closed {t['id']} PnL: {round(change,4)}")

        time.sleep(30)