from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED, EVALUATION_DONE

import random

print("📊 EVALUATOR READY")


def on_trade(trade):
    try:
        price = trade.get("price")

        if price is None:
            print("❌ Missing price in trade")
            return

        # simulace výsledku
        profit = random.uniform(-0.01, 0.02)

        result = {
            "symbol": trade["symbol"],
            "profit": profit,
            "result": "WIN" if profit > 0 else "LOSS"
        }

        print("📊 RESULT:", result)

        event_bus.publish(EVALUATION_DONE, result)

    except Exception as e:
        print("❌ Evaluation error:", e)


event_bus.subscribe(TRADE_EXECUTED, on_trade)