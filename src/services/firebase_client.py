import firebase_admin
from firebase_admin import credentials, firestore
import os, json, base64, time

db = None

CACHE = {
    "history": [],
    "last_fetch": 0
}

def init_firebase():
    global db

    if firebase_admin._apps:
        db = firestore.client()
        return db

    key = os.getenv("FIREBASE_KEY_BASE64")
    if not key:
        print("⚠️ Firebase disabled")
        return None

    decoded = base64.b64decode(key)
    cred = credentials.Certificate(json.loads(decoded))

    firebase_admin.initialize_app(cred)
    db = firestore.client()

    print("🔥 Firebase connected")
    return db


def load_history(limit=200):
    global CACHE, db

    if db is None:
        return []

    if time.time() - CACHE["last_fetch"] < 60:
        return CACHE["history"]

    try:
        docs = (
            db.collection("trades")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )

        CACHE["history"] = [d.to_dict() for d in docs]
        CACHE["last_fetch"] = time.time()

        print(f"📥 Loaded {len(CACHE['history'])} trades")

    except Exception as e:
        print("❌ load_history:", e)

    return CACHE["history"]


def save_batch(batch):
    if db is None:
        return

    try:
        for item in batch:
            db.collection("trades").add(item)
        print(f"💾 Saved {len(batch)} trades")
    except Exception as e:
        print("❌ save_batch:", e)