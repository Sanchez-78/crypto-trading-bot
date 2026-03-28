import os
import base64
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if not os.getenv("FIREBASE_KEY_BASE64") and os.path.exists("firebase_key.json"):
    with open("firebase_key.json", "rb") as f:
        os.environ["FIREBASE_KEY_BASE64"] = base64.b64encode(f.read()).decode("utf-8")

from src.services.firebase_client import get_db, init_firebase

COLLECTIONS = [
    "trades",
    "signals",
    "signals_compressed",
    "trades_compressed",
    "meta",
    "metrics",
    "weights",
    "model_state",
    "portfolio"
]

def delete_collection(col_name, batch_size=100):
    db = get_db()
    if not db:
        print("Firebase disabled or not initialized!")
        return
        
    col_ref = db.collection(col_name)

    while True:
        docs = list(col_ref.limit(batch_size).stream())
        deleted = 0

        for doc in docs:
            doc.reference.delete()
            deleted += 1

        print(f"{col_name}: deleted {deleted}")

        if deleted < batch_size:
            break

if __name__ == "__main__":
    print("🔥 RESET FIREBASE START")
    init_firebase()
    
    for c in COLLECTIONS:
        delete_collection(c)

    print("✅ FIREBASE CLEARED")