import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
import time

db = None
_last_write = 0
WRITE_INTERVAL = 5  # sec (anti spam)


# =========================
# INIT
# =========================
def init_firebase():
    global db

    try:
        key_json = os.getenv("FIREBASE_KEY")

        if not key_json:
            print("❌ FIREBASE_KEY missing")
            return

        key_dict = json.loads(key_json)

        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)

        db = firestore.client()

        print("🔥 Firebase READY")

    except Exception as e:
        print("❌ Firebase init error:", e)


# =========================
# SAFE WRITE (METRICS)
# =========================
def smart_write(data):
    global _last_write, db

    if db is None:
        print("❌ DB NOT READY")
        return

    now = time.time()

    if now - _last_write < WRITE_INTERVAL:
        return

    try:
        db.collection("metrics").document("latest").set(data)
        _last_write = now
        print("📡 metrics write OK")

    except Exception as e:
        print("❌ WRITE ERROR", e)


# =========================
# LAST TRADE
# =========================
def write_last_trade(trade):
    global db

    if db is None:
        return

    try:
        db.collection("metrics").document("last_trade").set(trade)
        print("📡 last_trade write OK")
    except Exception as e:
        print("❌ LAST TRADE ERROR", e)


# =========================
# TRADE HISTORY (OPTIONAL)
# =========================
def log_trade(trade):
    global db

    if db is None:
        return

    try:
        db.collection("trades").add(trade)
    except:
        pass