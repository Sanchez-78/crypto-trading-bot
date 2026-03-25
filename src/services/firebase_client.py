import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
import base64
import time

db = None


# =========================
# INIT
# =========================
def init_firebase():
    global db

    if firebase_admin._apps:
        return firestore.client()

    try:
        firebase_base64 = os.getenv("FIREBASE_KEY_BASE64")

        if not firebase_base64:
            print("⚠️ No Firebase ENV → running without DB")
            return None

        decoded = base64.b64decode(firebase_base64)
        cred_dict = json.loads(decoded)

        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)

        db = firestore.client()
        print("🔥 Firebase ready")

        return db

    except Exception as e:
        print("❌ Firebase error:", e)
        return None


# =========================
# LOAD HISTORY (LOW READ)
# =========================
def load_trade_history(limit=50):
    global db

    if db is None:
        return []

    try:
        docs = (
            db.collection("trades")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )

        return [d.to_dict() for d in docs]

    except Exception as e:
        print("❌ load error:", e)
        return []


# =========================
# SAVE TRADE (FILTERED)
# =========================
def save_trade(trade, result):
    global db

    if db is None:
        return

    try:
        profit = result.get("profit", 0)

        # 🔥 filtr (šetří writes)
        if abs(profit) < 0.001:
            return

        db.collection("trades").add({
            "symbol": trade.get("symbol"),
            "action": trade.get("action"),
            "features": trade.get("features"),
            "result": result.get("result"),
            "profit": profit,
            "timestamp": time.time()
        })

    except Exception as e:
        print("❌ save_trade error:", e)


# =========================
# SAVE STATS (THROTTLED)
# =========================
_last_stats_save = 0


def save_bot_stats(stats):
    global db, _last_stats_save

    if db is None:
        return

    # 🔥 max 1× za 30s
    if time.time() - _last_stats_save < 30:
        return

    try:
        db.collection("bot_stats").document("latest").set(stats)
        _last_stats_save = time.time()

    except Exception as e:
        print("❌ stats error:", e)