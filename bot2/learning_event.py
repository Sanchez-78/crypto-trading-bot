from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import db

import time

# =========================
# GLOBAL STATS
# =========================
stats = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "winrate": 0,
    "avg_profit": 0,
    "equity": 1000,
    "learning_score": 0,
    "ready": False
}


def update_learning(trade):
    stats["trades"] += 1

    if trade["result"] == "WIN":
        stats["wins"] += 1
    else:
        stats["losses"] += 1

    stats["winrate"] = stats["wins"] / stats["trades"]

    stats["avg_profit"] = (
        (stats["avg_profit"] * (stats["trades"] - 1) + trade["profit"])
        / stats["trades"]
    )

    stats["equity"] += stats["equity"] * trade["profit"]

    # 🔥 LEARNING SCORE
    stats["learning_score"] = (
        stats["winrate"] * 0.7 +
        min(stats["trades"] / 50, 1) * 0.3
    )

    # 🔥 READY LOGIC
    stats["ready"] = (
        stats["trades"] > 20 and
        stats["winrate"] > 0.55
    )


def print_status():
    print("\n🧠 ===== BOT STATUS =====")
    print(f"Trades: {stats['trades']}")
    print(f"Winrate: {round(stats['winrate']*100, 2)} %")
    print(f"Avg profit: {round(stats['avg_profit'], 4)}")
    print(f"Equity: {round(stats['equity'], 2)}")
    print(f"Learning score: {round(stats['learning_score'], 2)}")

    if stats["ready"]:
        print("🚀 BOT JE NAUČEN A PŘIPRAVEN OBCHODOVAT")
    else:
        print("📚 BOT SE STÁLE UČÍ")

    print("========================\n")


def save_to_firebase():
    try:
        db.collection("bot_stats").document("latest").set({
            **stats,
            "timestamp": time.time()
        })
    except Exception as e:
        print("❌ Firebase write error:", e)


def on_evaluation(trade):
    print("🧠 LEARNING TRIGGERED")

    update_learning(trade)
    print_status()
    save_to_firebase()


event_bus.subscribe(EVALUATION_DONE, on_evaluation)