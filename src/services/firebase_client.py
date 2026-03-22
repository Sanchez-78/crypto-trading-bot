import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# INIT
if not firebase_admin._apps:
    firebase_json = os.environ.get("FIREBASE_KEY")

    if not firebase_json:
        raise ValueError("FIREBASE_KEY missing")

    cred = credentials.Certificate(json.loads(firebase_json))
    firebase_admin.initialize_app(cred)

db = firestore.client()


def save_trade(trade):
    import random
    if random.random() > 0.3:
        return

    db.collection("trades").add(trade)


def load_recent_trades(limit=50):
    docs = db.collection("trades") \
        .order_by("timestamp", direction=firestore.Query.DESCENDING) \
        .limit(limit) \
        .stream()

    return [d.to_dict() for d in docs]


def save_config(config):
    db.collection("config").document("latest").set(config)


_last_config = None
_last_load = 0


def load_config():
    global _last_config, _last_load
    import time

    if time.time() - _last_load < 60:
        return _last_config or {}

    doc = db.collection("config").document("latest").get()

    _last_config = doc.to_dict() if doc.exists else {}
    _last_load = time.time()

    return _last_config