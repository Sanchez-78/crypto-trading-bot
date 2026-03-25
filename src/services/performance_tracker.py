from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE

print("📈 PERFORMANCE TRACKER READY")

stats = {
    "wins": 0,
    "losses": 0
}


def on_evaluation(result):
    if result["result"] == "WIN":
        stats["wins"] += 1
    else:
        stats["losses"] += 1

    total = stats["wins"] + stats["losses"]
    winrate = (stats["wins"] / total) * 100 if total > 0 else 0

    print(f"📈 PERFORMANCE → Trades: {total}, Winrate: {round(winrate,2)}%")


event_bus.subscribe(EVALUATION_DONE, on_evaluation)