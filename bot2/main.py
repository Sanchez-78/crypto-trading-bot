import time
import sys, os

sys.path.append(os.getcwd())

from src.services.firebase_client import get_db
from src.services.evaluator import calculate_performance


def compute_strategy_weights(trades):
    stats = {}

    for t in trades:
        strategy = t.get("strategy")
        if not strategy:
            continue

        if strategy not in stats:
            stats[strategy] = {"wins": 0, "total": 0}

        stats[strategy]["total"] += 1

        if t.get("result") == "WIN":
            stats[strategy]["wins"] += 1

    weights = {}

    for strat, s in stats.items():
        winrate = s["wins"] / s["total"] if s["total"] else 0
        weights[strat] = round(winrate, 2)

    return weights


def run_brain():
    print("🧠 Brain started...")

    db = get_db()

    while True:
        docs = db.collection("signals") \
            .where("evaluated", "==", True) \
            .limit(100) \
            .stream()

        trades = [d.to_dict() for d in docs]

        if not trades:
            print("⚠️ No evaluated signals yet...")
            time.sleep(30)
            continue

        perf = calculate_performance(trades)

        weights = compute_strategy_weights(trades)

        print("📊 PERF:", perf)
        print("⚖️ WEIGHTS:", weights)

        config = {
            "min_conf": 0.6 if perf["winrate"] > 0.5 else 0.7,
            "strategy_weights": weights
        }

        db.collection("config").document("latest").set(config)

        print("⚙️ Updated config:", config)

        time.sleep(60)


if __name__ == "__main__":
    run_brain()