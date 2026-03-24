from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import save_bot_stats

import time

print("🧠 LEARNING MODULE LOADED")

AUTO_TRADE_ENABLED = True
WRITE_INTERVAL = 0  # DEBUG

stats = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "winrate": 0,
    "avg_profit": 0,
    "equity": 1000,
    "learning_score": 0,
    "ready": False,
    "last_trade": None
}

last_write_time = 0


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

    stats["learning_score"] = (
        stats["winrate"] * 0.7 +
        min(stats["trades"] / 50, 1) * 0.3
    )

    stats["ready"] = (
        stats["trades"] > 5 and
        stats["winrate"] > 0.5
    )

    stats["last_trade"] = trade


def print_status():
    print("\n🧠 ===== BOT STATUS =====")
    print(stats)
    print("========================\n")


def save_to_firebase():
    global last_write_time

    now = time.time()

    if now - last_write_time < WRITE_INTERVAL:
        print("⏳ Skip Firebase write")
        return

    ok = save_bot_stats(stats)

    print("☁️ SAVE RESULT:", ok)

    if ok:
        last_write_time = now


def on_evaluation(trade):
    print("🧠 LEARNING TRIGGERED:", trade)

    if not isinstance(trade, dict):
        print("❌ invalid trade")
        return

    if "result" not in trade or "profit" not in trade:
        print("❌ missing fields")
        return

    update_learning(trade)
    print_status()
    save_to_firebase()


event_bus.subscribe(EVALUATION_DONE, on_evaluation)