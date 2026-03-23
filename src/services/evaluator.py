from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED, EVALUATION_DONE, TRADE_CLOSED
import random


def on_trade(trade):
    print("🔥 EVALUATOR TRIGGERED")

    profit = random.uniform(-0.02, 0.03)
    result = "WIN" if profit > 0 else "LOSS"

    # 🔥 sjednocený model (žádné trade["evaluation"])
    trade["profit"] = profit
    trade["result"] = result
    trade["status"] = "CLOSED"
    trade["exit_price"] = random.uniform(100, 50000)

    print("📊 EVALUATION:", trade)

    event_bus.publish(EVALUATION_DONE, trade)
    event_bus.publish(TRADE_CLOSED, trade)


event_bus.subscribe(TRADE_EXECUTED, on_trade)

print("📊 Evaluator READY")