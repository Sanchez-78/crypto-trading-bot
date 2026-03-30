import sys
import os

# 🔥 FIX: přidání root projektu do Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.services.firebase_client import get_db, col as _col

# All collections that hold state (trade history, model, weights, metrics)
# Order matters: wipe trades first so bootstrap on next start is clean.
COLLECTIONS = [
    "trades",
    "trades_compressed",
    "model_state",
    "weights",
    "metrics",
    "signals",
    "signals_compressed",
    "portfolio",
    "meta",
]


def delete_collection(col_name, batch_size=100):
    db = get_db()
    col_ref = db.collection(_col(col_name))   # respects PREFIX env var

    total_deleted = 0

    while True:
        docs = list(col_ref.limit(batch_size).stream())
        deleted = 0

        for doc in docs:
            doc.reference.delete()
            deleted += 1

        total_deleted += deleted

        print(f"🗑️ {col_name}: deleted {deleted}")

        if deleted < batch_size:
            break

    print(f"✅ {col_name}: TOTAL DELETED {total_deleted}\n")


def reset_firestore():
    print("🔥 RESET FIREBASE START\n")

    for collection in COLLECTIONS:
        try:
            delete_collection(collection)
        except Exception as e:
            print(f"❌ ERROR in {collection}:", e)

    print("🚀 FIREBASE RESET COMPLETE")


if __name__ == "__main__":
    reset_firestore()