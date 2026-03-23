from src.core.event_bus import event_bus
from src.core.events import TRADE_CLOSED, EVALUATION_DONE


def on_closed(data):
    trade = data["trade"]
    pnl = data["pnl"]

    trade["evaluation"] = {
        "profit": pnl,
        "result": data["result"]
    }

    print(f"📊 EVALUATED {trade['symbol']} pnl={pnl:.5f}")

    event_bus.publish(EVALUATION_DONE, trade)


event_bus.subscribe(TRADE_CLOSED, on_closed)