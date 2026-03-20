import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

db = None


# -------------------------------
# INIT
# -------------------------------

def init_firebase():
    global db

    try:
        if firebase_admin._apps:
            db = firestore.client()
            print("🔥 Firebase already initialized")
            return

        firebase_key = os.getenv("FIREBASE_KEY")

        if not firebase_key:
            raise Exception("FIREBASE_KEY missing")

        cred_dict = json.loads(firebase_key)
        cred = credentials.Certificate(cred_dict)

        firebase_admin.initialize_app(cred)
        db = firestore.client()

        print("🔥 Firebase connected")

    except Exception as e:
        print("❌ Firebase init error:", e)
        raise


# -------------------------------
# SAFE DB ACCESS
# -------------------------------

def get_db():
    global db
    if db is None:
        init_firebase()
    return db


# -------------------------------
# SIGNALS
# -------------------------------

def save_signal(signal: dict):
    try:
        db = get_db()
        db.collection("signals").add(signal)
    except Exception as e:
        print("❌ Save signal error:", e)


def load_all_signals(limit=500):
    try:
        db = get_db()
        docs = db.collection("signals").limit(limit).stream()
        return [d.to_dict() for d in docs]
    except Exception as e:
        print("❌ Load signals error:", e)
        return []


def load_open_signals():
    try:
        db = get_db()
        docs = db.collection("signals").where("evaluated", "==", False).stream()
        return [(d.id, d.to_dict()) for d in docs]
    except Exception as e:
        print("❌ Load open signals error:", e)
        return []


def update_signal(doc_id, data: dict):
    try:
        db = get_db()
        db.collection("signals").document(doc_id).update(data)
    except Exception as e:
        print("❌ Update signal error:", e)


# -------------------------------
# WEIGHTS (AI / META)
# -------------------------------

def save_weights(weights: dict):
    try:
        db = get_db()
        db.collection("meta").document("weights").set(weights)
    except Exception as e:
        print("❌ Save weights error:", e)


def load_weights():
    try:
        db = get_db()
        doc = db.collection("meta").document("weights").get()
        return doc.to_dict() if doc.exists else {}
    except Exception as e:
        print("❌ Load weights error:", e)
        return {}