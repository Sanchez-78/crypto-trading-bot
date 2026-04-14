import sys
import os
import base64
import time
import argparse

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

# Load firebase key from file if env var not set (local dev)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if not os.getenv("FIREBASE_KEY_BASE64") and os.path.exists("firebase_key.json"):
    with open("firebase_key.json", "rb") as _f:
        os.environ["FIREBASE_KEY_BASE64"] = base64.b64encode(_f.read()).decode("utf-8")

from firebase_admin import firestore
from src.services.firebase_client import init_firebase, get_db, col as _col

PRESERVE = set()

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
    "advice",
]

BATCH_SIZE = 400

def delete_batch(col_ref):
    docs = list(col_ref.limit(BATCH_SIZE).stream())
    deleted = 0
    for doc in docs:
        doc.reference.delete()
        deleted += 1
    return deleted

def smart_reset():
    print("🧠 SMART RESET START\n")

    db = get_db()

    # --- keep last N trades ---
    KEEP_LAST = 200
    trades_ref = db.collection(_col("trades"))

    docs = list(trades_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).stream())

    for doc in docs[KEEP_LAST:]:
        doc.reference.delete()

    print(f"  trades: kept {KEEP_LAST}, deleted {max(0, len(docs)-KEEP_LAST)}")

    # --- clear signals ---
    wipe_collection("signals")
    wipe_collection("signals_compressed")

    # --- clean metrics (preserve long-term) ---
    metrics_ref = db.collection(_col("metrics")).document("global")

    try:
        m = metrics_ref.get().to_dict() or {}

        preserved = {
            "equity_peak": m.get("equity_peak", 0),
            "total_trades": m.get("total_trades", 0),
        }

        metrics_ref.set(preserved)
        print("  metrics: cleaned")

    except Exception as e:
        print(f"  metrics error: {e}")

    # --- clear portfolio ---
    wipe_collection("portfolio")

    print("\n✅ SMART RESET COMPLETE")

def wipe_collection(col_name):
    db = get_db()
    col_ref = db.collection(_col(col_name))
    total_deleted = 0
    while True:
        deleted = delete_batch(col_ref)
        total_deleted += deleted
        print(f"  {col_name}: deleted {deleted}")
        if deleted == 0:
            break
        time.sleep(0.05)
    print(f"  {col_name}: TOTAL DELETED {total_deleted}\n")

def reset_firestore():
    print("🔥 FULL RESET START\n")
    for collection in COLLECTIONS:
        if collection in PRESERVE:
            print(f"⏭ Skipping: {collection}")
            continue
        try:
            wipe_collection(collection)
        except Exception as e:
            print(f"❌ ERROR in {collection}: {e}")
    print("✅ FULL RESET COMPLETE")

def debug_reset():
    print("🛠 DEBUG RESET START\n")
    db = get_db()
    metrics_ref = db.collection(_col("metrics")).document("global")
    try:
        m = metrics_ref.get().to_dict() or {}
        m["loss_streak"] = 0
        m["win_streak"] = 0
        m["last_trade_ts"] = 0
        metrics_ref.set(m)
        print("  metrics: streaks reset")
    except Exception as e:
        print(f"  metrics error: {e}")

    wipe_collection("signals")
    wipe_collection("signals_compressed")
    wipe_collection("portfolio")

    try:
        from src.services.state_manager import clear_redis_state
        clear_redis_state()
        print("  redis: cleared")
    except Exception as e:
        print(f"  redis error: {e}")

    print("\n✅ DEBUG RESET COMPLETE")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["full", "smart", "debug"], default="full")
    args = parser.parse_args()

    init_firebase()

    if args.mode == "full":
        reset_firestore()
    elif args.mode == "smart":
        smart_reset()
    elif args.mode == "debug":
        debug_reset()
