import time
import sys, os

sys.path.append(os.getcwd())

from src.services.firebase_client import get_db
from src.services.evaluator import calculate_performance  # tvůj evaluator


def run_brain():
    print("🧠 Brain started...")

    db = get_db()

    while True:
        # =========================
        # 📥 LOAD EVALUATED SIGNALS
        # =========================
        docs = db.collection("signals") \
            .where("evaluated", "==", True) \
            .limit(100) \
            .stream()

        trades = [d.to_dict() for d in docs]

        if not trades:
            print("⚠️ No evaluated signals yet...")
            time.sleep(10)
            continue

        # =========================
        # 📊 PERFORMANCE
        # =========================
        perf = calculate_performance(trades)

        print("📊 PERF:", perf)

        # =========================
        # 🧠 ADAPTACE
        # =========================
        config = {
            "min_conf": 0.6 if perf["winrate"] > 0.5 else 0.7
        }

        db.collection("config").document("latest").set(config)

        print("⚙️ Updated config:", config)

        time.sleep(30)


if __name__ == "__main__":
    run_brain()