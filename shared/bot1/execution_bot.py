import time
import random
import sys, os

sys.path.append(os.getcwd())

from src.services.firebase_client import save_signal, load_config
from src.services.risk_manager import RiskManager
from src.services.risk_engine import RiskEngine
from src.services.portfolio_manager import PortfolioManager


def get_market_features():
    return {
        "price": 50000 + random.randint(-500, 500),
        "trend": random.choice(["UP", "DOWN"]),
        "volatility": random.random(),
        "atr_m15": random.uniform(0.0005, 0.002)
    }


def detect_regime(f):
    if f["volatility"] > 0.7:
        return "VOLATILE"
    if f["trend"] == "UP":
        return "TREND"
    return "RANGE"


def trend_strategy(f):
    if f["trend"] == "UP":
        return "BUY", random.uniform(0.5, 1.0)
    return "HOLD", 0


def reversal_strategy(f):
    if f["volatility"] > 0.7:
        return "BUY", random.uniform(0.5, 1.0)
    return "HOLD", 0


def select_strategy(strategies, regime, features, config):
    scores = config.get("bandit_scores", {})
    epsilon = config.get("epsilon", 0.1)

    vol = features["volatility"]
    trend = features["trend"]

    vol_bucket = "HIGH" if vol > 0.7 else "MID" if vol > 0.3 else "LOW"
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


def load_metrics():
    return {
        "performance": {"winrate": 0.55},
        "drawdown": 0.05
    }


def run_execution():
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

        if signal != "BUY":
            time.sleep(60)
            continue

        metrics = load_metrics()
        winrate = metrics["performance"]["winrate"]
        drawdown = metrics["drawdown"]

        # 🔥 CONFIDENCE CALIBRATION
        cal = config.get("confidence_calibration", {})
        confidence_adj = cal.get(round(confidence, 1), confidence)

        # 🔥 BONUS RISK LAYER
        if regime == "TREND":
            risk_engine.max_risk_per_trade = 0.03
        elif regime == "VOLATILE":
            risk_engine.max_risk_per_trade = 0.01
        else:
            risk_engine.max_risk_per_trade = 0.02

        if drawdown > 0.1:
            risk_engine.max_risk_per_trade *= 0.5

        if drawdown > 0.2:
            print("💀 HARD STOP")
            time.sleep(300)
            continue

        if not risk_engine.should_trade(drawdown, {"cooldown": 0}):
            time.sleep(60)
            continue

        sl, tp = risk_manager.compute(features, features["price"], signal)

        if sl is None:
            time.sleep(60)
            continue

        edge = risk_engine.compute_edge(confidence_adj, winrate)

        size = risk_engine.position_size(
            balance,
            features["price"],
            sl,
            edge
        )

        if size <= 0 or not portfolio.can_open(balance):
            time.sleep(60)
            continue

        vol_bucket = "HIGH" if features["volatility"] > 0.7 else "MID" if features["volatility"] > 0.3 else "LOW"

        trade, _ = portfolio.open_trade(
            symbol="BTCUSDT",
            action="BUY",
            price=features["price"],
            confidence=confidence_adj,
            size=size,
            sl=sl,
            tp=tp
        )

        save_signal({
            **trade,
            "strategy": chosen,
            "regime": regime,
            "features": features,
            "edge": edge,
            "meta": {
                "feature_bucket": f"{features['trend']}_{vol_bucket}",
                "confidence_raw": confidence,
                "confidence_used": confidence_adj
            },
            "timestamp": time.time()
        })

        prices = {"BTCUSDT": features["price"]}
        closed = portfolio.update_trades(prices)

        for t, pnl, result in closed:
            print(f"🔒 CLOSED {t['id']} {result} {round(pnl,4)}")

        time.sleep(60)


if __name__ == "__main__":
    run_execution()