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
    "ready": False,
    "last_trade": None
}


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

    # READY LOGIKA
    stats["ready"] = (
        stats["trades"] > 20 and
        stats["winrate"] > 0.55
    )

    # poslední trade (pro appku)
    stats["last_trade"] = {
        "symbol": trade["symbol"],
        "result": trade["result"],
        "profit": trade["profit"]
    }


# =========================
# PRINT STATUS (LAIK FRIENDLY)
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
        print("📚 BOT SE STÁLE UČÍ")

    print("========================\n")


# =========================
# FIREBASE SAVE (SAFE)
# =========================
def save_to_firebase():
    global db

    if not db:
        print("⚠️ DB not ready — skipping write")
        return

    try:
        db.collection("bot_stats").document("latest").set({
            **stats,
            "timestamp": time.time()
        })
    except Exception as e:
        print("❌ Firebase write error:", e)


# =========================
# MAIN EVENT
# =========================
def on_evaluation(trade):
    print("🧠 LEARNING TRIGGERED")

    # safety (když by přišla špatná data)
    if not isinstance(trade, dict):
        print("⚠️ invalid trade data:", trade)
        return

    if "result" not in trade or "profit" not in trade:
        print("⚠️ incomplete trade:", trade)
        return

    update_learning(trade)
    print_status()
    save_to_firebase()


event_bus.subscribe(EVALUATION_DONE, on_evaluation)