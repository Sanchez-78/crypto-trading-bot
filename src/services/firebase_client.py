import firebase_admin
from firebase_admin import credentials, firestore

import os
import json
import base64
import time

print("🔥 FIREBASE CLIENT LOADING...")

db = None


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

        cred = None

        # =========================
        # 1. BASE64 ENV (Railway)
        # =========================
        base64_key = os.getenv("FIREBASE_KEY_BASE64")

        if base64_key:
            print("🔥 Using BASE64 ENV key")

            decoded = base64.b64decode(base64_key).decode("utf-8")
            cred_dict = json.loads(decoded)

            cred = credentials.Certificate(cred_dict)

        # =========================
        # 2. RAW JSON ENV
        # =========================
        elif os.getenv("FIREBASE_CREDENTIALS"):
            print("🔥 Using RAW ENV key")

            cred_dict = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
            cred = credentials.Certificate(cred_dict)

        # =========================
        # 3. FILE FALLBACK
        # =========================
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
# SAFE CHECK
# =========================
def is_ready():
    return db is not None


# =========================
# BOT STATS
# =========================
def save_bot_stats(data):
    global db

    if not db:
        print("❌ DB not ready (bot_stats)")
        return

    try:
        db.collection("bot_stats").document("latest").set(data)
        print("☁️ WRITE OK → bot_stats/latest")
    except Exception as e:
        print("❌ Write bot_stats error:", e)


def load_bot_stats():
    global db

    if not db:
        return None

    try:
        doc = db.collection("bot_stats").document("latest").get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print("❌ Load bot_stats error:", e)
        return None


# =========================
# PORTFOLIO
# =========================
def save_portfolio(data):
    global db

    if not db:
        print("❌ DB not ready (portfolio)")
        return

    try:
        db.collection("portfolio").document("latest").set(data)
        print("☁️ WRITE OK → portfolio/latest")
    except Exception as e:
        print("❌ Portfolio write error:", e)


def load_portfolio():
    global db

    if not db:
        return None

    try:
        doc = db.collection("portfolio").document("latest").get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print("❌ Load portfolio error:", e)
        return None


# =========================
# SIGNALS
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
# TRADES
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
# DEBUG
# =========================
def test_write():
    print("🧪 TEST FIREBASE WRITE")

    save_bot_stats({
        "test": True,
        "time": time.time()
    })