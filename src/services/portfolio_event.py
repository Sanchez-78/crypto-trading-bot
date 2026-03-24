from src.core.event_bus import event_bus
from src.core.events import SIGNAL_CREATED, TRADE_EXECUTED, TRADE_CLOSED
from src.services.firebase_client import save_portfolio

import time

print("📊 Portfolio Service READY")

# =========================
# STATE
# =========================
portfolio = {
    "open_position": None,
    "balance": 1000,
    "equity": 1000,
    "total_trades": 0,
    "wins": 0,
    "losses": 0,
    "last_update": None
}


# =========================
# HELPERS
# =========================
def safe_price(obj):
    price = obj.get("price") if isinstance(obj, dict) else None

    if price is None:
        print("❌ Missing price:", obj)
        return None

    return price


# =========================
# SIGNAL HANDLER (optional)
# =========================
def on_signal(signal):
    print("📡 PORTFOLIO SIGNAL RECEIVED")

    price = safe_price(signal)
    if price is None:
        return

    # pouze log (neotevírá pozici)
    print(f"📊 SIGNAL {signal.get('action')} @ {price}")


# =========================
# TRADE EXECUTED
# =========================
def on_trade(trade):
    print("📊 PORTFOLIO TRADE")

    price = safe_price(trade)
    if price is None:
        return

    action = trade.get("action")

    # =========================
    # OPEN POSITION
    # =========================
    if portfolio["open_position"] is None:
        portfolio["open_position"] = {
            "symbol": trade.get("symbol"),
            "action": action,
            "entry_price": price,
            "size": 1,
            "opened_at": time.time()
        }

        print("📈 OPEN POSITION:", portfolio["open_position"])
        save()
        return

    # =========================
    # CLOSE POSITION (opposite)
    # =========================
    current = portfolio["open_position"]

    if current["action"] != action:
        entry = current["entry_price"]

        if current["action"] == "BUY":
            profit = (price - entry) / entry
        else:
            profit = (entry - price) / entry

        portfolio["balance"] += portfolio["balance"] * profit
        portfolio["equity"] = portfolio["balance"]

        portfolio["total_trades"] += 1

        if profit > 0:
            portfolio["wins"] += 1
        else:
            portfolio["losses"] += 1

        closed_trade = {
            "symbol": current["symbol"],
            "entry": entry,
            "exit": price,
            "profit": profit,
            "result": "WIN" if profit > 0 else "LOSS"
        }

        print("📉 CLOSED TRADE:", closed_trade)

        # reset position
        portfolio["open_position"] = None

        event_bus.publish(TRADE_CLOSED, closed_trade)

        save()


# =========================
# SAVE
# =========================
def save():
    portfolio["last_update"] = time.time()

    save_portfolio(portfolio)


# =========================
# METRICS FOR APP
# =========================
def get_portfolio():
    return {
        "balance": portfolio["balance"],
        "equity": portfolio["equity"],
        "open_position": portfolio["open_position"],
        "total_trades": portfolio["total_trades"],
        "wins": portfolio["wins"],
        "losses": portfolio["losses"],
        "winrate": (
            portfolio["wins"] / portfolio["total_trades"]
            if portfolio["total_trades"] > 0 else 0
        ),
        "last_update": portfolio["last_update"]
    }


# =========================
# SUBSCRIBE
# =========================
event_bus.subscribe(SIGNAL_CREATED, on_signal)
event_bus.subscribe(TRADE_EXECUTED, on_trade)