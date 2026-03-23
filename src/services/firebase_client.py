import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

db = None


def init_firebase():
    global db

    print("\n🔥 INIT FIREBASE START")

    try:
        if not firebase_admin._apps:
            firebase_env = os.environ.get("FIREBASE_CREDENTIALS")

            if firebase_env:
                print("🔍 Using ENV credentials")

                try:
                    cred_dict = json.loads(firebase_env)
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred)
                    print("✅ Firebase initialized")
                except Exception as e:
                    print(f"❌ JSON ERROR: {e}")
                    return None
            else:
                print("❌ NO FIREBASE_CREDENTIALS")
                return None

        db = firestore.client()
        print("🔥 Firestore READY")

        # test write
        db.collection("debug").add({"ping": "ok"})
        print("🔥 TEST WRITE OK")

        return db

    except Exception as e:
        print(f"❌ INIT ERROR: {e}")
        return None


db = init_firebase()


def save_metrics(metrics):
    print("📡 SAVE METRICS CALLED")

    if not db:
        print("❌ DB NOT READY")
        return

    try:
        print("📡 WRITING:", metrics)

        db.collection("metrics").document("latest").set(metrics)

        print("🔥 FIREBASE WRITE OK")

    except Exception as e:
        print(f"❌ WRITE ERROR: {e}")