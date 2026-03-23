from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_OPENED, TRADE_CLOSED, PRICE_TICK

open_trades = {}

# =========================
# OPEN TRADE
# =========================
def handle_signal(data):
    symbol = data["symbol"]
    price = data["features"]["price"]

    # už otevřený trade? skip
    if symbol in open_trades:
        return

    trade = {
        "symbol": symbol,
        "entry_price": price,
        "steps": 0,  # 🔥 počítadlo ticků
        "strategy": data.get("strategy"),
        "regime": data.get("regime"),
        "confidence": data.get("confidence")
    }

    open_trades[symbol] = trade

    print(f"📈 OPEN {symbol} @ {price}")

    event_bus.publish(TRADE_OPENED, trade)


# =========================
# CLOSE TRADE (FIX!)
# =========================
def on_price(data):
    for symbol, trade in list(open_trades.items()):
        if symbol not in data:
            continue

        trade["steps"] += 1  # 🔥 počítáme čas

        current_price = data[symbol]["price"]
        entry = trade["entry_price"]

        pnl = (current_price - entry) / entry

        # 🔥 ZAVŘI po 5 tickech nebo při zisku/ztrátě
        if trade["steps"] >= 5 or abs(pnl) > 0.001:

            result = "WIN" if pnl > 0 else "LOSS"

            print(f"❌ CLOSE {symbol} pnl={pnl:.4f}")

            event_bus.publish(TRADE_CLOSED, {
                "trade": trade,
                "pnl": pnl,
                "result": result
            })

            del open_trades[symbol]


event_bus.subscribe(SIGNAL_CREATED, handle_signal)
event_bus.subscribe(PRICE_TICK, on_price)