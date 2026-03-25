from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE

print("🧠 LEARNING SYSTEM READY")

metrics = {
    "trades": 0,
    "wins": 0,
    "losses": 0,
    "profit": 0.0,
    "loss_streak": 0,
    "penalty": 0,
}

# adaptive threshold
MIN_CONFIDENCE = 0.5


def on_evaluation(result):
    global MIN_CONFIDENCE

    try:
        metrics["trades"] += 1
        metrics["profit"] += result.get("profit", 0)

        if result["result"] == "WIN":
            metrics["wins"] += 1
            metrics["loss_streak"] = 0

            # reward → sníží restrikci
            MIN_CONFIDENCE = max(0.5, MIN_CONFIDENCE - 0.01)

        else:
            metrics["losses"] += 1
            metrics["loss_streak"] += 1
            metrics["penalty"] += 1

            # penalizace → zpřísní strategii
            MIN_CONFIDENCE = min(0.9, MIN_CONFIDENCE + 0.02)

        print(f"🧠 Updated MIN_CONFIDENCE: {MIN_CONFIDENCE:.2f}")

    except Exception as e:
        print("❌ Learning error:", e)


def get_metrics():
    trades = metrics["trades"]
    winrate = metrics["wins"] / trades if trades > 0 else 0

    # 🔥 KVALITNÍ PROGRESS (ne jen trades)
    progress = min((winrate * trades) / 100, 1.0)

    return {
        **metrics,
        "winrate": winrate,
        "progress": progress,
        "epsilon": 1 - winrate
    }


event_bus.subscribe(EVALUATION_DONE, on_evaluation)