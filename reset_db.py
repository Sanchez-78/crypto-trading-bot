"""
reset_db.py — one-shot Firebase clean slate.

Deletes:
  trades/*           - all trade history (poisoned by evaluator.py random profits)
  model_state/latest - calibrator buckets, ev_history, bayes/bandit stats
  metrics/last_trade - stale last-trade summary
  metrics/auditor    - auditor state trained on bad data
  signals/*          - signals trained on corrupted trades

Keeps:
  weights/model      - strategy weights (bot2, not corrupted)
  metrics/latest     - live dashboard (overwritten on next bot tick)
  config/*           - runtime config

Usage:
  python reset_db.py
"""

import sys
from src.services.firebase_client import init_firebase, col

db = init_firebase()
if db is None:
    print("Firebase not connected - set FIREBASE_KEY_BASE64 env var")
    sys.exit(1)


def delete_collection(name, batch_size=400):
    col_ref = db.collection(name)
    total = 0
    while True:
        docs = list(col_ref.limit(batch_size).stream())
        if not docs:
            break
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        total += len(docs)
        print(f"  deleted {total} docs from '{name}' ...")
    return total


def delete_document(collection, doc_id):
    ref = db.collection(collection).document(doc_id)
    if ref.get().exists:
        ref.delete()
        print(f"  deleted {collection}/{doc_id}")
    else:
        print(f"  {collection}/{doc_id} not found - skipping")


print("\n Clearing trades ...")
print(f"  {delete_collection(col('trades'))} docs deleted")

print("\n Clearing signals ...")
print(f"  {delete_collection(col('signals'))} docs deleted")

print("\n Clearing model_state ...")
delete_document(col("model_state"), "latest")

print("\n Clearing stale metrics ...")
delete_document(col("metrics"), "last_trade")
delete_document(col("metrics"), "auditor")

print("\nDatabase reset complete.")
print("Keeping: weights/model, metrics/latest, config/*")
print("Restart the bot to begin clean bootstrap.\n")
