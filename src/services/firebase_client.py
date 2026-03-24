import os
import json
import time
import firebase_admin
from firebase_admin import credentials, firestore

db = None
_last_write = 0
WRITE_INTERVAL = 0  # debug


# =========================
# INIT FIREBASE
# =========================
def init_firebase():
    global db

    print("🔥 INIT FIREBASE CALLED")

    try:
        if firebase_admin._apps:
            db = firestore.client()
            print("🔥 Firebase already initialized")
            return db

        firebase_json = os.getenv("FIREBASE_KEY")

        if not firebase_json:
            print("❌ FIREBASE_KEY missing")
            return None

        firebase_json = firebase_json.replace('\\n', '\n')
        cred_dict = json.loads(firebase_json)

        cred = credentials.Certificate(cred_dict)
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
def safe_set(collection, doc, data):
    global db, _last_write

    if not db:
        print("⚠️ DB not ready")
        return False

    now = time.time()

    if now - _last_write < WRITE_INTERVAL:
        print("⏳ skip write")
        return False

    try:
        db.collection(collection).document(doc).set(data)
        _last_write = now

        print(f"☁️ WRITE OK → {collection}/{doc}")
        return True

    except Exception as e:
        print("❌ Firebase write error:", e)
        return False


# =========================
# SAVE BOT STATS
# =========================
def save_bot_stats(stats):
    print("☁️ SAVE BOT STATS")

    return safe_set(
        "bot_stats",
        "latest",
        {
            **stats,
            "timestamp": time.time()
        }
    )