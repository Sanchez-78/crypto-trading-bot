import firebase_admin
from firebase_admin import credentials, firestore

import os
import json
import time

print("🔥 FIREBASE CLIENT LOADING...")

db = None
last_write = 0

# =========================
# CONFIG
# =========================
WRITE_INTERVAL = 5  # sec (anti-spam)


# =========================
# INIT
# =========================
def init_firebase():
    global db

    try:
        print("🔥 INIT FIREBASE CALLED")

        if firebase_admin._apps:
            db = firestore.client()
            print("🔥 Firebase reused")
            return db

        # =========================
        # ENV (BASE64 JSON)
        # =========================
        firebase_key = os.getenv("FIREBASE_KEY")

        if firebase_key:
            print("🔥 Using ENV key")

            decoded = json.loads(firebase_key)
            cred = credentials.Certificate(decoded)

        else:
            print("🔥 Using local file")

            cred = credentials.Certificate("firebase_key.json")

        firebase_admin.initialize_app(cred)

        db = firestore.client()

        print("🔥 Firebase initialized OK")

        return db

    except Exception as e:
        print("❌ Firebase init error:", e)
        db = None
        return None


# =========================
# SAFE WRITE
# =========================
def safe_write(collection, doc, data):
    global db, last_write

    if not db:
        print("❌ DB not ready")
        return

    now = time.time()

    if now - last_write < WRITE_INTERVAL:
        return

    try:
        db.collection(collection).document(doc).set(data)
        last_write = now
        print(f"☁️ WRITE OK → {collection}/{doc}")
    except Exception as e:
        print("❌ Firebase write error:", e)


# =========================
# BOT STATS
# =========================
def save_bot_stats(data):
    safe_write("bot_stats", "latest", data)


def load_bot_stats():
    global db

    try:
        doc = db.collection("bot_stats").document("latest").get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print("❌ Load bot stats error:", e)
        return None


# =========================
# PORTFOLIO
# =========================
def save_portfolio(data):
    safe_write("portfolio", "latest", data)


def load_portfolio():
    global db

    try:
        doc = db.collection("portfolio").document("latest").get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print("❌ Load portfolio error:", e)
        return None


# =========================
# SIGNALS (light logging)
# =========================
def save_signal(signal):
    global db

    if not db:
        return

    try:
        db.collection("signals").add({
            "symbol": signal.get("symbol"),
            "action": signal.get("action"),
            "confidence": signal.get("confidence"),
            "price": signal.get("price"),
            "time": time.time()
        })
    except Exception as e:
        print("❌ Signal save error:", e)


# =========================
# TRADES (light logging)
# =========================
def save_trade(trade):
    global db

    if not db:
        return

    try:
        db.collection("trades").add({
            "symbol": trade.get("symbol"),
            "action": trade.get("action"),
            "price": trade.get("price"),
            "confidence": trade.get("confidence"),
            "time": time.time()
        })
    except Exception as e:
        print("❌ Trade save error:", e)


# =========================
# DEBUG TEST
# =========================
def test_write():
    print("🧪 TEST FIREBASE WRITE...")

    safe_write("bot_stats", "latest", {
        "test": True,
        "time": time.time()
    })