from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_OPENED, TRADE_CLOSED

open_trades = {}

def handle_signal(data):
    symbol = data["symbol"]
    price = data["features"]["price"]

    # 🔥 vždy otevři trade (DEBUG MODE)
    trade = {
        "symbol": symbol,
        "entry_price": price,
        "timestamp": 0,
        "strategy": data.get("strategy"),
        "regime": data.get("regime"),
        "confidence": data.get("confidence")
    }

    open_trades[symbol] = trade

    print(f"📈 OPEN {symbol} @ {price}")

    event_bus.publish(TRADE_OPENED, trade)


def on_price(data):
    for symbol, trade in list(open_trades.items()):
        if symbol not in data:
            continue

        current_price = data[symbol]["price"]
        entry = trade["entry_price"]

        pnl = (current_price - entry) / entry

        # 🔥 zavři rychle (DEBUG)
        if abs(pnl) > 0.001:
            result = "WIN" if pnl > 0 else "LOSS"

            print(f"❌ CLOSE {symbol} pnl={pnl:.4f}")

            event_bus.publish(TRADE_CLOSED, {
                "trade": trade,
                "pnl": pnl,
                "result": result
            })

            del open_trades[symbol]


event_bus.subscribe(SIGNAL_CREATED, handle_signal)
event_bus.subscribe("price_tick", on_price)