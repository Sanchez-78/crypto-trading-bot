from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import save_bot_stats, load_bot_stats

import time

print("🧠 LEARNING MODULE LOADED")

AUTO_TRADE_ENABLED = True

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


# =========================
# LOAD HISTORY
# =========================
def load_history():
    data = load_bot_stats()

    if not data:
        print("📭 starting fresh")
        return

    print("📊 RESTORED FROM DB")

    stats.update({
        "trades": data.get("trades", 0),
        "wins": data.get("wins", 0),
        "losses": data.get("losses", 0),
        "winrate": data.get("winrate", 0),
        "avg_profit": data.get("avg_profit", 0),
        "equity": data.get("equity", 1000),
        "learning_score": data.get("learning_score", 0),
        "ready": data.get("ready", False),
        "last_trade": data.get("last_trade")
    })


# =========================
# UPDATE
# =========================
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

    stats["ready"] = stats["trades"] > 5 and stats["winrate"] > 0.5

    stats["last_trade"] = trade


# =========================
# PROGRESS BAR
# =========================
def progress_bar():
    p = min(stats["trades"] / 50, 1)
    bars = int(p * 20)
    print("📊", "🟩" * bars + "⬜" * (20 - bars), f"{int(p*100)}%")


# =========================
# EVENT
# =========================
def on_evaluation(trade):
    print("🧠 LEARNING:", trade)

    update_learning(trade)

    print("📈 WINRATE:", round(stats["winrate"], 2))
    progress_bar()

    save_bot_stats(stats)


event_bus.subscribe(EVALUATION_DONE, on_evaluation)


# =========================
# EXPORTS
# =========================
def is_ready():
    return stats["ready"]


def get_status():
    return stats


# LOAD HISTORY ON START
load_history()