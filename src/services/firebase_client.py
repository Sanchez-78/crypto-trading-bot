import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
import base64
import time

db = None


# =========================
# INIT FIREBASE
# =========================
def init_firebase():
    global db

    if firebase_admin._apps:
        return firestore.client()

    try:
        print("🔥 INIT FIREBASE CALLED")

        firebase_base64 = os.getenv("FIREBASE_KEY_BASE64")
        firebase_json = os.getenv("FIREBASE_CREDENTIALS")

        # =========================
        # BASE64 (Railway)
        # =========================
        if firebase_base64:
            print("🔐 Using BASE64 ENV")

            decoded = base64.b64decode(firebase_base64)
            cred_dict = json.loads(decoded)

            cred = credentials.Certificate(cred_dict)

        # =========================
        # JSON ENV
        # =========================
        elif firebase_json:
            print("🔐 Using JSON ENV")

            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)

        else:
            print("⚠️ No Firebase ENV → running WITHOUT DB")
            return None  # ❗ žádný crash

        firebase_admin.initialize_app(cred)

        db = firestore.client()

        print("🔥 Firebase initialized OK")
        return db

    except Exception as e:
        print("❌ Firebase init error:", e)
        return None


# =========================
# GET DB SAFE
# =========================
def get_db():
    return db


# =========================
# SAVE TRADE
# =========================
def save_trade(trade, result):
    global db

    if db is None:
        return

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
# SAVE BOT STATS (bonus)
# =========================
def save_bot_stats(stats):
    global db

    if db is None:
        return

    try:
        db.collection("bot_stats").document("latest").set(stats)

    except Exception as e:
        print("❌ Firebase save_bot_stats error:", e)


# =========================
# LOAD TRADE HISTORY 🔥
# =========================
def load_trade_history(limit=200):
    global db

    if db is None:
        print("⚠️ DB not ready → no history")
        return []

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


# =========================
# LOAD BOT STATS (bonus)
# =========================
def load_bot_stats():
    global db

    if db is None:
        return None

    try:
        doc = db.collection("bot_stats").document("latest").get()

        if doc.exists:
            return doc.to_dict()

        return None

    except Exception as e:
        print("❌ Firebase load_bot_stats error:", e)
        return None