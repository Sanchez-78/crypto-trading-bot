from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import save_metrics

history = []

def on_eval(trade):
    history.append(trade)

    wins = sum(1 for t in history if t["evaluation"]["result"] == "WIN")
    total = len(history)

    winrate = wins / total if total else 0

    print("\n====================")
    print(f"📊 Trades: {total}")
    print(f"🎯 Winrate: {winrate:.2f}")
    print("====================\n")

    # 🔥 FIREBASE TEST
    save_metrics({
        "trades": total,
        "winrate": winrate
    })

event_bus.subscribe(EVALUATION_DONE, on_eval)