from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_OPENED, TRADE_CLOSED, PRICE_TICK

open_trades = {}

print("📊 Portfolio initialized")


def handle_signal(data):
    symbol = data["symbol"]
    price = data["features"]["price"]

    print(f"\n📥 SIGNAL {symbol}")

    if symbol in open_trades:
        return

    trade = {
        "symbol": symbol,
        "entry_price": price,
        "steps": 0,
        "strategy": data.get("strategy"),
        "regime": data.get("regime")
    }

    open_trades[symbol] = trade

    print(f"📈 OPEN {symbol} @ {price}")

    event_bus.publish(TRADE_OPENED, trade)


def on_price(data):
    if not open_trades:
        return

    for symbol, trade in list(open_trades.items()):
        if symbol not in data:
            continue

        trade["steps"] += 1

        current = data[symbol]["price"]
        entry = trade["entry_price"]

        pnl = (current - entry) / entry

        print(f"⏳ {symbol} step={trade['steps']} pnl={pnl:.5f}")

        # DEBUG CLOSE
        if trade["steps"] >= 5:
            result = "WIN" if pnl > 0 else "LOSS"

            print(f"❌ CLOSE {symbol} pnl={pnl:.5f}")

            event_bus.publish(TRADE_CLOSED, {
                "trade": trade,
                "pnl": pnl,
                "result": result
            })

            del open_trades[symbol]


event_bus.subscribe(SIGNAL_CREATED, handle_signal)
event_bus.subscribe(PRICE_TICK, on_price)