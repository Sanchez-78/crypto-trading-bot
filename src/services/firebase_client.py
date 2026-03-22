import firebase_admin
from firebase_admin import credentials, firestore
import os

_db = None


# =========================
# 🔌 INIT FIREBASE
# =========================
def init_firebase():
    global _db

    if _db is not None:
        return _db

    try:
        if not firebase_admin._apps:
            cred_path = os.getenv("FIREBASE_CREDENTIALS", "firebase_key.json")

            if not os.path.exists(cred_path):
                print("❌ Firebase credentials not found")
                return None

            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)

        _db = firestore.client()
        print("🔥 Firebase connected")

    except Exception as e:
        print(f"❌ Firebase init error: {e}")
        _db = None

    return _db


def get_db():
    if _db is None:
        return init_firebase()
    return _db


# =========================
# 📡 SIGNALS
# =========================
def save_signal(signal):
    db = get_db()
    if not db:
        return

    db.collection("signals").add(signal)


def update_signal(doc_id, data):
    db = get_db()
    if not db:
        return

    db.collection("signals").document(doc_id).update(data)


def load_signals(evaluated=None, limit=100):
    db = get_db()
    if not db:
        return []

    query = db.collection("signals")

    if evaluated is not None:
        query = query.where("evaluated", "==", evaluated)

    docs = query.limit(limit).stream()

    return [{**d.to_dict(), "id": d.id} for d in docs]


# =========================
# ⚙️ CONFIG
# =========================
def save_config(config):
    db = get_db()
    if not db:
        return

    db.collection("config").document("main").set(config)


def load_config():
    db = get_db()
    if not db:
        return {}

    doc = db.collection("config").document("main").get()

    if doc.exists:
        return doc.to_dict()

    return {}


# =========================
# 📊 METRICS
# =========================
def save_metrics(metrics):
    db = get_db()
    if not db:
        return

    db.collection("metrics").document("latest").set(metrics)


# =========================
# 💰 TRADES (OPTIONAL)
# =========================
def save_trade(trade):
    db = get_db()
    if not db:
        return

    db.collection("trades").add(trade)