from datetime import datetime
from src.services.firebase_client import get_db, update_signal
from src.services.market_data import get_all_prices

HOLD_CYCLES = 3


def evaluate_signals(symbol):
    try:
        db = get_db()
        if db is None:
            return

        prices = get_all_prices()

        docs = db.collection("signals") \
            .where("symbol", "==", symbol) \
            .where("evaluated", "==", False) \
            .stream()

        signals = [(d.id, d.to_dict()) for d in docs]

        for doc_id, signal in signals:
            try:
                age = signal.get("age", 0)

                if age < HOLD_CYCLES:
                    update_signal(doc_id, {"age": age + 1})
                    continue

                price = signal.get("price")
                action = signal.get("signal")

                current_price = prices.get(symbol, price)

                profit = 0

                if action == "BUY":
                    profit = (current_price - price) / price
                elif action == "SELL":
                    profit = (price - current_price) / price

                result = "WIN" if profit > 0 else "LOSS"

                update_signal(doc_id, {
                    "evaluated": True,
                    "profit": float(profit),
                    "result": result,
                    "evaluated_at": datetime.utcnow().isoformat()
                })

            except Exception as e:
                print("❌ Eval error:", e)

    except Exception as e:
        print("❌ Evaluator error:", e)