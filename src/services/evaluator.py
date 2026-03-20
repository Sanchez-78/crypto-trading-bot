from datetime import datetime
from src.services.firebase_client import get_db, update_signal
from src.services.market_data import get_all_prices
from google.cloud.firestore_v1.base_query import FieldFilter

HOLD_CYCLES = 3


def evaluate_signals(symbol):
    db = get_db()
    if db is None:
        return

    prices = get_all_prices()

    docs = db.collection("signals") \
        .where(filter=FieldFilter("symbol", "==", symbol)) \
        .where(filter=FieldFilter("evaluated", "==", False)) \
        .stream()

    for d in docs:
        doc_id = d.id
        signal = d.to_dict()

        age = signal.get("age", 0)

        if age < HOLD_CYCLES:
            update_signal(doc_id, {"age": age + 1})
            continue

        price = signal.get("price")
        action = signal.get("signal")

        current_price = prices.get(symbol, price)

        if action == "BUY":
            profit = (current_price - price) / price
        elif action == "SELL":
            profit = (price - current_price) / price
        else:
            profit = 0

        result = "WIN" if profit > 0 else "LOSS"

        update_signal(doc_id, {
            "evaluated": True,
            "profit": float(profit),
            "result": result,
            "evaluated_at": datetime.utcnow().isoformat()
        })