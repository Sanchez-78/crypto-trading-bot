from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED, EVALUATION_DONE, TRADE_CLOSED
import random


def on_trade(trade):
    print("🔥 EVALUATOR TRIGGERED")

    profit = random.uniform(-0.02, 0.03)
    result = "WIN" if profit > 0 else "LOSS"

    trade["evaluation"] = {
        "profit": profit,
        "result": result
    }

    print("📊 EVALUATION:", trade)

    # 🔥 publish evaluation
    event_bus.publish(EVALUATION_DONE, trade)

    # 🔥 close trade (pro portfolio)
    event_bus.publish(TRADE_CLOSED, trade)


event_bus.subscribe(TRADE_EXECUTED, on_trade)

print("📊 Evaluator READY")