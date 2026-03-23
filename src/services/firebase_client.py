import os
import json
import time
import firebase_admin
from firebase_admin import credentials, firestore

db = None

# 🔥 WRITE CONTROL (globální)
_last_write = 0
WRITE_INTERVAL = 30  # sekund


# =========================
# INIT FIREBASE
# =========================
def init_firebase():
    global db

    try:
        # už inicializováno
        if firebase_admin._apps:
            db = firestore.client()
            print("🔥 Firebase already initialized")
            return db

        firebase_json = os.getenv("FIREBASE_KEY")

        if not firebase_json:
            print("❌ FIREBASE_KEY missing")
            return None

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
# SAFE WRITE (GENERIC)
# =========================
def safe_set(collection, doc, data):
    global db, _last_write

    if not db:
        print("⚠️ DB not ready — skip write")
        return False

    now = time.time()

    # 🔥 RATE LIMIT
    if now - _last_write < WRITE_INTERVAL:
        print("⏳ Skip write (rate limit)")
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
# BOT STATS (hlavní použití)
# =========================
def save_bot_stats(stats):
    return safe_set(
        "bot_stats",
        "latest",
        {
            **stats,
            "timestamp": time.time()
        }
    )


# =========================
# DEBUG LOG (volitelné)
# =========================
def log_event(name, payload):
    global db

    if not db:
        return

    try:
        db.collection("logs").add({
            "event": name,
            "data": payload,
            "timestamp": time.time()
        })
    except:
        pass  # žádný crash


# =========================
# OPTIONAL (NEPOUŽÍVAT často!)
# =========================
def save_signal(signal):
    global db

    if not db:
        return

    try:
        db.collection("signals").add(signal)
    except:
        pass