from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import save_bot_stats

import time

# =========================
# CONFIG
# =========================
AUTO_TRADE_ENABLED = True
WRITE_INTERVAL = 30  # sekundy

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
    "ready": False,
    "last_trade": None
}

last_write_time = 0


# =========================
# UPDATE LEARNING
# =========================
def update_learning(trade):
    stats["trades"] += 1

    if trade["result"] == "WIN":
        stats["wins"] += 1
    else:
        stats["losses"] += 1

    stats["winrate"] = stats["wins"] / stats["trades"]

    # průměrný profit
    stats["avg_profit"] = (
        (stats["avg_profit"] * (stats["trades"] - 1) + trade["profit"])
        / stats["trades"]
    )

    # equity simulace
    stats["equity"] += stats["equity"] * trade["profit"]

    # learning score (0–1)
    stats["learning_score"] = (
        stats["winrate"] * 0.7 +
        min(stats["trades"] / 50, 1) * 0.3
    )

    # =========================
    # READY LOGIKA
    # =========================
    stats["ready"] = (
        stats["trades"] > 20 and
        stats["winrate"] > 0.55
    )

    # =========================
    # KILL SWITCH 🔥
    # =========================
    if stats["trades"] > 30 and stats["winrate"] < 0.45:
        stats["ready"] = False
        print("🛑 BOT DISABLED (bad performance)")

    # =========================
    # LAST TRADE
    # =========================
    stats["last_trade"] = {
        "symbol": trade["symbol"],
        "result": trade["result"],
        "profit": trade["profit"]
    }


# =========================
# STATUS PRINT
# =========================
def print_status():
    print("\n🧠 ===== BOT STATUS =====")
    print(f"Trades: {stats['trades']}")
    print(f"Wins: {stats['wins']} | Losses: {stats['losses']}")
    print(f"Winrate: {round(stats['winrate'] * 100, 2)} %")
    print(f"Avg profit: {round(stats['avg_profit'], 4)}")
    print(f"Equity: {round(stats['equity'], 2)}")
    print(f"Learning score: {round(stats['learning_score'], 2)}")

    if stats["last_trade"]:
        lt = stats["last_trade"]
        print(f"Last trade: {lt['symbol']} | {lt['result']} | {round(lt['profit'], 4)}")

    if stats["ready"]:
        print("🚀 BOT JE NAUČEN A PŘIPRAVEN OBCHODOVAT")
    else:
        print("📚 BOT SE STÁLE UČÍ / NEOBCHODUJE")

    print("========================\n")


# =========================
# FIREBASE SAVE (LOW WRITE)
# =========================
def save_to_firebase():
    global last_write_time

    now = time.time()

    if now - last_write_time < WRITE_INTERVAL:
        print("⏳ Skip Firebase write")
        return

    ok = save_bot_stats(stats)

    if ok:
        last_write_time = now


# =========================
# EXTERNAL ACCESS
# =========================
def is_ready():
    return stats["ready"]


def get_status():
    return {
        "ready": stats["ready"],
        "winrate": stats["winrate"],
        "trades": stats["trades"],
        "learning_score": stats["learning_score"]
    }


# =========================
# MAIN EVENT
# =========================
def on_evaluation(trade):
    print("🧠 LEARNING TRIGGERED")

    # safety
    if not isinstance(trade, dict):
        print("⚠️ invalid trade:", trade)
        return

    if "result" not in trade or "profit" not in trade:
        print("⚠️ incomplete trade:", trade)
        return

    update_learning(trade)
    print_status()
    save_to_firebase()


event_bus.subscribe(EVALUATION_DONE, on_evaluation)