from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import save_bot_stats, load_bot_stats

import time

print("🧠 LEARNING MODULE (PRO) LOADED")

# =========================
# CONFIG
# =========================
START_EQUITY = 1000
MIN_TRADES_READY = 30
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

    "total_profit": 0.0,
    "total_loss": 0.0,

    "equity": START_EQUITY,
    "peak_equity": START_EQUITY,
    "drawdown": 0.0,

    "win_streak": 0,
    "loss_streak": 0,
    "max_win_streak": 0,
    "max_loss_streak": 0,

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
    stats.update(data)


# =========================
# UPDATE LEARNING
# =========================
def update_learning(trade):
    profit = trade.get("profit", 0)

    stats["trades"] += 1

    # =========================
    # WIN / LOSS
    # =========================
    if trade["result"] == "WIN":
        stats["wins"] += 1
        stats["win_streak"] += 1
        stats["loss_streak"] = 0
        stats["max_win_streak"] = max(stats["max_win_streak"], stats["win_streak"])
        stats["total_profit"] += profit
    else:
        stats["losses"] += 1
        stats["loss_streak"] += 1
        stats["win_streak"] = 0
        stats["max_loss_streak"] = max(stats["max_loss_streak"], stats["loss_streak"])
        stats["total_loss"] += abs(profit)

    # =========================
    # METRICS
    # =========================
    stats["winrate"] = stats["wins"] / stats["trades"]

    stats["win_loss_ratio"] = (
        stats["wins"] / stats["losses"]
        if stats["losses"] > 0 else stats["wins"]
    )

    # 🔥 SPRÁVNÝ PROFIT FACTOR
    stats["profit_factor"] = (
        stats["total_profit"] / stats["total_loss"]
        if stats["total_loss"] > 0 else stats["total_profit"]
    )

    # =========================
    # EQUITY + DRAWDOWN
    # =========================
    stats["equity"] += stats["equity"] * profit

    stats["peak_equity"] = max(stats["peak_equity"], stats["equity"])

    stats["drawdown"] = (
        (stats["peak_equity"] - stats["equity"]) / stats["peak_equity"]
    )

    # =========================
    # LEARNING SCORE
    # =========================
    stats["learning_score"] = (
        stats["winrate"] * 0.5 +
        min(stats["trades"] / 100, 1) * 0.3 +
        min(stats["profit_factor"] / 2, 1) * 0.2
    )

    # =========================
    # READY
    # =========================
    stats["ready"] = (
        stats["trades"] >= MIN_TRADES_READY and
        stats["winrate"] >= MIN_WINRATE_READY and
        stats["profit_factor"] > 1.1
    )

    stats["last_trade"] = trade
    stats["updated_at"] = time.time()


# =========================
# PROGRESS BAR
# =========================
def progress_bar():
    progress = min(stats["trades"] / 100, 1)
    bars = int(progress * 20)
    bar = "🟩" * bars + "⬜" * (20 - bars)
    print(f"📊 {bar} {int(progress*100)}%")


# =========================
# PRINT
# =========================
def print_status():
    print("\n🧠 ===== BOT STATUS =====")

    print(f"Trades: {stats['trades']}")
    print(f"Wins: {stats['wins']} | Losses: {stats['losses']}")
    print(f"Winrate: {round(stats['winrate'], 2)}")

    print(f"Win/Loss Ratio: {round(stats['win_loss_ratio'], 2)}")
    print(f"Profit Factor: {round(stats['profit_factor'], 2)}")

    print(f"Equity: {round(stats['equity'], 2)}")
    print(f"Drawdown: {round(stats['drawdown'], 2)}")

    print(f"Win streak: {stats['win_streak']} (max {stats['max_win_streak']})")
    print(f"Loss streak: {stats['loss_streak']} (max {stats['max_loss_streak']})")

    print(f"Learning Score: {round(stats['learning_score'], 2)}")

    progress_bar()

    if stats["ready"]:
        print("🚀 BOT READY (EDGE DETECTED)")
    else:
        print("📚 LEARNING...")

    print("========================\n")


# =========================
# EVENT
# =========================
def on_evaluation(trade):
    print("🧠 LEARNING:", trade)

    update_learning(trade)

    print_status()

    save_bot_stats(stats)


event_bus.subscribe(EVALUATION_DONE, on_evaluation)


# =========================
# API
# =========================
def is_ready():
    return stats["ready"]


def get_status():
    return stats


# =========================
# INIT
# =========================
load_history()