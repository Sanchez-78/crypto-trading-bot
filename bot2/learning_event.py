from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import buffered_metrics_update

history = []
counter = 0


def on_eval(trade):
    global counter

    history.append(trade)
    counter += 1

    wins = sum(1 for t in history if t["evaluation"]["result"] == "WIN")
    total = len(history)

    winrate = wins / total if total else 0

    # PRINT vždy
    print(f"📊 Trades={total} Winrate={winrate:.2f}")

    # 🔥 FIREBASE jen každých 20 obchodů
    if counter % 10 != 0:
        return

    profits = [t["evaluation"]["profit"] for t in history]
    avg_profit = sum(profits) / total if total else 0

    metrics = {
        "trades": total,
        "winrate": winrate,
        "avg_profit": avg_profit
    }

    print("📡 BATCH SAVE TO FIREBASE")

    buffered_metrics_update(metrics)


event_bus.subscribe(EVALUATION_DONE, on_eval)from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import save_metrics

history = []


def on_eval(trade):
    print("\n🧠 LEARNING TRIGGERED")

    history.append(trade)

    wins = sum(1 for t in history if t["evaluation"]["result"] == "WIN")
    total = len(history)

    winrate = wins / total if total else 0

    profits = [t["evaluation"]["profit"] for t in history]
    avg_profit = sum(profits) / total if total else 0

    print("===================================")
    print(f"📊 TOTAL TRADES: {total}")
    print(f"🎯 WINRATE: {winrate:.2f}")
    print(f"💰 AVG PROFIT: {avg_profit:.5f}")

    # PROGRESS (zlepšuje se?)
    if total > 10:
        first_half = history[:total//2]
        second_half = history[total//2:]

        w1 = sum(1 for t in first_half if t["evaluation"]["result"] == "WIN") / len(first_half)
        w2 = sum(1 for t in second_half if t["evaluation"]["result"] == "WIN") / len(second_half)

        trend = "IMPROVING 📈" if w2 > w1 else "WORSENING 📉"

        print(f"📈 PROGRESS: {trend}")

    print("===================================\n")

    # FIREBASE
    metrics = {
        "trades": total,
        "winrate": winrate,
        "avg_profit": avg_profit
    }

    print("📡 CALLING SAVE_METRICS")

    save_metrics(metrics)


event_bus.subscribe(EVALUATION_DONE, on_eval)