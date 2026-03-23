from src.core.event_bus import event_bus
from src.core.events import TRADE_CLOSED, EVALUATION_DONE

def on_trade_closed(data):
    trade = data["trade"]
    pnl = data["pnl"]

    trade["evaluation"] = {
        "profit": pnl,
        "result": "WIN" if pnl > 0 else "LOSS"
    }

    print(f"📊 EVALUATED → {trade['symbol']} pnl={pnl:.4f}")

    event_bus.publish(EVALUATION_DONE, trade)

event_bus.subscribe(TRADE_CLOSED, on_trade_closed)