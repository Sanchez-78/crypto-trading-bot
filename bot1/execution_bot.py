import time
import random
import sys, os

sys.path.append(os.getcwd())

from src.services.firebase_client import save_trade, load_config
from bot1.trade_manager import get_open_trades, close_trade


def get_market_features():
    return {
        "price": 50000 + random.randint(-500, 500),
        "trend": random.choice(["UP", "DOWN"]),
        "volatility": random.random()
    }


def generate_signal(features, config):
    confidence = random.random()

    if confidence > config.get("min_conf", 0.5):
        return "BUY", confidence

    return "HOLD", confidence


def run_execution():
    print("🟢 Execution started")

    while True:
        config = load_config() or {}

        features = get_market_features()

        signal, confidence = generate_signal(features, config)

        # =========================
        # 🟢 OPEN TRADE
        # =========================
        if signal == "BUY":
            trade = {
                "symbol": "BTCUSDT",
                "entry_price": features["price"],
                "exit_price": None,
                "status": "OPEN",
                "strategy": "TREND",
                "confidence": confidence,
                "timestamp": time.time()
            }

            save_trade(trade)
            print(f"✅ BUY {round(confidence, 2)}")

        # =========================
        # 🔒 CLOSE TRADES
        # =========================
        open_trades = get_open_trades()

        for t in open_trades:
            entry = t["entry_price"]
            current_price = features["price"]

            change = (current_price - entry) / entry

            # TP / SL
            if change > 0.01 or change < -0.01:
                close_trade(t["id"], current_price)
                print(f"🔒 Closed {t['id']} PnL: {round(change,4)}")

        time.sleep(10)