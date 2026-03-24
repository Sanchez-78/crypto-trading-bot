from src.core.event_bus import event_bus
from src.core.events import TRADE_CLOSED, EVALUATION_DONE

from src.services.learning_event import update

print("📊 EVALUATOR READY")


def evaluate_trade(trade):
    print("📊 EVALUATING TRADE:", trade)

    profit = trade.get("profit", 0)
    action = trade.get("action")
    features = trade.get("features", {})

    # =========================
    # REWARD (CORE LEARNING)
    # =========================
    reward = profit  # můžeš později vylepšit

    # =========================
    # UPDATE MODEL
    # =========================
    update(features, action, reward)

    result = {
        "symbol": trade.get("symbol"),
        "profit": profit,
        "result": "WIN" if profit > 0 else "LOSS",
        "action": action,
        "features": features
    }

    print("📊 RESULT:", result)

    event_bus.publish(EVALUATION_DONE, result)


# =========================
# EVENT SUBSCRIBE
# =========================
event_bus.subscribe(TRADE_CLOSED, evaluate_trade)