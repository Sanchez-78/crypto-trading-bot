import firebase_admin
from firebase_admin import credentials, firestore
import time

db = None


def init_firebase():
    global db

    if not firebase_admin._apps:
        cred = credentials.Certificate("firebase_key.json")
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    return db


# =========================
# SAVE TRADE
# =========================
def save_trade(trade, result):
    try:
        data = {
            "symbol": trade.get("symbol"),
            "action": trade.get("action"),
            "price": trade.get("price"),
            "confidence": trade.get("confidence"),
            "features": trade.get("features", {}),
            "result": result.get("result"),
            "profit": result.get("profit"),
            "timestamp": time.time()
        }

        db.collection("trades").add(data)

    except Exception as e:
        print("❌ Firebase save_trade error:", e)


# =========================
# LOAD HISTORY
# =========================
def load_trade_history(limit=200):
    try:
        docs = (
            db.collection("trades")
            .order_by("timestamp")
            .limit(limit)
            .stream()
        )

        trades = [doc.to_dict() for doc in docs]

        print(f"📥 Loaded {len(trades)} trades from Firebase")
        return trades

    except Exception as e:
        print("❌ Firebase load error:", e)
        return []