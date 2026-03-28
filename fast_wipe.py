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
from firebase_admin import firestore

def execute_fast_wipe():
    db = get_db()
    
    # 1. Delete Auditor state & Model state
    print("Deleting 'metrics/auditor'...")
    db.document("metrics/auditor").delete()
    
    print("Deleting 'metrics/latest'...")
    db.document("metrics/latest").delete()
    
    print("Deleting 'model_state/latest'...")
    db.document("model_state/latest").delete()
    
    print("Deleting 'weights/model'...")
    db.document("weights/model").delete()

    # 2. Delete the NEWEST 200 trades (which cause the streak)
    print("Flushing ALL 'trades' in chunks of 500...")
    trades_ref = db.collection("trades")
    
    total_deleted = 0
    while True:
        docs = list(trades_ref.limit(500).stream())
        if not docs:
            break
            
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
            total_deleted += 1
            
        batch.commit()
        print(f"Flushed {total_deleted} trades so far...")
        
    print(f"✅ Fast wipe complete. {total_deleted} trades eliminated completely. Metrics reset.")

if __name__ == "__main__":
    init_firebase()
    execute_fast_wipe()
