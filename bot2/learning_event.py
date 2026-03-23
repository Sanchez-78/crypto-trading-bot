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

# 🔥 WRITE CONTROL
last_write_time = 0
WRITE_INTERVAL = 30  # sekund (≈ max 2880 zápisů/den)


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
        stats["trades"] > 20 and
        stats["winrate"] > 0.55
    )

    stats["last_trade"] = {
        "symbol": trade["symbol"],
        "result": trade["result"],
        "profit": trade["profit"]
    }


# =========================
# PRINT STATUS
# =========================
def print_status():
    print("\n🧠 ===== BOT STATUS =====")
    print(f"Trades: {stats['trades']}")
    print(f"Winrate: {round(stats['winrate'] * 100, 2)} %")
    print(f"Equity: {round(stats['equity'], 2)}")

    if stats["ready"]:
        print("🚀 READY")
    else:
        print("📚 LEARNING")

    print("========================\n")


# =========================
# 🔥 SMART FIREBASE WRITE
# =========================
def save_to_firebase():
    global db, last_write_time

    if not db:
        print("⚠️ DB not ready")
        return

    now = time.time()

    # 🔥 LIMIT WRITE RATE
    if now - last_write_time < WRITE_INTERVAL:
        print("⏳ Skip Firebase write (rate limit)")
        return

    try:
        db.collection("bot_stats").document("latest").set({
            **stats,
            "timestamp": now
        })

        last_write_time = now

        print("☁️ Firebase write OK")

    except Exception as e:
        print("❌ Firebase write error:", e)


# =========================
# MAIN EVENT
# =========================
def on_evaluation(trade):
    print("🧠 LEARNING TRIGGERED")

    if not isinstance(trade, dict):
        return

    if "result" not in trade or "profit" not in trade:
        return

    update_learning(trade)
    print_status()
    save_to_firebase()


event_bus.subscribe(EVALUATION_DONE, on_evaluation)