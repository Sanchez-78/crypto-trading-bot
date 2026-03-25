import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
import base64

db = None


def init_firebase():
    global db

    if firebase_admin._apps:
        return firestore.client()

    try:
        print("🔥 INIT FIREBASE CALLED")

        # =========================
        # 🔐 ONLY ENV (žádný file fallback)
        # =========================
        firebase_base64 = os.getenv("FIREBASE_KEY_BASE64")
        firebase_json = os.getenv("FIREBASE_CREDENTIALS")

        if firebase_base64:
            print("🔐 Using BASE64 ENV")

            decoded = base64.b64decode(firebase_base64)
            cred_dict = json.loads(decoded)
            cred = credentials.Certificate(cred_dict)

        elif firebase_json:
            print("🔐 Using JSON ENV")

            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)

        else:
            print("⚠️ No Firebase ENV → running WITHOUT DB")
            return None  # ❗ NEPADÁME

        firebase_admin.initialize_app(cred)

        db = firestore.client()
        print("🔥 Firebase initialized OK")

        return db

    except Exception as e:
        print("❌ Firebase init error:", e)
        return None  # ❗ NEPADÁME


# =========================
# SAFE ACCESS
# =========================
def get_db():
    return db