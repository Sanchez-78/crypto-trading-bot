from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_OPENED, TRADE_CLOSED, PRICE_TICK
from src.services.risk_manager import risk_manager
from src.services.auto_control import auto_control

open_trades = {}

TP = 0.004
SL = -0.003
TRAIL = 0.002
PYRAMID_THRESHOLD = 0.002


def handle_signal(data):
    symbol = data["symbol"]
    price = data["features"]["price"]
    confidence = data.get("confidence", 0.5)

    if not auto_control.trading_enabled:
        print("🛑 BLOCKED BY AUTO CONTROL")
        return

    if symbol in open_trades:
        return

    if risk_manager.is_drawdown_exceeded():
        print("🛑 RISK BLOCK")
        return

    size = risk_manager.get_position_size(confidence)

    trade = {
        "symbol": symbol,
        "entry_price": price,
        "size": size,
        "max_pnl": 0,
        "pyramids": 0
    }

    open_trades[symbol] = trade

    print(f"📈 OPEN {symbol} size={size:.2f}")

    event_bus.publish(TRADE_OPENED, trade)


def on_price(data):
    for symbol, trade in list(open_trades.items()):
        if symbol not in data:
            continue

        current = data[symbol]["price"]
        entry = trade["entry_price"]

        pnl = (current - entry) / entry
        trade["max_pnl"] = max(trade["max_pnl"], pnl)

        # PYRAMID
        if pnl > PYRAMID_THRESHOLD and trade["pyramids"] < 2:
            trade["pyramids"] += 1
            trade["size"] *= 1.5
            print(f"📈 PYRAMID {symbol}")

        # TRAILING
        if trade["max_pnl"] - pnl > TRAIL:
            reason = "TRAIL"

        elif pnl >= TP:
            reason = "TP"

        elif pnl <= SL:
            reason = "SL"

        else:
            continue

        result = "WIN" if pnl > 0 else "LOSS"

        print(f"❌ CLOSE {symbol} {reason} pnl={pnl:.4f}")

        risk_manager.update_balance(pnl)

        event_bus.publish(TRADE_CLOSED, {
            "trade": trade,
            "pnl": pnl,
            "result": result,
            "reason": reason
        })

        del open_trades[symbol]


event_bus.subscribe(SIGNAL_CREATED, handle_signal)
event_bus.subscribe(PRICE_TICK, on_price)