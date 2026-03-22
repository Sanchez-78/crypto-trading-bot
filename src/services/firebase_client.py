import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# =========================
# 🔑 INIT FIREBASE (ENV)
# =========================

if not firebase_admin._apps:
    firebase_json = os.environ.get("FIREBASE_KEY")

    if not firebase_json:
        raise ValueError("❌ FIREBASE_KEY not set in environment")

    cred = credentials.Certificate(json.loads(firebase_json))
    firebase_admin.initialize_app(cred)

db = firestore.client()


# =========================
# 📥 LOAD RECENT TRADES
# =========================
def load_recent_trades(limit=50):
    docs = db.collection("trades") \
        .order_by("timestamp", direction=firestore.Query.DESCENDING) \
        .limit(limit) \
        .stream()

    return [d.to_dict() for d in docs]


# =========================
# 📥 LOAD ALL SIGNALS
# =========================
def load_all_signals(limit=200):
    docs = db.collection("trades") \
        .order_by("timestamp", direction=firestore.Query.DESCENDING) \
        .limit(limit) \
        .stream()

    signals = []

    for d in docs:
        data = d.to_dict()

        strategy = data.get("strategy")
        result = data.get("result")

        if not strategy or result not in ["WIN", "LOSS"]:
            continue

        signals.append({
            "strategy": strategy,
            "result": result
        })

    return signals


# =========================
# 💾 SAVE TRADE (OPTIMIZED)
# =========================
def save_trade(trade):
    # ❗ neukládej všechny (šetření limitu)
    import random
    if random.random() > 0.3:
        return

    db.collection("trades").add(trade)


# =========================
# 💾 SAVE CONFIG
# =========================
def save_config(config):
    db.collection("config").document("latest").set(config)


# =========================
# 📥 LOAD CONFIG (CACHE)
# =========================
_last_config = None
_last_load_time = 0


def load_config():
    global _last_config, _last_load_time

    import time

    if time.time() - _last_load_time < 60:
        return _last_config or {}

    doc = db.collection("config").document("latest").get()

    _last_config = doc.to_dict() if doc.exists else {}
    _last_load_time = time.time()

    return _last_config


# =========================
# 📊 SAVE METRICS
# =========================
def save_metrics(metrics):
    db.collection("metrics").add(metrics)


# =========================
# 🧊 SAVE TRADE BATCH (komprese)
# =========================
def save_trade_batch(batch):
    db.collection("trade_batches").add(batch)