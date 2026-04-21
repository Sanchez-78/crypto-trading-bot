"""
Firebase client – centralized Firestore access layer.

Free-tier quotas: 50 000 reads/day · 20 000 writes/day · 1 GB storage

PERF_MODE=False  conservative (default):
  history  600 s / 100 docs  →  14 400 reads/day
  weights  300 s             →     288 reads/day
  signals  900 s             →  negligible
  writes   ~10 300/day                           ✅ safe

PERF_MODE=True  performance (enable when WR>45% AND PF>1.5):
  history  300 s / 200 docs  →  57 600 reads/day  ⚠ near limit — monitor
  weights  120 s             →     720 reads/day
  signals  600 s             →  negligible
  writes   ~11 500/day                           ✅ safe

Switch: set PERF_MODE=True in this file; restart bot.
"""

import firebase_admin
from firebase_admin import credentials, firestore
import os, json, base64, time, requests, threading

PREFIX = os.getenv("COLLECTION_PREFIX", "")

def col(name: str) -> str:
    """Returns prefixed collection name for Shadow Mode."""
    return f"{PREFIX}{name}"


# ── Globals ───────────────────────────────────────────────────────────────────

db = None

_HISTORY_CACHE  = {"data": [],   "ts": 0}
_WEIGHTS_CACHE  = {"data": None, "ts": 0}
_SIGNALS_CACHE  = {"data": [],   "ts": 0}
_RETRY_QUEUE    = []   # trades buffered after save_batch failure; flushed on next call
_MAX_RETRY_SIZE = 50000  # BUG FIX: prevent unbounded growth during Firebase outage (OOM risk)

# Local mirror of system/stats — updated synchronously in increment_stats().
# save_metrics_full() uses this as the authoritative trade count so the
# dashboard always shows the value that matches the Firestore atomic counter,
# not the (potentially lagged) in-memory METRICS dict.
_local_stats: dict = {"trades": 0, "wins": 0, "losses": 0, "timeouts": 0}


# ── Performance tier ───────────────────────────────────────────────────────────
# False = conservative (default).  True = performance (flip when WR>45%, PF>1.5)
PERF_MODE = False

HISTORY_LIMIT  = 200 if PERF_MODE else 100   # docs per fetch
SIGNALS_LIMIT  = 200

HISTORY_TTL    = 300 if PERF_MODE else 600   # 5 min  vs  10 min
WEIGHTS_TTL    = 120 if PERF_MODE else 300   # 2 min  vs   5 min
SIGNALS_TTL    = 600 if PERF_MODE else 900   # 10 min vs  15 min


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
    print("[Firebase] connected")
    return db


def get_db():
    return db


# ── Trade helpers ─────────────────────────────────────────────────────────────

def _slim_trade(trade):
    """
    Strip redundant/derived fields before storing.
    Keeps only what the decision engine needs for pattern matching.
    Saves ~40% Firestore document size vs raw trade dict.

    ws and ev are stored explicitly so bootstrap_from_history() can seed
    lm_update() and the calibrator with real values instead of 0.5 defaults.
    Boolean edge features (trend/pullback/bounce/etc.) are stored separately
    from continuous indicators so update_edge_stats() can filter them correctly.
    """
    feat = trade.get("features") or {}
    # Boolean edge features used by update_edge_stats / lm_update
    bool_feats = {k: bool(v) for k, v in feat.items() if isinstance(v, bool)}
    return {
        "symbol":       trade.get("symbol"),
        "action":       trade.get("action"),
        "signal":       trade.get("action"),          # app uses 'signal' not 'action'
        "price":        round(float(trade.get("price",      0)), 4),
        "exit_price":   round(float(trade.get("exit_price", 0)), 4),
        "profit":       round(float(trade.get("profit",     0)), 8),
        "pnl":          round(float(trade.get("profit",     0)), 8),
        "result":       trade.get("result"),
        "close_reason": trade.get("close_reason"),
        "confidence":   round(float(trade.get("confidence", 0)), 4),
        "regime":       trade.get("regime", "RANGING"),
        "strategy":     trade.get("regime", "RANGING"),
        "ws":           round(float(trade.get("ws",  0.5)), 4),   # weighted score at entry
        "ev":           round(float(trade.get("ev",  0.0)), 4),   # expected value at entry
        "timestamp":    trade.get("timestamp", time.time()),
        "opened_at":    trade.get("timestamp", time.time()),
        "closed_at":    trade.get("close_time", time.time()),
        "status":       "closed",
        "mae":          round(float(trade.get("mae", 0)), 6),
        "mfe":          round(float(trade.get("mfe", 0)), 6),
        "stop_loss":    round(float(trade.get("stop_loss")  or 0), 6),
        "take_profit":  round(float(trade.get("take_profit") or 0), 6),
        "features": {
            **bool_feats,   # trend, pullback, bounce, breakout, vol, mom, wick
            "ema_diff":   round(float(feat.get("ema_diff",   0)), 6),
            "rsi":        round(float(feat.get("rsi",       50)), 2),
            "volatility": round(float(feat.get("volatility", 0)), 6),
            "macd":       round(float(feat.get("macd",       0)), 8),
            "adx":        round(float(feat.get("adx",       20)), 2),
            "adx_slope":  round(float(feat.get("adx_slope",  0)), 4),
            "rsi_slope":  round(float(feat.get("rsi_slope",  0)), 4),
            "obi":        round(float(feat.get("obi", 0.0)), 4),
            "hour_utc":   int(feat.get("hour_utc", 12)),
            "is_weekend": bool(feat.get("is_weekend", False)),
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
            db.collection(col("trades"))
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

    DB-vanish resilience: on first failure waits 3 s and retries once.
    If the retry also fails the batch is appended to _RETRY_QUEUE so the
    next successful save_batch call will flush it.  Prevents silent data
    loss when Firebase is temporarily unavailable (Railway restart, quota
    spike, network blip).
    """
    if db is None:
        return

    # Drain any previously failed batches first
    if _RETRY_QUEUE:
        batch = list(_RETRY_QUEUE) + list(batch)
        _RETRY_QUEUE.clear()

    try:
        slimmed  = [_slim_trade(t) for t in batch]
        fb_batch = db.batch()
        for item in slimmed:
            fb_batch.set(db.collection(col("trades")).document(), item)
        fb_batch.commit()
        _HISTORY_CACHE["data"] = (slimmed + _HISTORY_CACHE["data"])[:HISTORY_LIMIT]
        _HISTORY_CACHE["ts"]   = time.time()
        
        # Count wins/losses/timeouts for atomic stats update
        # FIX: use the SAME timeout reason set as learning_event._update_metrics_locked
        # to keep system/stats.total_timeouts consistent with METRICS["timeouts"].
        _BATCH_TIMEOUT_REASONS = {
            "timeout", "TIMEOUT_PROFIT", "TIMEOUT_FLAT", "TIMEOUT_LOSS",
            "SCRATCH_EXIT", "STAGNATION_EXIT",
        }
        wins     = sum(1 for t in slimmed if t.get("result") == "WIN")
        losses   = sum(1 for t in slimmed if t.get("result") == "LOSS")
        timeouts = sum(
            1 for t in slimmed
            if t.get("close_reason", t.get("reason", "")) in _BATCH_TIMEOUT_REASONS
            and abs(float(t.get("profit", 0))) < 0.001
        )
        increment_stats(len(batch), wins, losses, timeouts)

        print(f"💾 Firebase: saved {len(batch)} trades (batch write)")
        return len(batch)
    except Exception as e:
        print(f"⚠️  save_batch failed ({e}) — queuing for retry (no blocking sleep)")
        # BUG FIX: Removed time.sleep(3) that blocked market stream thread
        # If Firebase fails, queue batch and return immediately instead of blocking
        # Market stream must stay responsive to price ticks
        if len(_RETRY_QUEUE) < _MAX_RETRY_SIZE:  # BUG FIX: prevent unbounded growth
            _RETRY_QUEUE.extend(batch)  # Queue for next flush cycle
        else:
            print(f"⚠️  _RETRY_QUEUE full ({len(_RETRY_QUEUE)} >= {_MAX_RETRY_SIZE}) — dropping batch")
        return 0


def save_trade(trade, result):
    """Single-trade save used by legacy evaluator.py."""
    combined = {**trade, **result, "timestamp": time.time()}
    save_batch([combined])


# ── Trade counter (system/stats) ─────────────────────────────────────────────
# A single lightweight document holds the all-time completed-trade count.
# Incremented atomically via firestore.Increment after every save_batch so
# bootstrap_from_history gets the true total even when history is capped at
# HISTORY_LIMIT (100–200 docs).  Costs 1 read on startup + 1 write per batch.

_STATS_DOC = col("system") + "/stats"


def increment_stats(n: int = 1, wins: int = 0, losses: int = 0, timeouts: int = 0) -> None:
    """Atomically update counters in system/stats AND _local_stats cache.

    _local_stats is updated synchronously so save_metrics_full() can read
    the correct trade count without making an extra Firestore call.
    """
    global _local_stats
    # Always update local mirror synchronously — zero Firestore I/O
    if n > 0:        _local_stats["trades"]   += n
    if wins > 0:     _local_stats["wins"]     += wins
    if losses > 0:   _local_stats["losses"]   += losses
    if timeouts > 0: _local_stats["timeouts"] += timeouts

    if db is None or (n <= 0 and wins <= 0 and losses <= 0 and timeouts <= 0):
        return
    try:
        upd = {"updated_at": time.time()}
        if n > 0:        upd["total_trades"]   = firestore.Increment(n)
        if wins > 0:     upd["total_wins"]     = firestore.Increment(wins)
        if losses > 0:   upd["total_losses"]   = firestore.Increment(losses)
        if timeouts > 0: upd["total_timeouts"] = firestore.Increment(timeouts)
        db.document(_STATS_DOC).set(upd, merge=True)
    except Exception as e:
        print(f"⚠️  increment_stats: {e}")



def load_stats() -> dict:
    """Return stats from system/stats.  Seeds _local_stats on first load."""
    global _local_stats
    if db is None:
        return {}
    try:
        doc = db.document(_STATS_DOC).get()
        if doc.exists:
            d = doc.to_dict()
            result = {
                "trades":   int(d.get("total_trades",   0)),
                "wins":     int(d.get("total_wins",     0)),
                "losses":   int(d.get("total_losses",   0)),
                "timeouts": int(d.get("total_timeouts", 0)),
            }
            # Seed local mirror so save_metrics_full starts with the right value
            for k in _local_stats:
                _local_stats[k] = max(_local_stats[k], result[k])
            return result
    except Exception as e:
        print(f"⚠️  load_stats: {e}")
    return {}



def load_trade_count() -> int | None:
    """Legacy shim for learning_event.py."""
    return load_stats().get("trades", 0)


# ── Model state (calibrator + learning histories + bayes/bandit) ───────────────

_MODEL_STATE_DOC = col("model_state") + "/latest"   # single document, overwritten each save

def save_model_state(state: dict) -> None:
    """
    Persist calibrator buckets, EV/score histories, and bayes/bandit stats
    to a single Firestore document.  ~1 write per 5 trades — negligible budget.
    """
    if db is None:
        return
    try:
        db.document(_MODEL_STATE_DOC).set({**state, "saved_at": time.time()})
    except Exception as e:
        print(f"⚠️  save_model_state: {e}")


def load_model_state() -> dict:
    """Return persisted model state dict, or {} if not available."""
    if db is None:
        return {}
    try:
        doc = db.document(_MODEL_STATE_DOC).get()
        return doc.to_dict() if doc.exists else {}
    except Exception as e:
        print(f"⚠️  load_model_state: {e}")
        return {}


def load_old_trades(limit=200):
    """
    Load oldest trades for cleanup (auto_cleaner.py).
    Returns dicts with injected 'id' field (Firestore doc ID).
    """
    if db is None:
        return []
    try:
        docs = (
            db.collection(col("trades"))
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
        db.collection(col("trades")).document(doc_id).delete()
    except Exception as e:
        print(f"❌ delete_trade: {e}")


def save_compressed(data):
    """Save a compressed trade summary (auto_cleaner.py)."""
    if db is None:
        return
    try:
        db.collection(col("trades_compressed")).add(data)
    except Exception as e:
        print(f"❌ save_compressed: {e}")


# ── Signals ───────────────────────────────────────────────────────────────────

def save_signal(signal):
    """Save a signal document, return its doc ID."""
    if db is None:
        return None
    try:
        _, ref = db.collection(col("signals")).add(signal)
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
            db.collection(col("signals"))
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
        doc = db.collection(col("weights")).document("model").get()
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
        db.collection(col("weights")).document("model").set(data, merge=True)
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
        db.collection(col("portfolio")).document("state").set(
            {**data, "updated_at": now}, merge=True
        )
        _last_portfolio_save = now
    except Exception as e:
        print(f"❌ save_portfolio: {e}")


# ── Metrics ───────────────────────────────────────────────────────────────────

def save_metrics(data):
    """Write legacy run statistics (main.py batch mode).

    FIX: redirected to metrics/run_status to prevent overwriting the
    main metrics/latest document that bot2 manages via save_metrics_full().
    If both processes were writing to metrics/latest (one with merge=False,
    one with merge=True), the app could see stale or partial data.
    """
    if db is None:
        return
    try:
        db.collection(col("metrics")).document("run_status").set(
            {**data, "timestamp": time.time()}, merge=True
        )
    except Exception as e:
        print(f"❌ save_metrics: {e}")



def save_last_trade(trade):
    """Write last closed trade summary to metrics/last_trade (TradesScreen)."""
    if db is None:
        return
    try:
        db.collection(col("metrics")).document("last_trade").set({
            "symbol":     trade.get("symbol"),
            "action":     trade.get("action"),
            "result":     trade.get("result"),
            "pnl":        round(float(trade.get("profit", 0)), 8),
            "price":      round(float(trade.get("price", 0)), 4),
            "exit_price": round(float(trade.get("exit_price", 0)), 4),
            "confidence": round(float(trade.get("confidence", 0)), 4),
            "mae":        round(float(trade.get("mae", 0)), 6),
            "mfe":        round(float(trade.get("mfe", 0)), 6),
            "regime":     trade.get("regime", "RANGING"),
            "reason":     trade.get("close_reason", ""),
            "timestamp":  trade.get("close_time", trade.get("timestamp", time.time())),  # CONSISTENCY FIX: use close_time for sorting
        }, merge=False)
        
        # Fire and forget push notification
        pnl_pct = round(float(trade.get("profit", 0) * 100), 2)
        sym = trade.get("symbol", "")
        res = trade.get("result", "")
        sign = "+" if pnl_pct >= 0 else ""
        msg = f"Bot uzavřel {sym} s výsledkem {res} ({sign}{pnl_pct}%)"
        threading.Thread(target=send_push_notification, args=(f"Obchod uzavřen: {sym}", msg), daemon=True).start()

    except Exception as e:
        print(f"❌ save_last_trade: {e}")

def send_push_notification(title, body):
    """Fetch Expo push token and send notification."""
    if db is None: return
    try:
        doc = db.collection(col("config")).document("push_tokens").get()
        if not doc.exists: return
        token = doc.to_dict().get("token")
        if not token: return
        
        payload = {
            "to": token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": {"action": "trade_closed"}
        }
        resp = requests.post("https://exp.host/--/api/v2/push/send", json=payload, timeout=5)
        if resp.status_code == 200:
            print(f"📡 Push notifikace odeslána: {title}")
        else:
            print(f"⚠️  Push API chyba: {resp.text}")
    except Exception as e:
        print(f"⚠️  selhání push notifikace: {e}")


def _build_open_positions(positions):
    """Serialise open_positions dict for Firestore (no nested objects)."""
    if not positions:
        return {}
    out = {}
    for sym, pos in positions.items():
        entry  = pos.get("entry", 0)
        tp_pct = round(pos.get("tp_move", 0) * 100, 3)
        sl_pct = round(pos.get("sl_move", 0) * 100, 3)
        out[sym] = {
            "action":   pos.get("action"),
            "entry":    round(float(entry), 4),
            "tp_pct":   tp_pct,
            "sl_pct":   sl_pct,
            "ticks":    pos.get("ticks", 0),
            "size":     round(float(pos.get("size", 0)), 4),
        }
    return out


def _sanitize_doc(obj):
    """
    Recursively strip Firestore-illegal dict keys before .set().
    Firestore rejects: None keys, empty-string keys, and keys containing '.'.
    Drops the offending key (with a fallback rename for '.' cases).
    """
    if isinstance(obj, dict):
        clean = {}
        for k, v in obj.items():
            if not isinstance(k, str) or not k:
                continue   # drop None / non-string / empty keys
            safe_k = k.replace(".", "_")   # dots create phantom sub-paths
            clean[safe_k] = _sanitize_doc(v)
        return clean
    if isinstance(obj, list):
        return [_sanitize_doc(i) for i in obj]
    return obj


def save_metrics_full(metrics, open_positions=None, execution=None, monitor=None, fx_usd_czk=None):
    """
    Write full nested metrics to metrics/latest.
    Called every 30 s from bot2/main.py.
    App reads: performance, health, learning, equity, system, sym_stats,
               open_positions, execution (EV/failure/sharpe/control),
               fx_usd_czk (CZK/USD fallback for app when Frankfurter API is down).
    """
    if db is None:
        return
    try:
        # FIX: authority = max(in-memory METRICS, synchronously-updated _local_stats).
        # _local_stats is incremented in increment_stats() which fires from save_batch()
        # immediately upon trade close -- no async-worker delay. This eliminates the
        # 0-30 s lag that caused the dashboard to show stale/flickering trade counts.
        t   = max(metrics.get("trades", 0), _local_stats.get("trades", 0))
        wr  = metrics.get("winrate", 0.0)
        pf  = metrics.get("profit_factor", 1.0)
        exp = metrics.get("expectancy", 0.0)
        dd  = metrics.get("drawdown", 0.0)
        ep  = metrics.get("equity_peak", 0.0)
        pr  = metrics.get("profit", 0.0)
        rdy = metrics.get("ready", False)
        lt  = metrics.get("learning_trend", "SBÍRÁ DATA...")
        ca  = metrics.get("confidence_avg", 0.0)
        rwr = metrics.get("recent_winrate", 0.0)
        rc  = metrics.get("recent_count", 0)
        blk = metrics.get("blocked", 0)
        gen = metrics.get("signals_generated", 0)
        flt = metrics.get("signals_filtered", 0)
        exe = metrics.get("signals_executed", 0)

        # health score: weighted combination of WR, PF, drawdown
        score = int(min(100, max(0,
            wr * 50 +
            min(pf / 3.0, 1.0) * 30 -
            min(dd * 5000, 20)
        )))
        if rdy:
            status = "HEALTHY"
        elif wr >= 0.45 and pf >= 1.0:
            status = "RISKY"
        elif t < 20:
            status = "LEARNING"
        else:
            status = "BAD"

        regimes = metrics.get("regimes", {})
        dominant_regime = max(regimes, key=regimes.get) if regimes else "RANGING"

        lp = metrics.get("last_prices", {})
        prices_clean = {sym: vals[0] for sym, vals in lp.items()}

        # Convert Czech trend text → English enum for app
        _trend_map = {
            "ZLEPŠUJE": "IMPROVING",
            "ZHORŠUJE": "WORSENING",
            "STABILNÍ": "STABLE",
        }
        trend_en = next((v for k, v in _trend_map.items() if k in lt), "STABLE")

        # Learning state: GOOD if profitable (PF >= 1.5), regardless of WR
        # WR alone is misleading with high RR — a 2:1 system is fine at 45% WR
        if t < 20:
            learn_state = "LEARNING"
        elif rdy or pf >= 1.5:
            learn_state = "GOOD"
        elif pf >= 1.0 and wr >= 0.40:
            learn_state = "LEARNING"
        else:
            learn_state = "BAD"

        ev_st  = metrics.get("ev_stats",    {})
        cl_st  = metrics.get("close_stats", {})
        rg_raw = metrics.get("regime_stats", {})
        # Serialise regime_stats: {regime: {trades, winrate}}
        rg_st  = {k: {"trades": v["trades"], "winrate": round(v["winrate"], 4)}
                  for k, v in rg_raw.items() if v.get("trades", 0) > 0}

        # NOTE: wins/losses/timeouts/wr come ONLY from get_metrics() (METRICS dict).
        # _update_metrics_locked() correctly excludes neutral timeouts from wins/losses.
        # save_batch() counts all result=="WIN" into _local_stats.wins including those
        # neutral timeouts — using max() here would inflate wins and DROP winrate.
        # Only the TOTAL trade count `t` safely uses _local_stats (both paths count
        # every trade the same way regardless of category).
        _wins        = metrics.get("wins",     0)
        _losses      = metrics.get("losses",   0)
        _timeouts    = metrics.get("timeouts", 0)
        _decisive    = _wins + _losses      # neutral timeouts excluded from WR
        # Mark WR as unreliable below 10 decisive trades to avoid misleading 100%
        _wr_reliable = _decisive >= 10

        _cur_dd = metrics.get("current_drawdown", 0.0)
        _cur_dd_pct = round(_cur_dd / ep, 4) if ep > 0 else 0.0

        _now = time.time()
        _last_trade_ts = metrics.get("last_trade_ts", 0.0)  # CONSISTENCY FIX: unified key name

        data = {
            # ── Envelope metadata ─────────────────────────────────────────────
            "schema_version":  "v2",
            "generated_at_ts": _now,
            "freshness": {
                "portfolio_age_s":    0,           # always current — computed per flush
                "performance_age_s":  0,
                "strategy_age_s":     0,
                "last_trade_age_s":   round(_now - _last_trade_ts, 1) if _last_trade_ts else None,
            },

            # ── Portfolio: equity & drawdown ──────────────────────────────────
            "portfolio": {
                "equity_abs":           round(pr, 8),
                "equity_peak_abs":      round(ep, 8),
                "drawdown_max_abs":     round(dd, 8),
                "drawdown_current_abs": round(_cur_dd, 8),
                "drawdown_current_pct": _cur_dd_pct,
            },

            # ── Performance: winrate, PF, EV, trade quality ───────────────────
            "performance": {
                "winrate_ratio":        round(wr, 4),
                "winrate_reliable":     _wr_reliable,
                "profit_factor_ratio":  round(pf, 4),
                "expectancy_abs":       round(exp, 8),
                "avg_win_abs":          round(metrics.get("avg_win", 0.0), 8),
                "avg_loss_abs":         round(metrics.get("avg_loss", 0.0), 8),
                "best_trade_abs":       round(metrics.get("best_trade", 0.0), 8),
                "worst_trade_abs":      round(metrics.get("worst_trade", 0.0), 8),
                "win_streak_count":     metrics.get("win_streak", 0),
                "loss_streak_count":    metrics.get("loss_streak", 0),
                "recent_winrate_ratio": round(rwr, 4),
                "recent_count":         rc,
                "trend":                trend_en,
                "trend_cs":             lt,
            },

            # ── Strategy: trade counts, regime/symbol/exit breakdown ──────────
            "strategy": {
                "trades_count":       t,
                "wins_count":         _wins,
                "losses_count":       _losses,
                "timeouts_count":     _timeouts,
                "decisive_count":     _decisive,
                "timeout_rate_ratio": round(_timeouts / t, 4) if t else 0.0,
                "confidence_avg":     round(ca, 4),
                "ev_stats":           ev_st,
                "close_stats":        cl_st,
                "regime_stats":       rg_st,
                "sym_stats":          metrics.get("sym_stats", {}),
            },

            # ── Health: bot state & learning quality ──────────────────────────
            "health": {
                "score":          score,
                "status":         status,
                "ready":          rdy,
                "learning_state": learn_state,
            },

            # ── System: runtime, signals, positions, fx ───────────────────────
            "system": {
                "trading_enabled":          True,
                "dominant_regime":          dominant_regime,
                "regimes":                  regimes,
                "signals_generated_count":  gen,
                "signals_filtered_count":   flt,
                "signals_executed_count":   exe,
                "signals_blocked_count":    blk,
                "last_trade_ts":            _last_trade_ts,
                "last_prices":              prices_clean,
                "last_signals":             metrics.get("last_signals", {}),
                "open_positions":           _build_open_positions(open_positions),
                "execution":                execution,
                "monitor":                  monitor,
                "fx_usd_czk":               round(float(fx_usd_czk), 4) if fx_usd_czk else None,
            },
        }
        db.collection(col("metrics")).document("latest").set(_sanitize_doc(data), merge=False)
    except Exception as e:
        print(f"❌ save_metrics_full: {e}")


# ── Auditor state ─────────────────────────────────────────────────────────────

def save_auditor_state(data):
    """Persist auditor state (min_conf, pos_size_mult) across restarts."""
    if db is None:
        return
    try:
        db.collection(col("metrics")).document("auditor").set(
            {**data, "saved_at": time.time()}, merge=False
        )
    except Exception as e:
        print(f"❌ save_auditor_state: {e}")


def load_auditor_state():
    """Load persisted auditor state; returns {} if not found."""
    if db is None:
        return {}
    try:
        doc = db.collection(col("metrics")).document("auditor").get()
        return doc.to_dict() or {}
    except Exception as e:
        print(f"❌ load_auditor_state: {e}")
        return {}


# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    """Load runtime config from Firestore (execution_bot.py)."""
    if db is None:
        return {}
    try:
        doc = db.collection(col("config")).document("runtime").get()
        return doc.to_dict() or {}
    except Exception as e:
        print(f"❌ load_config: {e}")
        return {}


# ── Bot2 → Bot1 advice channel ────────────────────────────────────────────────
# Bot2 writes a compact advice doc after every audit cycle.
# Bot1 reads it before opening trades — skips blocked pairs, sizes up winners.
# 1 write per 30s from bot2 audit = 2 880 writes/day (within budget).
# Bot1 reads with 60s TTL = ~1 440 reads/day.

_ADVICE_DOC   = col("advice") + "/latest"   # advice/latest
_ADVICE_CACHE = {"data": None, "ts": 0}
ADVICE_TTL    = 60  # seconds


def save_bot2_advice(advice: dict) -> None:
    """
    Write bot2 learning state for bot1 to consume.
    Called from bot2/auditor.py after every audit cycle.

    Schema:
      blocked_pairs:  list of "SYMREGIME" strings bot1 must skip
      top_pairs:      list of {sym, regime, ev, wr} — highest EV confirmed pairs
      regime_ev:      {regime: ev} — average EV per regime across all pairs
      loss_streak:    int — current system-wide loss streak
      health:         float — lm_health() score
      timestamp:      float
    """
    if db is None:
        return
    try:
        db.document(_ADVICE_DOC).set({**advice, "timestamp": time.time()})
        _ADVICE_CACHE["data"] = dict(advice)
        _ADVICE_CACHE["ts"]   = time.time()
    except Exception as e:
        print(f"⚠️  save_bot2_advice: {e}")


def load_bot2_advice() -> dict:
    """
    Read bot2 advice with 60s TTL cache.
    Returns {} if Firebase unavailable or no advice written yet.
    """
    if db is None:
        return {}
    if _ADVICE_CACHE["data"] is not None and \
       time.time() - _ADVICE_CACHE["ts"] < ADVICE_TTL:
        return dict(_ADVICE_CACHE["data"])
    try:
        doc = db.document(_ADVICE_DOC).get()
        _ADVICE_CACHE["data"] = doc.to_dict() or {}
        _ADVICE_CACHE["ts"]   = time.time()
    except Exception as e:
        print(f"⚠️  load_bot2_advice: {e}")
        return _ADVICE_CACHE["data"] or {}
    return dict(_ADVICE_CACHE["data"])


def load_bot2_metrics() -> dict:
    """
    Read the live metrics/latest that bot2 writes every 30s.
    Returns performance (winrate, profit_factor, drawdown) for bot1's
    RiskEngine to use instead of hardcoded stubs.
    TTL 60s — same as advice channel.
    """
    if db is None:
        return {}
    try:
        doc = db.collection(col("metrics")).document("latest").get()
        return doc.to_dict() or {}
    except Exception as e:
        print(f"⚠️  load_bot2_metrics: {e}")
        return {}


# ── Daily budget report ───────────────────────────────────────────────────────

def daily_budget_report():
    """
    Estimate daily Firebase operation counts (call once at startup).
    Limit: 50 000 reads · 20 000 writes/day (free tier).
    """
    mode = "PERFORMANCE" if PERF_MODE else "CONSERVATIVE"
    hl   = HISTORY_LIMIT
    ht   = HISTORY_TTL
    wt   = WEIGHTS_TTL

    r_hist = hl * (86400 // ht)
    r_wgt  = 86400 // wt
    r_tot  = r_hist + r_wgt

    print(f"📊 Firebase daily budget  [{mode}]")
    print(f"   Reads : load_history  ≤ {r_hist:>6}/day  ({hl} docs, cache {ht}s)")
    print(f"           load_weights  ≤ {r_wgt:>6}/day")
    print(f"           total reads   ≈ {r_tot:>6}/day  (limit 50 000)  {'✅' if r_tot < 45000 else '⚠️'}")
    print(f"   Writes: metrics/latest every 10s  =  8 640/day")
    print(f"           save_batch    every 60s   =  1 440/day")
    print(f"           save_last_trade (est.)    =    200/day")
    print(f"   Total : ~10 280 writes/day  (limit 20 000)  ✅")
    if not PERF_MODE:
        print(f"   ℹ️  Set PERF_MODE=True when WR>45% AND PF>1.5 for fresher calibration")
