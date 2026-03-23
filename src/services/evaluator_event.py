from src.core.event_bus import event_bus
from src.core.events import TRADE_CLOSED, EVALUATION_DONE


def on_trade_closed(data):
    try:
        trade = data["trade"]
        pnl = data["pnl"]
        result = data["result"]

        # =========================
        # EVALUATION
        # =========================
        trade["evaluation"] = {
            "profit": pnl,
            "result": result
        }

        print(f"📊 EVALUATED: {trade['symbol']} pnl={pnl:.4f}")

        # =========================
        # 🔥 POSÍLÁME DO LEARNING
        # =========================
        event_bus.publish(EVALUATION_DONE, trade)

    except Exception as e:
        print(f"❌ evaluator error: {e}")


event_bus.subscribe(TRADE_CLOSED, on_trade_closed)