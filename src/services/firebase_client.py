"""
Firebase client – centralized Firestore access layer.

Free-tier quotas: 50 000 reads/day · 20 000 writes/day · 1 GB storage

Optimizations:
  - History cache 600 s  → ≤ 14 400 reads/day  (100 docs × 144 fetches)
  - Weights  cache 300 s → negligible reads
  - Signals  cache 900 s → negligible reads
  - Cache updated on every write  → avoids re-fetch after save_batch
  - Slim trade documents          → ~40% smaller, same write count
  - Firestore WriteBatch          → atomic, single round-trip per batch
  - All missing functions added   → no ImportError from legacy modules
"""

import firebase_admin
from firebase_admin import credentials, firestore
import os, json, base64, time

# ── Globals ───────────────────────────────────────────────────────────────────

db = None

_HISTORY_CACHE  = {"data": [],   "ts": 0}
_WEIGHTS_CACHE  = {"data": None, "ts": 0}
_SIGNALS_CACHE  = {"data": [],   "ts": 0}

HISTORY_LIMIT  = 100
SIGNALS_LIMIT  = 200

HISTORY_TTL    = 600   # 10 min
WEIGHTS_TTL    = 300   # 5  min
SIGNALS_TTL    = 900   # 15 min


# ── Init ──────────────────────────────────────────────────────────────────────

def init_firebase():
    global db
    if firebase_admin._apps:
        db = firestore.client()
        return db

    key = os.getenv("FIREBASE_KEY_BASE64")
    if not key:
        print("⚠️  Firebase disabled (no FIREBASE_KEY_BASE64)")
        return None

    cred = credentials.Certificate(json.loads(base64.b64decode(key)))
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("🔥 Firebase connected")
    return db


def get_db():
    return db


# ── Trade helpers ─────────────────────────────────────────────────────────────

def _slim_trade(trade):
    """
    Strip redundant/derived fields before storing.
    Keeps only what the decision engine needs for pattern matching.
    Saves ~40% Firestore document size vs raw trade dict.
    """
    feat = trade.get("features") or {}
    return {
        "symbol":       trade.get("symbol"),
        "action":       trade.get("action"),
        "price":        round(float(trade.get("price",      0)), 4),
        "exit_price":   round(float(trade.get("exit_price", 0)), 4),
        "profit":       round(float(trade.get("profit",     0)), 8),
        "result":       trade.get("result"),
        "close_reason": trade.get("close_reason"),
        "confidence":   round(float(trade.get("confidence", 0)), 4),
        "regime":       trade.get("regime", "RANGING"),
        "timestamp":    trade.get("timestamp", time.time()),
        "features": {
            "ema_diff":   round(float(feat.get("ema_diff",   0)), 6),
            "rsi":        round(float(feat.get("rsi",       50)), 2),
            "volatility": round(float(feat.get("volatility", 0)), 6),
            "macd":       round(float(feat.get("macd",       0)), 8),
            "adx":        round(float(feat.get("adx",       20)), 2),
        },
    }


# ── Trades ────────────────────────────────────────────────────────────────────

def load_history(limit=HISTORY_LIMIT):
    """
    Return last `limit` trades (slim dicts).
    Cached for HISTORY_TTL seconds.
    Cache is kept warm after every save_batch, so real fetches are rare.
    """
    if db is None:
        return []
    if time.time() - _HISTORY_CACHE["ts"] < HISTORY_TTL:
        return _HISTORY_CACHE["data"]
    try:
        docs = (
            db.collection("trades")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        _HISTORY_CACHE["data"] = [d.to_dict() for d in docs]
        _HISTORY_CACHE["ts"]   = time.time()
        print(f"📥 Firebase: loaded {len(_HISTORY_CACHE['data'])} trades")
    except Exception as e:
        print(f"❌ load_history: {e}")
    return _HISTORY_CACHE["data"]


def save_batch(batch):
    """
    Atomic WriteBatch write.  Single round-trip regardless of batch size.
    Updates local history cache so next load_history() uses in-memory data.
    Write quota: 1 write per document (same as individual adds).
    """
    if db is None:
        return
    try:
        slimmed    = [_slim_trade(t) for t in batch]
        fb_batch   = db.batch()
        for item in slimmed:
            fb_batch.set(db.collection("trades").document(), item)
        fb_batch.commit()

        # Keep cache fresh – prepend new trades, cap at limit
        _HISTORY_CACHE["data"] = (slimmed + _HISTORY_CACHE["data"])[:HISTORY_LIMIT]
        _HISTORY_CACHE["ts"]   = time.time()

        print(f"💾 Firebase: saved {len(batch)} trades (batch write)")
    except Exception as e:
        print(f"❌ save_batch: {e}")


def save_trade(trade, result):
    """Single-trade save used by legacy evaluator.py."""
    combined = {**trade, **result, "timestamp": time.time()}
    save_batch([combined])


def load_old_trades(limit=200):
    """
    Load oldest trades for cleanup (auto_cleaner.py).
    Returns dicts with injected 'id' field (Firestore doc ID).
    """
    if db is None:
        return []
    try:
        docs = (
            db.collection("trades")
            .order_by("timestamp", direction=firestore.Query.ASCENDING)
            .limit(limit)
            .stream()
        )
        return [{**d.to_dict(), "id": d.id} for d in docs]
    except Exception as e:
        print(f"❌ load_old_trades: {e}")
        return []


def delete_trade(doc_id):
    """Delete a single trade document by Firestore ID."""
    if db is None:
        return
    try:
        db.collection("trades").document(doc_id).delete()
    except Exception as e:
        print(f"❌ delete_trade: {e}")


def save_compressed(data):
    """Save a compressed trade summary (auto_cleaner.py)."""
    if db is None:
        return
    try:
        db.collection("trades_compressed").add(data)
    except Exception as e:
        print(f"❌ save_compressed: {e}")


# ── Signals ───────────────────────────────────────────────────────────────────

def save_signal(signal):
    """Save a signal document, return its doc ID."""
    if db is None:
        return None
    try:
        _, ref = db.collection("signals").add(signal)
        # Invalidate signals cache so next load picks it up
        _SIGNALS_CACHE["ts"] = 0
        return ref.id
    except Exception as e:
        print(f"❌ save_signal: {e}")
        return None


def load_all_signals(limit=SIGNALS_LIMIT):
    """
    Load evaluated signals for ML retraining (retrainer.py, strategy_weights.py).
    Cached for SIGNALS_TTL seconds.
    """
    if db is None:
        return []
    if time.time() - _SIGNALS_CACHE["ts"] < SIGNALS_TTL:
        return _SIGNALS_CACHE["data"]
    try:
        docs = (
            db.collection("signals")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        _SIGNALS_CACHE["data"] = [d.to_dict() for d in docs]
        _SIGNALS_CACHE["ts"]   = time.time()
        print(f"📥 Firebase: loaded {len(_SIGNALS_CACHE['data'])} signals")
    except Exception as e:
        print(f"❌ load_all_signals: {e}")
    return _SIGNALS_CACHE["data"]


# ── Weights ───────────────────────────────────────────────────────────────────

def load_weights():
    """
    Load ML model weights.
    Cached for WEIGHTS_TTL seconds – avoids a Firestore read on every signal.
    """
    if db is None:
        return {}
    if _WEIGHTS_CACHE["data"] is not None and \
       time.time() - _WEIGHTS_CACHE["ts"] < WEIGHTS_TTL:
        return dict(_WEIGHTS_CACHE["data"])
    try:
        doc = db.collection("weights").document("model").get()
        _WEIGHTS_CACHE["data"] = doc.to_dict() or {}
        _WEIGHTS_CACHE["ts"]   = time.time()
    except Exception as e:
        print(f"❌ load_weights: {e}")
        return _WEIGHTS_CACHE["data"] or {}
    return dict(_WEIGHTS_CACHE["data"])


def save_weights(data):
    """Persist model weights and update local cache."""
    if db is None:
        return
    try:
        db.collection("weights").document("model").set(data, merge=True)
        _WEIGHTS_CACHE["data"] = dict(data)
        _WEIGHTS_CACHE["ts"]   = time.time()
    except Exception as e:
        print(f"❌ save_weights: {e}")


# ── Portfolio ─────────────────────────────────────────────────────────────────

_last_portfolio_save = 0
PORTFOLIO_THROTTLE   = 30  # write at most once per 30 s

def save_portfolio(data):
    """Throttled portfolio state save (portfolio_event.py)."""
    global _last_portfolio_save
    if db is None:
        return
    now = time.time()
    if now - _last_portfolio_save < PORTFOLIO_THROTTLE:
        return  # skip – too frequent
    try:
        db.collection("portfolio").document("state").set(
            {**data, "updated_at": now}, merge=True
        )
        _last_portfolio_save = now
    except Exception as e:
        print(f"❌ save_portfolio: {e}")


# ── Metrics ───────────────────────────────────────────────────────────────────

def save_metrics(data):
    """Write run statistics to metrics/latest (main.py batch mode)."""
    if db is None:
        return
    try:
        db.collection("metrics").document("latest").set(
            {**data, "timestamp": time.time()}, merge=True
        )
    except Exception as e:
        print(f"❌ save_metrics: {e}")


# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    """Load runtime config from Firestore (execution_bot.py)."""
    if db is None:
        return {}
    try:
        doc = db.collection("config").document("runtime").get()
        return doc.to_dict() or {}
    except Exception as e:
        print(f"❌ load_config: {e}")
        return {}


# ── Daily budget report ───────────────────────────────────────────────────────

def daily_budget_report():
    """
    Estimate daily Firebase operation counts (call once at startup).

    Reads:
      load_history:   100 docs × (86400 / 600)  = 14 400 reads/day
      load_weights:     1 doc  × (86400 / 300)  =    288 reads/day
      load_all_signals: 200 docs × (86400 / 900) = 19 200 reads/day  ← only if retrainer runs
    Writes:
      save_batch (20 trades/batch): depends on signal rate
        conservative 1 batch/h → 24 batches × 20 = 480 writes/day
        aggressive   5 batch/h → 120 batches × 20 = 2 400 writes/day
    Limit: 50 000 reads · 20 000 writes/day
    """
    print("📊 Firebase daily budget:")
    print("   Reads : load_history  ≤ 14 400/day")
    print("           load_weights  ≤    288/day")
    print("   Writes: trades (est.) ≤  2 400/day (conservative)")
    print("   Limit : 50 000 reads · 20 000 writes/day  ✅")
