import sys
import os

sys.path.append(os.getcwd())
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import time
from datetime import datetime

from bot2.strategy_weights import StrategyWeights
from bot2.self_evolving import SelfEvolvingSystem
from bot2.stabilizer import Stabilizer

from src.services.firebase_client import (
    load_recent_trades,
    save_config,
    save_metrics,
    save_trade_batch
)


def compute_performance(trades):
    if not trades:
        return {"winrate": 0, "profit": 0, "confidence_quality": 0}

    wins = sum(1 for t in trades if t.get("result") == "WIN")
    losses = sum(1 for t in trades if t.get("result") == "LOSS")

    total = wins + losses
    winrate = (wins / total) * 100 if total > 0 else 0

    profits = [t.get("profit", 0) for t in trades]
    total_profit = sum(profits)

    errors = [t.get("self_eval", {}).get("error", 0) for t in trades]
    confidence_quality = 1 - (sum(errors) / len(errors)) if errors else 0.5

    return {
        "winrate": winrate,
        "profit": total_profit,
        "confidence_quality": confidence_quality
    }


def run_brain():
    print("🧠 Brain started...")

    stabilizer = Stabilizer()
    evolver = SelfEvolvingSystem()
    weights_engine = StrategyWeights()

    while True:
        try:
            trades = load_recent_trades(limit=100)

            if not trades:
                print("⚠️ No trades yet...")
                time.sleep(10)
                continue

            perf = compute_performance(trades)
            weights = weights_engine.update()
            evo = evolver.evolve(perf)

            stabilizer.update(trades)
            stab = stabilizer.get_state()

            config = {
                "weights": weights,
                "confidence_bias": 0,
                "confidence_scale": 1,
                "min_conf": stab["min_conf"],
                "cooldown": stab["cooldown"],
                "risk_multiplier": evo.get("risk_multiplier", 1),
                "trust": 1,
                "timestamp": datetime.utcnow().isoformat()
            }

            save_config(config)
            save_metrics({"performance": perf})

            print("✅ Brain updated config")

            time.sleep(30)

        except Exception as e:
            print("❌ ERROR:", e)
            time.sleep(10)


if __name__ == "__main__":
    run_brain()