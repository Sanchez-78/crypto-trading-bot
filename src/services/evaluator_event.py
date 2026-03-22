from src.core.event_bus import event_bus
from src.core.events import TRADE_CLOSED, EVALUATION_DONE


def evaluate_trade(data):
    trade = data["trade"]
    pnl = data["pnl"]

    trade["evaluation"] = {
        "profit": pnl,
        "result": data["result"]
    }

    # 🔥 SAFE GUARDS (aby nikdy nespadl learning)
    if "regime" not in trade:
        trade["regime"] = "UNKNOWN"

    if "strategy" not in trade:
        trade["strategy"] = "UNKNOWN"

    if "meta" not in trade:
        trade["meta"] = {}

    event_bus.publish(EVALUATION_DONE, trade)


event_bus.subscribe(TRADE_CLOSED, evaluate_trade)