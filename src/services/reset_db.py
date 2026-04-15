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


def count_collection(col_name: str) -> int:
    db = get_db()
    col_ref = db.collection(_col(col_name))
    total = 0
    for _ in col_ref.select([]).stream():
        total += 1
    return total


def count_total_records(collections=None) -> tuple[int, dict]:
    if collections is None:
        collections = COLLECTIONS

    per_collection = {}
    total = 0

    print("📊 COUNTING RECORDS...\n")
    for col_name in collections:
        try:
            cnt = count_collection(col_name)
            per_collection[col_name] = cnt
            total += cnt
            print(f"  {col_name}: {cnt}")
        except Exception as e:
            per_collection[col_name] = -1
            print(f"  {col_name}: ERROR ({e})")

    print(f"\n  TOTAL: {total}\n")
    return total, per_collection


def print_count_summary(title: str, total: int, per_collection: dict):
    print("=" * 72)
    print(title)
    print("=" * 72)
    for col_name, value in per_collection.items():
        if value >= 0:
            print(f"  {col_name:<22} {value}")
        else:
            print(f"  {col_name:<22} ERROR")
    print("-" * 72)
    print(f"  {'TOTAL':<22} {total}")
    print("=" * 72)
    print()


def delete_batch(col_ref):
    docs = list(col_ref.limit(BATCH_SIZE).stream())
    deleted = 0
    for doc in docs:
        doc.reference.delete()
        deleted += 1
    return deleted


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
    return total_deleted


def safe_clear_redis():
    try:
        from src.services.state_manager import clear_redis_state
        clear_redis_state()
        print("  redis: cleared")
    except Exception as e:
        print(f"  redis error: {e}")


def smart_reset():
    print("🧠 SMART RESET START\n")
    actually_deleted = 0

    db = get_db()

    # --- keep last N trades ---
    KEEP_LAST = 200
    trades_ref = db.collection(_col("trades"))

    docs = list(
        trades_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
    )

    deleted_trades = 0
    for doc in docs[KEEP_LAST:]:
        doc.reference.delete()
        deleted_trades += 1

    actually_deleted += deleted_trades
    print(f"  trades: kept {min(KEEP_LAST, len(docs))}, deleted {deleted_trades}")

    # --- clear signals ---
    actually_deleted += wipe_collection("signals")
    actually_deleted += wipe_collection("signals_compressed")

    # --- clean metrics (preserve long-term) ---
    metrics_ref = db.collection(_col("metrics")).document("global")
    try:
        m = metrics_ref.get().to_dict() or {}
        preserved = {
            "equity_peak": m.get("equity_peak", 0),
            "total_trades": m.get("total_trades", 0),
        }
        metrics_ref.set(preserved)
        print("  metrics: cleaned (preserved long-term totals)")
    except Exception as e:
        print(f"  metrics error: {e}")

    # --- clear portfolio ---
    actually_deleted += wipe_collection("portfolio")

    safe_clear_redis()

    print("\n✅ SMART RESET COMPLETE")
    return actually_deleted


def learning_reset():
    print("🧪 LEARNING RESET START\n")
    actually_deleted = 0

    # Keep raw trade history, reset learning/runtime layers
    actually_deleted += wipe_collection("signals")
    actually_deleted += wipe_collection("signals_compressed")
    actually_deleted += wipe_collection("portfolio")
    actually_deleted += wipe_collection("model_state")
    actually_deleted += wipe_collection("weights")
    actually_deleted += wipe_collection("advice")
    actually_deleted += wipe_collection("meta")

    # --- clean metrics (preserve only long-term counters) ---
    db = get_db()
    metrics_ref = db.collection(_col("metrics")).document("global")
    try:
        m = metrics_ref.get().to_dict() or {}
        preserved = {
            "equity_peak": m.get("equity_peak", 0),
            "total_trades": m.get("total_trades", 0),
        }
        metrics_ref.set(preserved)
        print("  metrics: learning/runtime fields reset, long-term counters preserved")
    except Exception as e:
        print(f"  metrics error: {e}")

    safe_clear_redis()

    print("\n✅ LEARNING RESET COMPLETE")
    return actually_deleted


def reset_firestore():
    print("🔥 FULL RESET START\n")
    actually_deleted = 0

    for collection in COLLECTIONS:
        if collection in PRESERVE:
            print(f"⏭ Skipping: {collection}")
            continue
        try:
            actually_deleted += wipe_collection(collection)
        except Exception as e:
            print(f"❌ ERROR in {collection}: {e}")

    safe_clear_redis()

    print("✅ FULL RESET COMPLETE")
    return actually_deleted


def debug_reset():
    print("🛠 DEBUG RESET START\n")
    actually_deleted = 0

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

    actually_deleted += wipe_collection("signals")
    actually_deleted += wipe_collection("signals_compressed")
    actually_deleted += wipe_collection("portfolio")

    safe_clear_redis()

    print("\n✅ DEBUG RESET COMPLETE")
    return actually_deleted


def get_mode_collections(mode: str) -> list[str]:
    if mode == "full":
        return COLLECTIONS
    if mode == "smart":
        return [
            "trades",
            "signals",
            "signals_compressed",
            "metrics",
            "portfolio",
        ]
    if mode == "debug":
        return [
            "metrics",
            "signals",
            "signals_compressed",
            "portfolio",
        ]
    if mode == "learning":
        return [
            "model_state",
            "weights",
            "metrics",
            "signals",
            "signals_compressed",
            "portfolio",
            "meta",
            "advice",
        ]
    return COLLECTIONS


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["full", "smart", "debug", "learning"],
        default="full",
    )
    args = parser.parse_args()

    init_firebase()

    tracked_collections = get_mode_collections(args.mode)

    before_total, before_per_collection = count_total_records(tracked_collections)
    print_count_summary("BEFORE RESET", before_total, before_per_collection)

    actually_deleted = 0

    if args.mode == "full":
        actually_deleted = reset_firestore()
    elif args.mode == "smart":
        actually_deleted = smart_reset()
    elif args.mode == "debug":
        actually_deleted = debug_reset()
    elif args.mode == "learning":
        actually_deleted = learning_reset()

    after_total, after_per_collection = count_total_records(tracked_collections)
    print_count_summary("AFTER RESET", after_total, after_per_collection)

    net_change = before_total - after_total
    created_during_reset = max(0, after_total - (before_total - actually_deleted))

    print("=" * 72)
    print("FINAL RESET SUMMARY")
    print("=" * 72)
    print(f"  Mode                   : {args.mode}")
    print(f"  Records before         : {before_total}")
    print(f"  Records after          : {after_total}")
    print(f"  Documents deleted      : {actually_deleted}")
    print(f"  Net record change      : {net_change}")
    print(f"  New records created    : {created_during_reset}")
    print("=" * 72)