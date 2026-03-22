import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)

db = firestore.client()


# =========================
# 📥 LOAD RECENT TRADES
# =========================
def load_recent_trades(limit=100):
    docs = db.collection("trades") \
        .order_by("timestamp", direction=firestore.Query.DESCENDING) \
        .limit(limit) \
        .stream()

    return [d.to_dict() for d in docs]


# =========================
# 📥 LOAD ALL SIGNALS (FIX)
# =========================
def load_all_signals(limit=500):
    docs = db.collection("trades") \
        .order_by("timestamp", direction=firestore.Query.DESCENDING) \
        .limit(limit) \
        .stream()

    signals = []

    for d in docs:
        data = d.to_dict()

        signals.append({
            "strategy": data.get("strategy"),
            "result": data.get("result")  # WIN / LOSS
        })

    return signals


# =========================
# 💾 SAVE TRADE
# =========================
def save_trade(trade):
    db.collection("trades").add(trade)


# =========================
# 💾 SAVE CONFIG
# =========================
def save_config(config):
    db.collection("config").document("latest").set(config)


# =========================
# 📥 LOAD CONFIG
# =========================
def load_config():
    doc = db.collection("config").document("latest").get()
    return doc.to_dict() if doc.exists else {}


# =========================
# 📊 SAVE METRICS
# =========================
def save_metrics(metrics):
    db.collection("metrics").add(metrics)


# =========================
# 🧊 SAVE BATCH
# =========================
def save_trade_batch(batch):
    db.collection("trade_batches").add(batch)