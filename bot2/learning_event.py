from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import smart_write, log_trade

import time
import statistics

# =========================
# STATE
# =========================
history = []

equity = 1000
peak = 1000

last_winrate = None


# =========================
# HELPERS
# =========================
def compute_drawdown():
    global equity, peak

    peak = max(peak, equity)
    return (peak - equity) / peak


def compute_winrate(data):
    if not data:
        return 0
    wins = sum(1 for t in data if t["evaluation"]["result"] == "WIN")
    return wins / len(data)


def compute_avg_profit(data):
    if not data:
        return 0
    return sum(t["evaluation"]["profit"] for t in data) / len(data)


def compute_profit_factor(data):
    profits = [t["evaluation"]["profit"] for t in data]

    gains = sum(p for p in profits if p > 0)
    losses = abs(sum(p for p in profits if p < 0))

    return gains / losses if losses > 0 else 999


def compute_consistency(data):
    profits = [t["evaluation"]["profit"] for t in data]
    if len(profits) < 5:
        return 0

    return 1 / (1 + statistics.stdev(profits))


def compute_score(winrate, profit_factor, drawdown):
    score = 0

    score += winrate * 50
    score += min(profit_factor, 3) * 15
    score += max(0, (1 - drawdown)) * 35

    return round(score, 2)


def compute_status(score, drawdown):
    if drawdown > 0.25:
        return "BROKEN"

    if score > 70:
        return "HEALTHY"

    if score > 50:
        return "RISKY"

    return "BAD"


# =========================
# MAIN
# =========================
def on_eval(trade):
    global equity, last_winrate

    print("\n🧠 LEARNING TRIGGERED")

    history.append(trade)

    pnl = trade["evaluation"]["profit"]
    equity *= (1 + pnl)

    total = len(history)
    winrate = compute_winrate(history)
    avg_profit = compute_avg_profit(history)
    profit_factor = compute_profit_factor(history)
    drawdown = compute_drawdown()
    consistency = compute_consistency(history)

    # =========================
    # TREND
    # =========================
    trend = "STABLE"

    if last_winrate is not None:
        if winrate > last_winrate:
            trend = "IMPROVING"
        elif winrate < last_winrate:
            trend = "WORSENING"

    last_winrate = winrate

    # =========================
    # LEARNING STATE
    # =========================
    learning_state = "UNKNOWN"

    if total > 20:
        first = history[:total//2]
        second = history[total//2:]

        if compute_winrate(second) > compute_winrate(first):
            learning_state = "GOOD"
        else:
            learning_state = "BAD"

    # =========================
    # SCORE + STATUS
    # =========================
    score = compute_score(winrate, profit_factor, drawdown)
    status = compute_status(score, drawdown)

    # =========================
    # PRINT (pro tebe)
    # =========================
    print("===================================")
    print(f"📊 Trades: {total}")
    print(f"🎯 Winrate: {winrate:.2f}")
    print(f"💰 Equity: {equity:.2f}")
    print(f"📉 Drawdown: {drawdown:.2%}")
    print(f"📈 Trend: {trend}")
    print(f"🧠 Learning: {learning_state}")
    print(f"📊 Score: {score}")
    print(f"🚦 Status: {status}")
    print("===================================\n")

    # =========================
    # FIREBASE (EXTERNAL READY)
    # =========================
    metrics = {
        "performance": {
            "trades": total,
            "winrate": winrate,
            "avg_profit": avg_profit,
            "profit_factor": profit_factor
        },
        "equity": {
            "equity": equity,
            "drawdown": drawdown
        },
        "learning": {
            "trend": trend,
            "state": learning_state,
            "consistency": consistency
        },
        "health": {
            "score": score,
            "status": status
        },
        "timestamp": time.time()
    }

    smart_write(metrics)

    # log trade zvlášť
    log_trade(trade)


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(EVALUATION_DONE, on_eval)

print("🧠 Learning engine ready (EXTERNAL MODE)")