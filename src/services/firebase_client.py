import os
import json
import time
import base64
import firebase_admin
from firebase_admin import credentials, firestore

db = None
_last_write = 0

# 🔥 nastav později na 30 (limit writes)
WRITE_INTERVAL = 0


# =========================
# INIT FIREBASE
# =========================
def init_firebase():
    global db

    print("🔥 INIT FIREBASE CALLED")

    try:
        # už inicializováno
        if firebase_admin._apps:
            db = firestore.client()
            print("🔥 Firebase already initialized")
            return db

        # =========================
        # 1️⃣ BASE64 (NEJLEPŠÍ VARIANTA)
        # =========================
        firebase_b64 = os.getenv("FIREBASE_KEY_BASE64")

        if firebase_b64:
            print("🔑 Using BASE64 key")

            try:
                decoded = base64.b64decode(firebase_b64).decode("utf-8")
                cred_dict = json.loads(decoded)

            except Exception as e:
                print("❌ BASE64 decode error:", e)
                return None

        else:
            # =========================
            # 2️⃣ RAW JSON (fallback)
            # =========================
            firebase_json = os.getenv("FIREBASE_KEY")

            if not firebase_json:
                print("❌ FIREBASE_KEY missing")
                return None

            try:
                # pokus 1
                cred_dict = json.loads(firebase_json)

            except Exception:
                try:
                    # pokus 2 (fix newline)
                    firebase_json_fixed = firebase_json.replace('\\n', '\n')
                    cred_dict = json.loads(firebase_json_fixed)

                except Exception as e:
                    print("❌ JSON parse failed:", e)
                    print("📛 KEY PREVIEW:", firebase_json[:120])
                    return None

        # =========================
        # INIT APP
        # =========================
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)

        db = firestore.client()

        print("🔥 Firebase initialized OK")
        print("🔥 DB OBJECT:", db)

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

    print(f"☁️ TRY WRITE → {collection}/{doc}")

    if not db:
        print("⚠️ DB not ready — skip write")
        return False

    now = time.time()

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
# SAVE BOT STATS
# =========================
def save_bot_stats(stats):
    print("☁️ SAVE BOT STATS:", stats)

    return safe_set(
        "bot_stats",
        "latest",
        {
            **stats,
            "timestamp": time.time()
        }
    )