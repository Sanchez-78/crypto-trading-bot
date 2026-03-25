from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE

from src.services.firebase_client import load_trade_history

print("🧠 LEARNING SYSTEM READY")

metrics = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "profit": 0.0,
    "loss_streak": 0,
}

# =========================
# 🔥 BOOTSTRAP FROM DB
# =========================
def bootstrap_learning():
    history = load_trade_history()

    for trade in history:
        metrics["trades"] += 1
        metrics["profit"] += trade.get("profit", 0)

        if trade.get("result") == "WIN":
            metrics["wins"] += 1
        else:
            metrics["losses"] += 1

    print(f"🧠 Bootstrapped: {metrics['trades']} trades")


# =========================
# UPDATE FROM LIVE
# =========================
def on_evaluation(result):
    metrics["trades"] += 1
    metrics["profit"] += result.get("profit", 0)

    if result["result"] == "WIN":
        metrics["wins"] += 1
        metrics["loss_streak"] = 0
    else:
        metrics["losses"] += 1
        metrics["loss_streak"] += 1


# =========================
# METRICS
# =========================
def get_metrics():
    trades = metrics["trades"]
    winrate = metrics["wins"] / trades if trades else 0

    progress = min((winrate * trades) / 100, 1.0)

    return {
        **metrics,
        "winrate": winrate,
        "progress": progress
    }


event_bus.subscribe(EVALUATION_DONE, on_evaluation)