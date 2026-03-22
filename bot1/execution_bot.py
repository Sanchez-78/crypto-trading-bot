import time
import random
import sys, os

sys.path.append(os.getcwd())

from src.services.firebase_client import save_signal, load_config
from src.services.risk_manager import RiskManager
from src.services.risk_engine import RiskEngine
from src.services.portfolio_manager import PortfolioManager


# =========================
# 📊 MARKET FEATURES (mock)
# =========================
def get_market_features():
    return {
        "price": 50000 + random.randint(-500, 500),
        "trend": random.choice(["UP", "DOWN"]),
        "volatility": random.random(),
        "atr_m15": random.uniform(0.0005, 0.002)  # 🔥 důležité pro risk
    }


# =========================
# 🧠 REGIME
# =========================
def detect_regime(f):
    if f["volatility"] > 0.7:
        return "VOLATILE"
    if f["trend"] == "UP":
        return "TREND"
    return "RANGE"


# =========================
# 📈 STRATEGIES
# =========================
def trend_strategy(f):
    if f["trend"] == "UP":
        return "BUY", random.uniform(0.5, 1.0)
    return "HOLD", random.uniform(0.0, 0.5)


def reversal_strategy(f):
    if f["volatility"] > 0.7:
        return "BUY", random.uniform(0.5, 1.0)
    return "HOLD", random.uniform(0.0, 0.5)


# =========================
# 🧠 BANDIT
# =========================
def select_strategy(strategies, regime, features, config):
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

    if random.random() < epsilon:
        return random.choice(list(strategies.keys()))

    best, best_score = None, -999

    for name in strategies:
        key = f"{regime}_{name}_{feature_key}"
        score = scores.get(key, 0)

        if score > best_score:
            best_score = score
            best = name

    return best or random.choice(list(strategies.keys()))


# =========================
# 📊 MOCK METRICS (napojíš na Firebase)
# =========================
def load_metrics():
    return {
        "performance": {"winrate": 0.55},
        "drawdown": 0.05
    }


# =========================
# 🚀 MAIN
# =========================
def run_execution():
    print("🟢 Execution started (FULL SYSTEM)")

    risk_manager = RiskManager()
    risk_engine = RiskEngine()
    portfolio = PortfolioManager()

    balance = 10000

    while True:
        config = load_config() or {}
        features = get_market_features()

        strategies = {
            "TREND": trend_strategy,
            "REVERSAL": reversal_strategy
        }

        regime = detect_regime(features)
        chosen = select_strategy(strategies, regime, features, config)

        signal, confidence = strategies[chosen](features)

        # =========================
        # ❌ ONLY BUY
        # =========================
        if signal != "BUY":
            time.sleep(60)
            continue

        # =========================
        # 📊 METRICS
        # =========================
        metrics = load_metrics()
        winrate = metrics["performance"]["winrate"]
        drawdown = metrics["drawdown"]

        # =========================
        # 🚨 KILL SWITCH
        # =========================
        if not risk_engine.should_trade(drawdown, {"cooldown": 0}):
            print("🛑 Trading paused")
            time.sleep(60)
            continue

        # =========================
        # 📉 SL / TP (ATR)
        # =========================
        sl, tp = risk_manager.compute(
            features,
            features["price"],
            signal
        )

        if sl is None:
            print("❌ No ATR → skip")
            time.sleep(60)
            continue

        # =========================
        # 🧠 EDGE
        # =========================
        edge = risk_engine.compute_edge(confidence, winrate)

        # =========================
        # 💰 POSITION SIZE
        # =========================
        size = risk_engine.position_size(
            balance,
            features["price"],
            sl,
            edge
        )

        if size <= 0:
            print("❌ Size = 0")
            time.sleep(60)
            continue

        # =========================
        # 📊 PORTFOLIO LIMIT
        # =========================
        if not portfolio.can_open(balance):
            print("⚠️ Max exposure reached")
            time.sleep(60)
            continue

        # =========================
        # 🟢 OPEN TRADE
        # =========================
        trade, _ = portfolio.open_trade(
            symbol="BTCUSDT",
            action="BUY",
            price=features["price"],
            confidence=confidence,
            size=size,
            sl=sl,
            tp=tp
        )

        # Firebase = logging only
        save_signal({
            **trade,
            "strategy": chosen,
            "regime": regime,
            "features": features,
            "edge": edge,
            "timestamp": time.time()
        })

        print(f"✅ OPEN {trade['id']} size={round(size,2)}")

        # =========================
        # 🔄 UPDATE PORTFOLIO
        # =========================
        prices = {"BTCUSDT": features["price"]}

        closed = portfolio.update_trades(prices)

        for t, pnl, result in closed:
            print(f"🔒 CLOSED {t['id']} {result} PnL={round(pnl,4)}")

        time.sleep(60)