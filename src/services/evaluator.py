from src.core.event_bus import event_bus
from src.core.events import TRADE_EXECUTED, EVALUATION_DONE

from src.services.learning_event import update

import random

print("📊 EVALUATOR READY")


def evaluate_trade(trade):
    print("📊 EVALUATING:", trade)

    # =========================
    # SIMULATED RESULT
    # =========================
    profit = random.uniform(-1, 1)

    action = trade.get("action")
    features = trade.get("features", {})

    reward = profit

    update(features, action, reward)

    result = {
        "symbol": trade.get("symbol"),
        "profit": profit,
        "result": "WIN" if profit > 0 else "LOSS"
    }

    print("📊 RESULT:", result)

    event_bus.publish(EVALUATION_DONE, result)


# 🔥 FIX: poslouchá TRADE_EXECUTED
event_bus.subscribe(TRADE_EXECUTED, evaluate_trade)