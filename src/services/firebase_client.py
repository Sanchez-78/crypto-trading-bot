import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

db = None


# ---------------- INIT ----------------

def init_firebase():
    global db

    try:
        if firebase_admin._apps:
            db = firestore.client()
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


# ---------------- SIGNALS ----------------

def save_signal(signal: dict):
    try:
        db = get_db()
        if not db:
            print("❌ No DB")
            return

        db.collection("signals").add(signal)
        print(f"✅ Saved: {signal['symbol']} {signal['signal']}")

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
            .where(filter=FieldFilter("evaluated", "==", False)) \
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


# ---------------- LEARNING ----------------

def load_recent_trades(limit=100):
    try:
        db = get_db()
        if not db:
            return []

        docs = db.collection("signals") \
            .where(filter=FieldFilter("evaluated", "==", True)) \
            .limit(limit) \
            .stream()

        return [d.to_dict() for d in docs]

    except Exception as e:
        print("❌ Load trades error:", e)
        return []


# ---------------- PERFORMANCE ----------------

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

        profits = [s.get("profit", 0) for s in signals if s.get("profit") is not None]
        avg_profit = sum(profits) / len(profits) if profits else 0

        return {
            "winrate": round(winrate, 3),
            "total_trades": total,
            "avg_profit": round(avg_profit, 5)
        }

    except Exception as e:
        print("❌ Performance error:", e)
        return {}


# ---------------- USERS ----------------

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
            .where(filter=FieldFilter("stripe_customer_id", "==", customer_id)) \
            .limit(1) \
            .stream()

        for d in docs:
            return d.id, d.to_dict()

        return None

    except Exception as e:
        print("❌ Find user error:", e)
        return None


# ---------------- META ----------------

def save_meta_state(data: dict):
    try:
        db = get_db()
        if not db:
            return

        db.collection("meta").document("state").set(data)

    except Exception as e:
        print("❌ Save meta error:", e)


def load_meta_state():
    try:
        db = get_db()
        if not db:
            return {}

        doc = db.collection("meta").document("state").get()
        return doc.to_dict() if doc.exists else {}

    except Exception as e:
        print("❌ Load meta error:", e)
        return {}


# ---------------- WEIGHTS ----------------

def load_weights() -> dict:
    try:
        db = get_db()
        if not db:
            return {}

        doc = db.collection("meta").document("weights").get()
        return doc.to_dict() if doc.exists else {}

    except Exception as e:
        print("❌ Load weights error:", e)
        return {}


def save_weights(weights: dict) -> None:
    try:
        db = get_db()
        if not db:
            return

        db.collection("meta").document("weights").set(weights)

    except Exception as e:
        print("❌ Save weights error:", e)


# ---------------- PENDING SIGNALS (pro evaluator) ----------------

def load_pending_signals() -> list[dict]:
    """Vrátí signály, které ještě nebyly vyhodnoceny."""
    try:
        db = get_db()
        if not db:
            return []

        docs = db.collection("signals") \
            .where(filter=FieldFilter("evaluated", "==", False)) \
            .stream()

        return [{"id": d.id, **d.to_dict()} for d in docs]

    except Exception as e:
        print("❌ Load pending signals error:", e)
        return []


def mark_signal_evaluated(doc_id: str, update: dict) -> None:
    """Označí signál jako vyhodnocený a uloží výsledek."""
    try:
        db = get_db()
        if not db:
            return

        db.collection("signals").document(doc_id).update({
            "evaluated":    True,
            "evaluated_at": __import__("datetime").datetime.utcnow().isoformat(),
            **update,
        })

    except Exception as e:
        print("❌ Mark evaluated error:", e)

def load_old_trades(limit=200):
    db = get_db()

    docs = (
        db.collection("signals")
        .where("evaluated", "==", True)
        .order_by("timestamp")
        .limit(limit)
        .stream()
    )

    trades = []
    for d in docs:
        data = d.to_dict()
        data["id"] = d.id
        trades.append(data)

    return trades


def delete_trade(doc_id):
    db = get_db()
    db.collection("signals").document(doc_id).delete()


def save_compressed(trade):
    db = get_db()
    db.collection("signals_compressed").add(trade)