import firebase_admin
from firebase_admin import credentials, firestore
import os, json, base64, time

db = None

# Cache TTL = 600s (10 min) to stay under 50k reads/day limit
# 100 docs × 144 fetches/day = 14,400 reads/day
CACHE = {
    "history": [],
    "last_fetch": 0
}
CACHE_TTL = 600
HISTORY_LIMIT = 100


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


def load_history(limit=HISTORY_LIMIT):
    global CACHE, db

    if db is None:
        return []

    if time.time() - CACHE["last_fetch"] < CACHE_TTL:
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

        print(f"📥 Loaded {len(CACHE['history'])} trades from Firebase")

    except Exception as e:
        print("❌ load_history:", e)

    return CACHE["history"]


def save_batch(batch):
    if db is None:
        return

    try:
        for item in batch:
            db.collection("trades").add(item)
        print(f"💾 Saved {len(batch)} trades to Firebase")
    except Exception as e:
        print("❌ save_batch:", e)
