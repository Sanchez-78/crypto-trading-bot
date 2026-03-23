import time
from src.services.firebase_client import db


def get_open_trades():
    docs = db.collection("trades") \
        .where("status", "==", "OPEN") \
        .stream()

    trades = []
    for d in docs:
        data = d.to_dict()
        data["id"] = d.id
        trades.append(data)

    return trades


def close_trade(trade_id, exit_price):
    ref = db.collection("trades").document(trade_id)
    trade = ref.get().to_dict()

    if not trade:
        return

    entry = trade["entry_price"]

    pnl = (exit_price - entry) / entry

    result = "WIN" if pnl > 0 else "LOSS"

    ref.update({
        "exit_price": exit_price,
        "status": "CLOSED",
        "pnl": pnl,
        "result": result,
        "closed_at": time.time()
    })