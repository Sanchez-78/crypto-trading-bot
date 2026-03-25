from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED, TRADE_CLOSED

import random

print("📦 PORTFOLIO MANAGER READY")

portfolio = {
    "open_trades": [],
    "closed_trades": [],
    "balance": 10000
}


def on_trade_executed(trade):
    print("📦 ADDING TRADE TO PORTFOLIO")

    if not isinstance(trade, dict):
        print("❌ Invalid trade:", trade)
        return

    price = trade.get("price")

    if price is None:
        print("❌ Missing price in trade:", trade)
        return

    portfolio["open_trades"].append(trade)


def close_trade(trade):
    # =========================
    # SIMULACE PROFITU
    # =========================
    profit = random.uniform(-1, 1)

    trade["profit"] = profit
    trade["status"] = "CLOSED"

    portfolio["open_trades"].remove(trade)
    portfolio["closed_trades"].append(trade)

    print("📦 TRADE CLOSED:", trade)

    # 🔥 EVENT → evaluator
    event_bus.publish(TRADE_CLOSED, trade)


def process_portfolio():
    # zavíráme všechny otevřené trady (simple simulace)
    for trade in portfolio["open_trades"][:]:
        close_trade(trade)


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(TRADE_EXECUTED, on_trade_executed)

# 🔁 pravidelné zavírání (hookneš v main loopu)