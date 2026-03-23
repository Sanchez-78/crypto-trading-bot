import firebase_admin
from firebase_admin import credentials, firestore
import os, json

db = None

def init():
    global db

    try:
        if not firebase_admin._apps:

            if os.environ.get("FIREBASE_CREDENTIALS"):
                cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS"]))
                firebase_admin.initialize_app(cred)
                print("🔥 Firebase ENV")

            elif os.path.exists("firebase_key.json"):
                cred = credentials.Certificate("firebase_key.json")
                firebase_admin.initialize_app(cred)
                print("🔥 Firebase FILE")

            else:
                print("❌ NO FIREBASE CREDS")
                return None

        db = firestore.client()
        return db

    except Exception as e:
        print(e)

db = init()


def save_metrics(metrics):
    if not db:
        print("❌ NO DB")
        return

    db.collection("metrics").document("latest").set(metrics)
    print("🔥 FIREBASE WRITE")