from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED, TRADE_CLOSED

import random

print("📦 PORTFOLIO MANAGER READY")

portfolio = {
    "open": [],
    "closed": [],
    "balance": 10000
}


def on_trade_executed(trade):
    try:
        if not isinstance(trade, dict):
            print("❌ Invalid trade:", trade)
            return

        price = trade.get("price")

        if price is None:
            print("❌ Missing price in trade:", trade)
            return

        portfolio["open"].append(trade)

    except Exception as e:
        print("❌ portfolio error:", e)


def process_portfolio():
    for trade in portfolio["open"][:]:
        try:
            profit = random.uniform(-1, 1)

            trade["profit"] = profit
            trade["status"] = "CLOSED"

            portfolio["open"].remove(trade)
            portfolio["closed"].append(trade)

            print("📦 TRADE CLOSED:", trade)

            event_bus.publish(TRADE_CLOSED, trade)

        except Exception as e:
            print("❌ close trade error:", e)


event_bus.subscribe(TRADE_EXECUTED, on_trade_executed)