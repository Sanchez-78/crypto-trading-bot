import os
import json
import time
import base64
import firebase_admin
from firebase_admin import credentials, firestore

db = None
_last_write = 0
WRITE_INTERVAL = 5  # debug


# =========================
# INIT
# =========================
def init_firebase():
    global db

    print("🔥 INIT FIREBASE CALLED")

    try:
        if firebase_admin._apps:
            db = firestore.client()
            return db

        firebase_b64 = os.getenv("FIREBASE_KEY_BASE64")

        if firebase_b64:
            decoded = base64.b64decode(firebase_b64).decode("utf-8")
            cred_dict = json.loads(decoded)
        else:
            firebase_json = os.getenv("FIREBASE_KEY")
            firebase_json = firebase_json.replace('\\n', '\n')
            cred_dict = json.loads(firebase_json)

        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)

        db = firestore.client()

        print("🔥 Firebase initialized OK")
        return db

    except Exception as e:
        print("❌ Firebase init error:", e)
        return None


# =========================
# CORE WRITE
# =========================
def safe_set(collection, doc, data):
    global db, _last_write

    if not db:
        print("⚠️ DB not ready")
        return False

    now = time.time()

    if now - _last_write < WRITE_INTERVAL:
        return False

    try:
        db.collection(collection).document(doc).set(data)
        _last_write = now
        print(f"☁️ WRITE OK → {collection}/{doc}")
        return True

    except Exception as e:
        print("❌ write error:", e)
        return False


def safe_add(collection, data):
    global db

    if not db:
        return False

    try:
        db.collection(collection).add(data)
        return True
    except Exception as e:
        print("❌ add error:", e)
        return False


# =========================
# BOT STATS
# =========================
def save_bot_stats(stats):
    return safe_set("bot_stats", "latest", {
        **stats,
        "timestamp": time.time()
    })


def load_bot_stats():
    global db

    if not db:
        return None

    try:
        doc = db.collection("bot_stats").document("latest").get()
        return doc.to_dict() if doc.exists else None
    except:
        return None


# =========================
# SIGNALS
# =========================
def save_signal(signal):
    return safe_add("signals", {
        **signal,
        "timestamp": time.time()
    })


# =========================
# TRADES
# =========================
def save_trade(trade):
    return safe_add("trades", {
        **trade,
        "timestamp": time.time()
    })