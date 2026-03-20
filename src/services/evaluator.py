from datetime import datetime
from src.services.firebase_client import get_db, update_signal


def evaluate_signals(symbol):
    try:
        db = get_db()
        if db is None:
            print("❌ No DB")
            return

        docs = db.collection("signals") \
            .where("symbol", "==", symbol) \
            .where("evaluated", "==", False) \
            .stream()

        signals = [(d.id, d.to_dict()) for d in docs]

        print(f"🔎 Found {len(signals)} signals for {symbol}")

        for doc_id, signal in signals:
            try:
                price = signal.get("price")
                action = signal.get("signal")

                if not price or not action:
                    continue

                # ❗ fake evaluation (zatím)
                current_price = price * 0.995  # simulace pohybu

                profit = 0

                if action == "BUY":
                    profit = (current_price - price) / price
                elif action == "SELL":
                    profit = (price - current_price) / price

                result = "WIN" if profit > 0 else "LOSS"

                print(f"{action} → {result} | 💰 {round(profit, 4)}")

                update_signal(doc_id, {
                    "evaluated": True,
                    "profit": float(profit),
                    "result": result,
                    "evaluated_at": datetime.utcnow().isoformat()
                })

            except Exception as e:
                print("❌ Eval signal error:", e)

    except Exception as e:
        print("❌ Evaluator error:", e)