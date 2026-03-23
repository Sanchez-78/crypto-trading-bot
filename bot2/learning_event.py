from src.core.event_bus import event_bus
from src.core.events import EVALUATION_DONE
from src.services.firebase_client import smart_write, log_trade
from src.services.auto_control import auto_control

import time
import statistics

history = []

equity = 1000
peak = 1000
last_winrate = None


def compute_drawdown():
    global equity, peak
    peak = max(peak, equity)
    return (peak - equity) / peak


def compute_winrate(data):
    wins = sum(1 for t in data if t["evaluation"]["result"] == "WIN")
    return wins / len(data) if data else 0


def compute_profit_factor(data):
    profits = [t["evaluation"]["profit"] for t in data]
    gains = sum(p for p in profits if p > 0)
    losses = abs(sum(p for p in profits if p < 0))
    return gains / losses if losses > 0 else 999


def compute_score(winrate, pf, dd):
    return round(winrate * 50 + min(pf, 3) * 15 + (1 - dd) * 35, 2)


def compute_status(score, dd):
    if dd > 0.25:
        return "BROKEN"
    if score > 70:
        return "HEALTHY"
    if score > 50:
        return "RISKY"
    return "BAD"


def on_eval(trade):
    global equity, last_winrate

    history.append(trade)

    pnl = trade["evaluation"]["profit"]
    equity *= (1 + pnl)

    total = len(history)
    winrate = compute_winrate(history)
    pf = compute_profit_factor(history)
    dd = compute_drawdown()

    trend = "STABLE"
    if last_winrate:
        if winrate > last_winrate:
            trend = "IMPROVING"
        elif winrate < last_winrate:
            trend = "WORSENING"

    last_winrate = winrate

    score = compute_score(winrate, pf, dd)
    status = compute_status(score, dd)

    print("===================================")
    print(f"📊 Trades: {total}")
    print(f"🎯 Winrate: {winrate:.2f}")
    print(f"💼 Equity: {equity:.2f}")
    print(f"📉 DD: {dd:.2%}")
    print(f"📈 Trend: {trend}")
    print(f"📊 Score: {score}")
    print(f"🚦 Status: {status}")
    print("===================================\n")

    metrics = {
        "performance": {
            "trades": total,
            "winrate": winrate,
            "profit_factor": pf
        },
        "equity": {
            "equity": equity,
            "drawdown": dd
        },
        "learning": {
            "trend": trend
        },
        "health": {
            "score": score,
            "status": status
        },
        "timestamp": time.time()
    }

    smart_write(metrics)

    # 🔥 AUTO CONTROL UPDATE
    auto_control.update(metrics)

    log_trade(trade)


event_bus.subscribe(EVALUATION_DONE, on_eval)

print("🧠 Learning + AutoControl READY")