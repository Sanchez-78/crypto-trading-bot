import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

db = None


# =========================
# INIT FIREBASE (FULL DEBUG)
# =========================
def init_firebase():
    global db

    print("\n🔥 INIT FIREBASE START")

    try:
        if not firebase_admin._apps:

            # =========================
            # ENV VAR
            # =========================
            firebase_env = os.environ.get("FIREBASE_CREDENTIALS")

            if firebase_env:
                print("🔍 Using FIREBASE_CREDENTIALS ENV")

                try:
                    cred_dict = json.loads(firebase_env)
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred)
                    print("✅ Firebase initialized from ENV")

                except Exception as e:
                    print(f"❌ ENV JSON ERROR: {e}")
                    return None

            # =========================
            # FILE
            # =========================
            elif os.path.exists("firebase_key.json"):
                print("🔍 Using firebase_key.json file")

                try:
                    cred = credentials.Certificate("firebase_key.json")
                    firebase_admin.initialize_app(cred)
                    print("✅ Firebase initialized from FILE")

                except Exception as e:
                    print(f"❌ FILE ERROR: {e}")
                    return None

            else:
                print("❌ NO FIREBASE CREDENTIALS FOUND")
                return None

        db = firestore.client()
        print("🔥 Firestore client READY")

        # =========================
        # TEST WRITE
        # =========================
        try:
            db.collection("debug").add({"test": "ok"})
            print("🔥 TEST WRITE SUCCESS")
        except Exception as e:
            print(f"❌ TEST WRITE FAILED: {e}")

        return db

    except Exception as e:
        print(f"❌ INIT FAILED: {e}")
        return None


db = init_firebase()


# =========================
# SAFE WRITE
# =========================
def save_metrics(metrics):
    print("📡 TRY SAVE METRICS")

    if not db:
        print("❌ DB NOT READY")
        return

    try:
        db.collection("metrics").document("latest").set(metrics)
        print("🔥 FIREBASE WRITE OK")

    except Exception as e:
        print(f"❌ FIREBASE WRITE ERROR: {e}")