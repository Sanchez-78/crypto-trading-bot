from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import save_bot_stats, load_bot_stats

import time

print("🧠 LEARNING MODULE LOADED")

# =========================
# CONFIG
# =========================
START_EQUITY = 1000
MIN_TRADES_READY = 20
MIN_WINRATE_READY = 0.55

# =========================
# STATE
# =========================
stats = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "winrate": 0.0,
    "win_loss_ratio": 0.0,
    "profit_factor": 0.0,
    "avg_profit": 0.0,
    "equity": START_EQUITY,
    "learning_score": 0.0,
    "ready": False,
    "last_trade": None,
    "updated_at": None
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
        "winrate": data.get("winrate", 0.0),
        "win_loss_ratio": data.get("win_loss_ratio", 0.0),
        "profit_factor": data.get("profit_factor", 0.0),
        "avg_profit": data.get("avg_profit", 0.0),
        "equity": data.get("equity", START_EQUITY),
        "learning_score": data.get("learning_score", 0.0),
        "ready": data.get("ready", False),
        "last_trade": data.get("last_trade"),
        "updated_at": data.get("updated_at")
    })


# =========================
# UPDATE LEARNING
# =========================
def update_learning(trade):
    stats["trades"] += 1

    if trade["result"] == "WIN":
        stats["wins"] += 1
    else:
        stats["losses"] += 1

    # =========================
    # CORE METRICS
    # =========================
    stats["winrate"] = stats["wins"] / stats["trades"]

    # avg profit
    stats["avg_profit"] = (
        (stats["avg_profit"] * (stats["trades"] - 1) + trade["profit"])
        / stats["trades"]
    )

    # equity growth
    stats["equity"] += stats["equity"] * trade["profit"]

    # =========================
    # ADVANCED METRICS
    # =========================
    stats["win_loss_ratio"] = (
        stats["wins"] / stats["losses"]
        if stats["losses"] > 0 else stats["wins"]
    )

    stats["profit_factor"] = (
        (stats["avg_profit"] * stats["wins"]) /
        abs(stats["avg_profit"] * stats["losses"])
        if stats["losses"] > 0 else 1
    )

    # =========================
    # LEARNING SCORE
    # =========================
    stats["learning_score"] = (
        stats["winrate"] * 0.6 +
        min(stats["trades"] / 100, 1) * 0.4
    )

    # =========================
    # READY LOGIC
    # =========================
    stats["ready"] = (
        stats["trades"] >= MIN_TRADES_READY and
        stats["winrate"] >= MIN_WINRATE_READY
    )

    stats["last_trade"] = trade
    stats["updated_at"] = time.time()


# =========================
# PROGRESS BAR
# =========================
def progress_bar():
    progress = min(stats["trades"] / 100, 1)

    bars = int(progress * 20)
    empty = 20 - bars

    bar = "🟩" * bars + "⬜" * empty
    percent = int(progress * 100)

    print(f"📊 PROGRESS: [{bar}] {percent}%")


# =========================
# PRINT STATUS
# =========================
def print_status():
    print("\n🧠 ===== BOT STATUS =====")

    print(f"Trades: {stats['trades']}")
    print(f"Wins: {stats['wins']} | Losses: {stats['losses']}")
    print(f"Winrate: {round(stats['winrate'], 2)}")

    print(f"Win/Loss Ratio: {round(stats['win_loss_ratio'], 2)}")
    print(f"Profit Factor: {round(stats['profit_factor'], 2)}")

    print(f"Equity: {round(stats['equity'], 2)}")
    print(f"Learning Score: {round(stats['learning_score'], 2)}")

    progress_bar()

    if stats["ready"]:
        print("🚀 BOT READY FOR TRADING")
    else:
        print("📚 BOT IS STILL LEARNING")

    print("========================\n")


# =========================
# EVENT HANDLER
# =========================
def on_evaluation(trade):
    print("🧠 LEARNING:", trade)

    update_learning(trade)

    print_status()

    save_bot_stats(stats)


event_bus.subscribe(EVALUATION_DONE, on_evaluation)


# =========================
# EXPORTS (API / APP)
# =========================
def is_ready():
    return stats["ready"]


def get_status():
    progress = min(stats["trades"] / 100, 1)

    return {
        "trades": stats["trades"],
        "wins": stats["wins"],
        "losses": stats["losses"],
        "winrate": stats["winrate"],
        "win_loss_ratio": stats["win_loss_ratio"],
        "profit_factor": stats["profit_factor"],
        "equity": stats["equity"],
        "learning_score": stats["learning_score"],
        "progress": progress,
        "ready": stats["ready"],
        "last_trade": stats["last_trade"],
        "updated_at": stats["updated_at"]
    }


# =========================
# INIT
# =========================
load_history()