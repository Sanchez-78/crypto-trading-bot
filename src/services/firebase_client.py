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
        db = None


def get_db():
    global db

    if db is None:
        init_firebase()

    return db


# -------------------------------
# USERS
# -------------------------------

def create_or_update_user(user_id, data: dict):
    try:
        db = get_db()
        if not db:
            return

        db.collection("users").document(user_id).set(data, merge=True)

    except Exception as e:
        print("❌ User save error:", e)


def get_user(user_id):
    try:
        db = get_db()
        if not db:
            return None

        doc = db.collection("users").document(user_id).get()

        return doc.to_dict() if doc.exists else None

    except Exception as e:
        print("❌ Get user error:", e)
        return None


def get_user_plan(user_id):
    user = get_user(user_id)
    return user.get("plan", "FREE") if user else "FREE"


def update_user_plan(user_id, plan, status="active"):
    create_or_update_user(user_id, {
        "plan": plan,
        "subscription_status": status
    })


def set_stripe_customer(user_id, customer_id):
    create_or_update_user(user_id, {
        "stripe_customer_id": customer_id
    })


def find_user_by_customer(customer_id):
    try:
        db = get_db()
        if not db:
            return None

        docs = db.collection("users") \
            .where("stripe_customer_id", "==", customer_id) \
            .limit(1).stream()

        for d in docs:
            return d.id, d.to_dict()

        return None

    except Exception as e:
        print("❌ Find user error:", e)
        return None


# -------------------------------
# SIGNALS
# -------------------------------

def save_signal(signal: dict):
    try:
        db = get_db()
        if not db:
            return

        db.collection("signals").add(signal)

    except Exception as e:
        print("❌ Save signal error:", e)


def load_all_signals(limit=500):
    try:
        db = get_db()
        if not db:
            return []

        docs = db.collection("signals").limit(limit).stream()
        return [d.to_dict() for d in docs]

    except Exception as e:
        print("❌ Load signals error:", e)
        return []


def load_open_signals():
    try:
        db = get_db()
        if not db:
            return []

        docs = db.collection("signals") \
            .where("evaluated", "==", False) \
            .stream()

        return [(d.id, d.to_dict()) for d in docs]

    except Exception as e:
        print("❌ Load open signals error:", e)
        return []


def update_signal(doc_id, data: dict):
    try:
        db = get_db()
        if not db:
            return

        db.collection("signals").document(doc_id).update(data)

    except Exception as e:
        print("❌ Update signal error:", e)


# -------------------------------
# PERFORMANCE (HIGH IMPACT)
# -------------------------------

def get_performance():
    try:
        db = get_db()
        if not db:
            return {}

        docs = db.collection("signals").stream()
        signals = [d.to_dict() for d in docs]

        wins = [s for s in signals if s.get("result") == "WIN"]
        losses = [s for s in signals if s.get("result") == "LOSS"]

        total = len(wins) + len(losses)
        winrate = len(wins) / total if total > 0 else 0

        return {
            "winrate": round(winrate, 3),
            "total_trades": total
        }

    except Exception as e:
        print("❌ Performance error:", e)
        return {}


# -------------------------------
# META (AI WEIGHTS)
# -------------------------------

def save_weights(weights: dict):
    try:
        db = get_db()
        if not db:
            return

        clean = {k: float(v) for k, v in weights.items() if v is not None}

        db.collection("meta").document("weights").set(clean)

    except Exception as e:
        print("❌ Save weights error:", e)


def load_weights():
    try:
        db = get_db()
        if not db:
            return {}

        doc = db.collection("meta").document("weights").get()

        if doc.exists:
            data = doc.to_dict()
            return data if isinstance(data, dict) else {}

        return {}

    except Exception as e:
        print("❌ Load weights error:", e)
        return {}