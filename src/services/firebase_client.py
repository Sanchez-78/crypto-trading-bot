import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

db = None

def init_firebase():
    global db

    try:
        if not firebase_admin._apps:

            # 🔥 ENV (Railway)
            firebase_json = os.environ.get("FIREBASE_CREDENTIALS")

            if firebase_json:
                cred_dict = json.loads(firebase_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                print("🔥 Firebase initialized (ENV)")

            # 🔥 LOCAL FILE
            elif os.path.exists("firebase_key.json"):
                cred = credentials.Certificate("firebase_key.json")
                firebase_admin.initialize_app(cred)
                print("🔥 Firebase initialized (FILE)")

            else:
                print("❌ Firebase credentials NOT FOUND")
                return None

        db = firestore.client()
        print("🔥 Firestore client ready")

        return db

    except Exception as e:
        print(f"❌ Firebase init error: {e}")
        return None


db = init_firebase()


# =========================
# WRITE FUNCTIONS
# =========================

def save_metrics(metrics):
    try:
        if not db:
            print("❌ Firebase NOT READY → metrics skipped")
            return

        db.collection("metrics").document("latest").set(metrics)

        print("🔥 FIREBASE WRITE: metrics/latest")

    except Exception as e:
        print(f"❌ Firebase write error: {e}")


def save_trade(trade):
    try:
        if not db:
            print("❌ Firebase NOT READY → trade skipped")
            return

        db.collection("trades").add(trade)

        print("🔥 FIREBASE WRITE: trade")

    except Exception as e:
        print(f"❌ Firebase trade error: {e}")