from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED, EVALUATION_DONE

import random

print("📊 Evaluator READY")


def on_trade(trade):
    print("📊 EVALUATING TRADE")

    # 🔥 fake evaluation (zatím)
    result = random.choice(["WIN", "LOSS"])
    profit = random.uniform(-0.01, 0.02)

    evaluation = {
        "symbol": trade.get("symbol"),
        "action": trade.get("action"),
        "price": trade.get("price"),
        "result": result,
        "profit": profit,
        "features": trade.get("features", {})  # 🔥 FIX
    }

    print("📊 EVALUATION:", evaluation)

    event_bus.publish(EVALUATION_DONE, evaluation)


event_bus.subscribe(TRADE_EXECUTED, on_trade)