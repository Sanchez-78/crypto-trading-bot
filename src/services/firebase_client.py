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

        # ✅ Railway BASE64
        base64_key = os.getenv("FIREBASE_KEY_BASE64")

        if base64_key:
            print("🔥 Using BASE64 ENV")

            decoded = base64.b64decode(base64_key).decode("utf-8")
            cred_dict = json.loads(decoded)

            cred = credentials.Certificate(cred_dict)

        # ✅ fallback (lokální)
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
# BOT STATS (KRITICKÉ)
# =========================
def save_bot_stats(data):
    global db

    if not db:
        print("❌ DB NOT READY")
        return

    try:
        db.collection("bot_stats").document("latest").set(data)
        print("☁️ WRITE OK → bot_stats/latest")
    except Exception as e:
        print("❌ Write error:", e)


def load_bot_stats():
    global db

    if not db:
        return None

    try:
        doc = db.collection("bot_stats").document("latest").get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print("❌ Load error:", e)
        return None


# =========================
# PORTFOLIO
# =========================
def save_portfolio(data):
    global db

    if not db:
        return

    try:
        db.collection("portfolio").document("latest").set(data)
        print("☁️ WRITE OK → portfolio/latest")
    except Exception as e:
        print("❌ Portfolio error:", e)


def load_portfolio():
    global db

    if not db:
        return None

    try:
        doc = db.collection("portfolio").document("latest").get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        print("❌ Portfolio load error:", e)
        return None


# =========================
# SIGNALS
# =========================
def save_signal(signal):
    global db

    if not db:
        return

    try:
        db.collection("signals").add(signal)
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
        db.collection("trades").add(trade)
    except Exception as e:
        print("❌ Trade save error:", e)