from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED, EVALUATION_DONE, TRADE_CLOSED

import random
import time


def simulate_exit_price(entry_price):
    return entry_price * (1 + random.uniform(-0.01, 0.01))


def on_trade(trade):
    print("🔥 EVALUATOR TRIGGERED:", trade)

    time.sleep(1)

    exit_price = simulate_exit_price(trade["entry_price"])

    if trade["action"] == "BUY":
        profit = (exit_price - trade["entry_price"]) / trade["entry_price"]
    else:
        profit = (trade["entry_price"] - exit_price) / trade["entry_price"]

    result = "WIN" if profit > 0 else "LOSS"

    trade["profit"] = profit
    trade["result"] = result
    trade["status"] = "CLOSED"
    trade["exit_price"] = exit_price

    print("📊 EVALUATION RESULT:", trade)
    print("📊 SENDING TO LEARNING")

    event_bus.publish(EVALUATION_DONE, trade)
    event_bus.publish(TRADE_CLOSED, trade)


event_bus.subscribe(TRADE_EXECUTED, on_trade)