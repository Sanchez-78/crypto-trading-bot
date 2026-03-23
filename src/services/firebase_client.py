import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

db = None


def init_firebase():
    global db

    try:
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