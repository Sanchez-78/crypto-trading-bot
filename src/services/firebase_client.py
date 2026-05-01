"""
Firebase client – centralized Firestore access layer.

Free-tier quotas: 50 000 reads/day · 20 000 writes/day · 1 GB storage

PERF_MODE=False  conservative (default):
  history  1800 s / 100 docs  →  4 800 reads/day (V10.13o: extended TTL)
  weights  900 s              →    96 reads/day
  signals  1800 s             →  negligible
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
import logging
import os, json, base64, time, requests, threading

# V10.13u: Safe logging for exception messages (prevent secret leakage)
try:
    from src.services.safe_logging import safe_log_exception
except ImportError:
    def safe_log_exception(e):
        return f"{type(e).__name__}: {str(e)}"

PREFIX = os.getenv("COLLECTION_PREFIX", "")

def col(name: str) -> str:
    """Returns prefixed collection name for Shadow Mode."""
    return f"{PREFIX}{name}"


# ── Globals ───────────────────────────────────────────────────────────────────

db = None

_HISTORY_CACHE  = {"data": [],   "ts": 0, "limit": 0}
_WEIGHTS_CACHE  = {"data": None, "ts": 0}
_SIGNALS_CACHE  = {"data": [],   "ts": 0}
_CONFIG_CACHE   = {"data": None, "ts": 0}
_ADVICE_CACHE   = {"data": None, "ts": 0}
_METRICS_CACHE  = {"data": None, "ts": 0}
_PUSH_TOKEN_CACHE = {"data": None, "ts": 0}
_RETRY_QUEUE    = []   # trades buffered after save_batch failure; flushed on next call
_MAX_RETRY_SIZE = 50000  # BUG FIX: prevent unbounded growth during Firebase outage (OOM risk)

# V10.14: Proactive quota tracking — track reads/writes against 50k/20k daily limits
_QUOTA_WINDOW_START = time.time()  # Midnight UTC of current quota day
_QUOTA_READS = 0    # Current day read count
_QUOTA_WRITES = 0   # Current day write count
_QUOTA_MAX_READS = 50000
_QUOTA_MAX_WRITES = 20000

# EMERGENCY (2026-04-25): Firebase degradation tracking — safe mode on 429/unavailable
_FIREBASE_READ_DEGRADED = False
_FIREBASE_WRITE_DEGRADED = False
_FIREBASE_DEGRADED_UNTIL = 0  # timestamp when degradation expires
_FIREBASE_LAST_ERROR = None  # Last error message (429, timeout, etc)
_FIREBASE_DEGRADED_REASON = None  # "quota_429" | "unavailable" | None

# V10.13x: Reconciliation logging (periodic, every 300s = 5min to conserve quota)
_LAST_RECON_TS = 0
_RECON_INTERVAL = 300  # seconds between reconciliation checks (quota-safe: ~288 reads/day)

CONFIG_TTL       = 300   # runtime config changes rarely
ADVICE_TTL       = 120   # advice updates on the audit cadence
BOT2_METRICS_TTL = 300   # bot2 flushes metrics every 5 minutes
PUSH_TOKEN_TTL   = 3600  # mobile push token is slow-moving

def _reset_quota_if_new_day():
    """Reset counters at midnight Pacific Time each day (= 07:00 UTC / 09:00 GMT+2).

    Firebase quota resets at: Midnight PT = 09:00 GMT+2 = 07:00 UTC
    """
    global _QUOTA_WINDOW_START, _QUOTA_READS, _QUOTA_WRITES
    from datetime import datetime, timezone, timedelta

    # Get current time in Pacific timezone (UTC-7 for PDT, UTC-8 for PST)
    # Using UTC-7 (PDT) as the standard
    pacific_tz = timezone(timedelta(hours=-7))
    now_utc = datetime.now(timezone.utc)
    now_pacific = now_utc.astimezone(pacific_tz)

    # Get midnight Pacific today
    midnight_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_pacific.astimezone(timezone.utc)

    # Check if we've crossed midnight Pacific since last reset
    last_reset_utc = datetime.fromtimestamp(_QUOTA_WINDOW_START, tz=timezone.utc)

    if now_utc >= midnight_utc and last_reset_utc < midnight_utc:
        # We've crossed midnight Pacific since last reset
        _QUOTA_WINDOW_START = midnight_utc.timestamp()
        _QUOTA_READS = 0
        _QUOTA_WRITES = 0
        import logging
        logging.info("✅ Firebase quota RESET at midnight Pacific (09:00 GMT+2 / 07:00 UTC) — 50k reads, 20k writes available")

def refresh_quota_window_on_startup():
    """
    HOTFIX (2026-04-25): Refresh local quota window at startup.

    Prevents stale in-process quota counters from blocking hydration reads
    after Firebase daily reset (09:00 GMT+2 / 07:00 UTC).

    Call during bot startup BEFORE first Firebase reads. This ensures that
    if the bot restarts before the daily reset, the local quota window is
    refreshed to match the current calendar day.

    Side effects: None. Only resets local counters if new day detected.
    Does not ignore real 429 errors or increase actual Firebase quota.
    """
    _reset_quota_if_new_day()

def _get_quota_severity(reads_pct: float, writes_pct: float) -> str:
    """Map quota % to severity level."""
    max_pct = max(reads_pct, writes_pct)

    if max_pct >= 95:
        return "CRITICAL"
    elif max_pct >= 80:
        return "HIGH_WARNING"
    elif max_pct >= 50:
        return "WARNING"
    else:
        return "INFO"

def _can_read(count=1):
    """Check if read quota available. Returns (allowed, current_usage, limit)."""
    _reset_quota_if_new_day()
    # EMERGENCY (2026-04-25): Lowered brake from 80% to 65% due to quota exceeded incident
    # Prevents further overage while maintaining cache-backed fallback
    if _QUOTA_READS >= _QUOTA_MAX_READS * 0.65:
        return False, _QUOTA_READS, _QUOTA_MAX_READS
    allowed = (_QUOTA_READS + count) <= _QUOTA_MAX_READS
    return allowed, _QUOTA_READS, _QUOTA_MAX_READS

def _record_read(count=1):
    """Record read operation(s)."""
    global _QUOTA_READS
    _QUOTA_READS += count
    import logging
    reads_pct = _QUOTA_READS/_QUOTA_MAX_READS*100
    writes_pct = _QUOTA_WRITES/_QUOTA_MAX_WRITES*100
    severity = _get_quota_severity(reads_pct, writes_pct)

    # Log at appropriate severity level
    if _QUOTA_READS % 100 == 0:  # Every 100 reads
        msg = f"Firebase quota: reads {reads_pct:.1f}%, writes {writes_pct:.1f}%"
        if severity == "INFO":
            logging.info(msg)
        elif severity == "WARNING":
            logging.warning(f"Firebase approaching limit: {msg}")
        elif severity == "HIGH_WARNING":
            logging.warning(f"Firebase near limit: {msg}")
        elif severity == "CRITICAL":
            logging.critical(f"Firebase quota critical: {msg}")

        if severity in ("HIGH_WARNING", "CRITICAL"):
            import traceback
            logging.warning("QUOTA USAGE TRACEBACK:")
            for line in traceback.format_stack()[-5:-1]:
                logging.warning(line.strip())

def _can_write(count=1):
    """Check if write quota available. Returns (allowed, current_usage, limit)."""
    _reset_quota_if_new_day()
    allowed = (_QUOTA_WRITES + count) <= _QUOTA_MAX_WRITES
    return allowed, _QUOTA_WRITES, _QUOTA_MAX_WRITES

def _record_write(count=1):
    """Record write operation(s)."""
    global _QUOTA_WRITES
    _QUOTA_WRITES += count
    if _QUOTA_WRITES > _QUOTA_MAX_WRITES * 0.9:  # Warn at 90%
        import logging
        logging.warning(f"⚠️  Firebase writes: {_QUOTA_WRITES:,}/{_QUOTA_MAX_WRITES:,} ({_QUOTA_WRITES/_QUOTA_MAX_WRITES*100:.1f}%)")

def get_quota_status():
    """Return current quota usage as dict for monitoring."""
    _reset_quota_if_new_day()
    return {
        "reads": _QUOTA_READS,
        "reads_limit": _QUOTA_MAX_READS,
        "reads_pct": f"{_QUOTA_READS/_QUOTA_MAX_READS*100:.1f}%",
        "writes": _QUOTA_WRITES,
        "writes_limit": _QUOTA_MAX_WRITES,
        "writes_pct": f"{_QUOTA_WRITES/_QUOTA_MAX_WRITES*100:.1f}%",
    }

def _check_quota_status():
    """Check if quota exhausted (legacy, kept for compatibility)."""
    allowed_read, _, _ = _can_read()
    return not allowed_read

def _mark_quota_exhausted(error_msg: str):
    """Mark quota as exhausted via 429 error (reactive)."""
    global _QUOTA_READS, _QUOTA_WRITES
    import logging
    # Set quotas to their limits to immediately prevent further operations
    _QUOTA_READS = _QUOTA_MAX_READS
    _QUOTA_WRITES = _QUOTA_MAX_WRITES
    logging.warning(f"⚠️  Firebase 429 error: {error_msg} — marked quota exhausted until midnight Pacific reset (09:00 GMT+2)")
    # Also set degradation flags
    _set_firebase_degraded(is_read=True, is_write=True, reason="quota_429")

def _set_firebase_degraded(is_read=False, is_write=False, reason=None):
    """Mark Firebase as degraded due to 429/unavailable."""
    global _FIREBASE_READ_DEGRADED, _FIREBASE_WRITE_DEGRADED, _FIREBASE_DEGRADED_UNTIL, _FIREBASE_LAST_ERROR, _FIREBASE_DEGRADED_REASON
    import logging
    now = time.time()
    _FIREBASE_DEGRADED_UNTIL = now + 24 * 3600
    if is_read:
        _FIREBASE_READ_DEGRADED = True
    if is_write:
        _FIREBASE_WRITE_DEGRADED = True
    _FIREBASE_DEGRADED_REASON = reason
    _FIREBASE_LAST_ERROR = reason
    logging.critical(f"[FIREBASE_DEGRADED] {reason} — safe mode active until quota reset")


def _clear_firebase_degradation():
    """Clear all degradation flags on confirmed Firebase recovery."""
    global _FIREBASE_READ_DEGRADED, _FIREBASE_WRITE_DEGRADED, _FIREBASE_DEGRADED_UNTIL
    _FIREBASE_READ_DEGRADED = False
    _FIREBASE_WRITE_DEGRADED = False
    _FIREBASE_DEGRADED_UNTIL = 0

def get_firebase_health():
    """Return Firebase health status for safe-mode decisions."""
    now = time.time()
    active = now < _FIREBASE_DEGRADED_UNTIL
    return {
        "available": not (active and (_FIREBASE_READ_DEGRADED or _FIREBASE_WRITE_DEGRADED)),
        "read_degraded": _FIREBASE_READ_DEGRADED and active,
        "write_degraded": _FIREBASE_WRITE_DEGRADED and active,
        "last_error": _FIREBASE_LAST_ERROR,
        "degraded_until": _FIREBASE_DEGRADED_UNTIL if active else None,
        "reason": _FIREBASE_DEGRADED_REASON if active else None,
    }


_LAST_NONCRITICAL_SKIP_LOG = 0  # Throttle write-skip logging to once per 60s


def should_skip_noncritical_write() -> tuple[bool, str]:
    """
    EMERGENCY (2026-04-25): Check if non-critical writes should be skipped.

    Returns (should_skip, reason_code) when:
    - Firebase write_degraded (429 quota exhausted)
    - Write quota >= 95%

    Logs once per 60 seconds to avoid spam.
    Use for: metrics, advice, runtime_status, dashboards, debug snapshots.
    Do NOT use for: trade persistence (save_batch), atomic counters (increment_stats).
    """
    global _LAST_NONCRITICAL_SKIP_LOG

    allowed, current, limit_writes = _can_write(0)  # Check without incrementing
    writes_pct = (current / limit_writes * 100) if limit_writes > 0 else 0

    now = time.time()
    is_write_degraded = _FIREBASE_WRITE_DEGRADED and (now < _FIREBASE_DEGRADED_UNTIL)
    should_skip = is_write_degraded or writes_pct >= 95

    if should_skip and (now - _LAST_NONCRITICAL_SKIP_LOG) >= 60.0:
        reason = "write_degraded" if is_write_degraded else "quota_95pct"
        logging.warning(
            f"[FIREBASE_DEGRADED] write skipped: {reason} "
            f"({current}/{limit_writes} writes, {writes_pct:.1f}%)"
        )
        _LAST_NONCRITICAL_SKIP_LOG = now

    return should_skip, "FIREBASE_QUOTA_EXHAUSTED" if should_skip else ""

# Local mirror of system/stats — updated synchronously in increment_stats().
# save_metrics_full() uses this as the authoritative trade count so the
# dashboard always shows the value that matches the Firestore atomic counter,
# not the (potentially lagged) in-memory METRICS dict.
def _clone_payload(data):
    if isinstance(data, dict):
        return dict(data)
    if isinstance(data, list):
        return list(data)
    return data


def _cache_get(cache: dict, ttl: int):
    if cache.get("data") is not None and time.time() - cache.get("ts", 0) < ttl:
        return _clone_payload(cache["data"])
    return None


def _cache_set(cache: dict, data) -> None:
    cache["data"] = _clone_payload(data)
    cache["ts"] = time.time()


def _handle_quota_error(label: str, exc: Exception) -> None:
    if "429" in str(exc) or "Quota" in str(exc):
        _mark_quota_exhausted(str(exc))
    else:
        logging.error("%s: %s", label, exc)


def _read_doc_dict(doc_ref, *, label: str, cache: dict | None = None,
                   ttl: int = 0, default: dict | None = None) -> dict:
    fallback = {} if default is None else dict(default)
    cached = _cache_get(cache, ttl) if cache is not None and ttl > 0 else None
    if cached is not None:
        return cached
    if db is None:
        return dict(fallback)

    allowed, current, limit_quota = _can_read(1)
    if not allowed:
        logging.debug("Skipping %s read: quota limit reached (%s/%s)",
                      label, current, limit_quota)
        return cached if cached is not None else dict(fallback)

    try:
        doc = doc_ref.get()
        data = doc.to_dict() or dict(fallback)
        _record_read(1)
        if cache is not None and ttl > 0:
            _cache_set(cache, data)
        return dict(data)
    except Exception as exc:
        _handle_quota_error(label, exc)
        return cached if cached is not None else dict(fallback)


_local_stats: dict = {"trades": 0, "wins": 0, "losses": 0, "timeouts": 0}


# ── Performance tier ───────────────────────────────────────────────────────────
# False = conservative (default).  True = performance (flip when WR>45%, PF>1.5)
PERF_MODE = False

HISTORY_LIMIT  = 200 if PERF_MODE else 100   # docs per fetch
SIGNALS_LIMIT  = 200

# V10.15 QUOTA EMERGENCY: Increased TTL to 6 hours to prevent runaway reads (was 1h)
# Runaway read rate detected: 6000 reads in 36 min = 240k/day vs 50k limit
# EMERGENCY (2026-04-25): Further increased WEIGHTS_TTL, SIGNALS_TTL to 2h to reduce read storm
HISTORY_TTL    = 600  if PERF_MODE else 43200  # 10 min vs 12 hours  → ≤14 400 vs ≤200 reads/day
WEIGHTS_TTL    = 300  if PERF_MODE else 14400  # 5 min vs 4 hours   → ≤288  vs ≤6   reads/day
SIGNALS_TTL    = 1200 if PERF_MODE else 14400  # 20 min vs 4 hours  → ≤144  vs ≤6   reads/day


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
        "strategy":     trade.get("strategy", trade.get("regime", "RANGING")),
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

    V10.14: Proactive quota check — prevent reads if approaching 50k/day limit.
    """
    if db is None:
        return []
    if (
        time.time() - _HISTORY_CACHE["ts"] < HISTORY_TTL
        and _HISTORY_CACHE.get("limit", 0) >= limit
    ):
        return list(_HISTORY_CACHE["data"][:limit])

    # V10.14: Proactive quota check — skip if quota almost exhausted
    estimated_reads = max(1, min(limit, _HISTORY_CACHE.get("limit", 0) or HISTORY_LIMIT))
    allowed, current, limit_quota = _can_read(estimated_reads)
    if not allowed:
        cache_items = len(_HISTORY_CACHE.get("data", []))
        # EMERGENCY (2026-04-25): Log clearly when returning cache due to quota degradation, not true empty DB
        logging.warning(f"[FIREBASE_DEGRADED] load_history skipped: quota exhausted ({current}/{limit_quota}); returning cache ({cache_items} items)")
        return list(_HISTORY_CACHE["data"][:limit])  # Return stale cache (may be empty on startup)

    try:
        docs = list(
            db.collection(col("trades"))
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        _HISTORY_CACHE["data"] = [d.to_dict() for d in docs]
        _HISTORY_CACHE["ts"]   = time.time()
        _HISTORY_CACHE["limit"] = max(limit, len(_HISTORY_CACHE["data"]))
        _record_read(max(1, len(_HISTORY_CACHE["data"])))
        print(f"[FIREBASE] loaded {len(_HISTORY_CACHE['data'])} trades")
    except Exception as e:
        _handle_quota_error("load_history", e)
    return list(_HISTORY_CACHE["data"][:limit])


def _async_firebase_write(slimmed, batch_size):
    """Background thread: commit batch to Firebase without blocking critical path."""
    try:
        if db is None:
            return
        fb_batch = db.batch()
        for item in slimmed:
            fb_batch.set(db.collection(col("trades")).document(), item)
        fb_batch.commit()
        _record_write(batch_size)
    except Exception as e:
        if "429" in str(e) or "Quota" in str(e):
            _mark_quota_exhausted(str(e))
        print(f"⚠️  Async Firebase write failed: {e}")


def save_batch(batch):
    """
    Non-blocking batch write: updates local cache immediately, writes to Firebase asynchronously.
    Returns immediately without waiting for Firebase commit (critical latency fix).

    V10.15x LATENCY FIX: Moved fb_batch.commit() to background thread to eliminate
    270ms average blocking latency on trade close path. Local cache is still updated
    synchronously for consistency.
    """
    if db is None:
        return

    # Drain any previously failed batches first
    if _RETRY_QUEUE:
        batch = list(_RETRY_QUEUE) + list(batch)
        _RETRY_QUEUE.clear()

    try:
        slimmed  = [_slim_trade(t) for t in batch]

        # V10.14: Check write quota before committing
        allowed, current, limit_writes = _can_write(len(slimmed))
        if not allowed:
            import logging
            logging.warning(f"Write quota limit approaching ({current + len(slimmed)}/{limit_writes}) — queuing instead")
            _RETRY_QUEUE.extend(batch)
            return 0  # No writes committed

        # Preserve the largest requested history window so callers asking for
        # 500 trades do not silently collapse back to HISTORY_LIMIT after each save.
        cache_limit = max(HISTORY_LIMIT, _HISTORY_CACHE.get("limit", 0) or HISTORY_LIMIT)
        _HISTORY_CACHE["data"] = (slimmed + _HISTORY_CACHE["data"])[:cache_limit]
        _HISTORY_CACHE["ts"]   = time.time()
        _HISTORY_CACHE["limit"] = cache_limit

        # Count wins/losses/timeouts for atomic stats update
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

        # V10.15x LATENCY FIX: Spawn background thread for Firebase write
        # This returns immediately instead of blocking 200-300ms on commit()
        threading.Thread(
            target=_async_firebase_write,
            args=(slimmed, len(slimmed)),
            daemon=True
        ).start()

        print(f"[FIREBASE_WRITE] queued {len(batch)} trades (async write, non-blocking)")
        return len(batch)
    except Exception as e:
        # Detect 429 Quota Exceeded errors (reactive fallback) — mark quota exhausted immediately
        if "429" in str(e) or "Quota" in str(e):
            _mark_quota_exhausted(str(e))
        print(f"⚠️  save_batch failed ({safe_log_exception(e)}) — queuing for retry (no blocking sleep)")
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
        print(f"⚠️  increment_stats: {safe_log_exception(e)}")



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
        print(f"⚠️  load_stats: {safe_log_exception(e)}")
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
        _record_write(1)
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
        return list(_SIGNALS_CACHE["data"][:limit])
    try:
        docs = list(
            db.collection(col("signals"))
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        _SIGNALS_CACHE["data"] = [d.to_dict() for d in docs]
        _SIGNALS_CACHE["ts"]   = time.time()
        _record_read(max(1, len(_SIGNALS_CACHE["data"])))
        print(f"📥 Firebase: loaded {len(_SIGNALS_CACHE['data'])} signals")
    except Exception as e:
        print(f"❌ load_all_signals: {e}")
    return list(_SIGNALS_CACHE["data"][:limit])


# ── Weights ───────────────────────────────────────────────────────────────────

def load_weights():
    if db is None:
        return {}
    return _read_doc_dict(
        db.collection(col("weights")).document("model"),
        label="load_weights",
        cache=_WEIGHTS_CACHE,
        ttl=WEIGHTS_TTL,
    )

def save_weights(data):
    """Persist model weights and update local cache."""
    if db is None:
        return
    try:
        db.collection(col("weights")).document("model").set(data, merge=True)
        _record_write(1)
        _cache_set(_WEIGHTS_CACHE, data)
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
        _record_write(1)
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

    EMERGENCY (2026-04-25): Skip on Firebase degradation (non-critical write).
    """
    if db is None:
        return
    # Skip non-critical write if Firebase degraded
    should_skip, _ = should_skip_noncritical_write()
    if should_skip:
        return
    try:
        db.collection(col("metrics")).document("run_status").set(
            {**data, "timestamp": time.time()}, merge=True
        )
        _record_write(1)
    except Exception as e:
        print(f"❌ save_metrics: {e}")



def save_last_trade(trade):
    """Write last closed trade summary to metrics/last_trade (TradesScreen).

    EMERGENCY (2026-04-25): Skip on Firebase degradation (non-critical write).
    """
    if db is None:
        return

    # Skip non-critical write if Firebase degraded
    should_skip, _ = should_skip_noncritical_write()
    if should_skip:
        return

    def _write():
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
                "timestamp":  trade.get("close_time", trade.get("timestamp", time.time())),
            }, merge=False)
            _record_write(1)

            pnl_pct = round(float(trade.get("profit", 0) * 100), 2)
            sym = trade.get("symbol", "")
            res = trade.get("result", "")
            sign = "+" if pnl_pct >= 0 else ""
            msg = f"Bot uzavřel {sym} s výsledkem {res} ({sign}{pnl_pct}%)"
            send_push_notification(f"Obchod uzavřen: {sym}", msg)
        except Exception as e:
            print(f"❌ save_last_trade: {e}")

    threading.Thread(target=_write, daemon=True).start()


def load_push_token():
    if db is None:
        return None
    data = _read_doc_dict(
        db.collection(col("config")).document("push_tokens"),
        label="load_push_token",
        cache=_PUSH_TOKEN_CACHE,
        ttl=PUSH_TOKEN_TTL,
    )
    token = data.get("token")
    return token or None


def send_push_notification(title, body):
    """Fetch Expo push token and send notification."""
    if db is None: return
    try:
        token = load_push_token()
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

    EMERGENCY (2026-04-25): Skip on Firebase degradation (non-critical write).
    """
    if db is None:
        return
    # Skip non-critical write if Firebase degraded
    should_skip, _ = should_skip_noncritical_write()
    if should_skip:
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

        # V10.13x: Periodic reconciliation check (every 60s) to validate metrics integrity
        global _LAST_RECON_TS
        if _now - _LAST_RECON_TS >= _RECON_INTERVAL:
            try:
                from src.services.metrics_engine import MetricsEngine
                engine = MetricsEngine()
                recent_trades = load_history(limit=HISTORY_LIMIT)  # use cache-aligned limit to avoid quota storm
                canonical = engine.compute_canonical_trade_stats(recent_trades)

                # Log reconciliation status
                recon_msg = f"[V10.13x RECON] trades={canonical['trades_total']} " \
                            f"(wins={canonical['wins']} losses={canonical['losses']} flats={canonical['flats']}) " \
                            f"net_pnl={canonical['net_pnl']:+.8f} status={'OK' if canonical['reconciliation']['verified'] else 'MISMATCH'}"

                if not canonical['reconciliation']['verified']:
                    alerts = "; ".join(canonical['reconciliation']['alerts'])
                    print(f"⚠️  {recon_msg} — alerts: {alerts}")
                    import logging
                    logging.warning(recon_msg + f" — {alerts}")
                else:
                    print(recon_msg)

                _LAST_RECON_TS = _now
            except Exception as e:
                # Don't let reconciliation errors block metrics saving
                import logging
                logging.error(f"V10.13x reconciliation failed: {e}")

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
                "learning":       metrics.get("learning", {}),  # learning block from get_metrics()
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
                "rejection_breakdown":      metrics.get("rejection_breakdown", {}),  # Signal filtering breakdown
            },
        }
        data = _sanitize_doc(data)
        db.collection(col("metrics")).document("latest").set(data, merge=False)
        _record_write(1)
        _cache_set(_METRICS_CACHE, data)
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
        _record_write(1)
    except Exception as e:
        print(f"❌ save_auditor_state: {e}")


def load_auditor_state():
    if db is None:
        return {}
    return _read_doc_dict(
        db.collection(col("metrics")).document("auditor"),
        label="load_auditor_state",
    )
# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    if db is None:
        return {}
    return _read_doc_dict(
        db.collection(col("config")).document("runtime"),
        label="load_config",
        cache=_CONFIG_CACHE,
        ttl=CONFIG_TTL,
    )
# ── Bot2 → Bot1 advice channel ────────────────────────────────────────────────
# Bot2 writes a compact advice doc after every audit cycle.
# Bot1 reads it before opening trades — skips blocked pairs, sizes up winners.
# 1 write per 30s from bot2 audit = 2 880 writes/day (within budget).
# Bot1 reads with 60s TTL = ~1 440 reads/day.

_ADVICE_DOC   = col("advice") + "/latest"   # advice/latest
# _ADVICE_CACHE and ADVICE_TTL are defined with the other shared caches above.


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
        payload = {**advice, "timestamp": time.time()}
        db.document(_ADVICE_DOC).set(payload)
        _record_write(1)
        _cache_set(_ADVICE_CACHE, payload)
    except Exception as e:
        print(f"⚠️  save_bot2_advice: {e}")


def load_bot2_advice() -> dict:
    if db is None:
        return {}
    return _read_doc_dict(
        db.document(_ADVICE_DOC),
        label="load_bot2_advice",
        cache=_ADVICE_CACHE,
        ttl=ADVICE_TTL,
    )
def load_bot2_metrics() -> dict:
    if db is None:
        return {}
    return _read_doc_dict(
        db.collection(col("metrics")).document("latest"),
        label="load_bot2_metrics",
        cache=_METRICS_CACHE,
        ttl=BOT2_METRICS_TTL,
    )
# ── Daily budget report ───────────────────────────────────────────────────────

def load_commands_since(since_ms: int, limit: int = 10) -> list[dict]:
    """Load app commands newer than since_ms with quota accounting."""
    if db is None:
        return []

    allowed, current, limit_quota = _can_read(1)
    if not allowed:
        logging.debug("Skipping commands read: quota limit reached (%s/%s)",
                      current, limit_quota)
        return []

    try:
        snap = (
            db.collection(col("commands"))
            .where("timestamp_ms", ">", since_ms)
            .order_by("timestamp_ms")
            .limit(limit)
            .get()
        )
        commands = [{"id": d.id, **d.to_dict()} for d in snap]
        _record_read(max(1, len(commands)))
        return commands
    except Exception as exc:
        _handle_quota_error("load_commands_since", exc)
        return []


def daily_budget_report():
    """Estimate daily Firebase reads and writes against free-tier quota."""
    mode = "PERFORMANCE" if PERF_MODE else "CONSERVATIVE"
    ht = HISTORY_TTL
    wt = WEIGHTS_TTL
    cmd_poll = int(float(os.getenv("CMD_POLL_SEC", "30")))

    # History: HISTORY_LIMIT docs per cache miss, cache-aligned by all callers
    r_hist     = HISTORY_LIMIT * (86400 // ht)
    r_wgt      = 86400 // wt
    r_cfg      = 86400 // CONFIG_TTL
    r_advice   = 86400 // ADVICE_TTL
    r_metrics  = 86400 // BOT2_METRICS_TTL
    r_commands = 86400 // max(cmd_poll, 1)
    r_tot      = r_hist + r_wgt + r_cfg + r_advice + r_metrics + r_commands
    budget_ok  = "✅" if r_tot <= 45000 else "⚠️  OVER 45k TARGET"

    print(f"[Firebase] daily budget [{mode}]")
    print(f"   Reads : history       <= {r_hist:>6}/day  ({HISTORY_LIMIT} docs, cache {ht}s)")
    print(f"           weights       <= {r_wgt:>6}/day  (cache {wt}s)")
    print(f"           runtime cfg   <= {r_cfg:>6}/day  (cache {CONFIG_TTL}s)")
    print(f"           bot2 advice   <= {r_advice:>6}/day  (cache {ADVICE_TTL}s)")
    print(f"           bot2 metrics  <= {r_metrics:>6}/day  (cache {BOT2_METRICS_TTL}s)")
    print(f"           commands poll <= {r_commands:>6}/day  (poll {cmd_poll}s)")
    print(f"           total reads   ~= {r_tot:>6}/day  (target ≤45 000 / limit 50 000)  {budget_ok}")
    print("   Writes: metrics/latest every 300s =    288/day")
    print("           save_batch    every 60s   =  1 440/day")
    print("           save_last_trade (est.)    =    200/day")
    print("   Total : ~1 928 writes/day  (limit 20 000)  ✅")


# ════════════════════════════════════════════════════════════════════════════════
# HOTFIX (2026-04-26): Firebase quota recovery probe
# ════════════════════════════════════════════════════════════════════════════════

_LAST_RECOVERY_PROBE = 0  # Timestamp of last recovery probe
_RECOVERY_PROBE_COOLDOWN = 300  # Seconds between probes (5 minutes)

def probe_quota_recovered() -> bool:
    """
    Cheap Firebase recovery probe to detect when quota is restored.

    Uses exactly 1 read of a tiny config document to test Firebase access.
    Returns True only if read succeeds without 429/permission/network errors.

    Global cooldown prevents per-cycle probing spam.
    """
    global _LAST_RECOVERY_PROBE, db
    import time
    import logging as _log_probe

    now = time.time()

    # Cooldown check: only probe every 5 minutes
    if now - _LAST_RECOVERY_PROBE < _RECOVERY_PROBE_COOLDOWN:
        return False  # Not yet time to probe

    _LAST_RECOVERY_PROBE = now

    # Safety: if db not initialized, can't probe
    if db is None:
        _log_probe.warning("[RECOVERY_PROBE] Firebase not initialized, skipping probe")
        return False

    try:
        # Minimal read: fetch runtime config (tiny doc)
        # This tests read access without scanning trades/signals
        config_doc = db.collection(col("config")).document("runtime").get()

        # Success: Firebase is responding — clear degradation flags so writes resume
        _clear_firebase_degradation()
        _log_probe.info("[RECOVERY_PROBE] Firebase quota recovered; degradation flags cleared")
        return True

    except Exception as e:
        error_str = str(e)

        # Check if it's still a quota error
        if "429" in error_str or "quota" in error_str.lower():
            _log_probe.warning(f"[RECOVERY_PROBE] Still quota limited: {type(e).__name__}")
            return False

        # Check if it's a permission/auth error (don't recover for these)
        if "permission" in error_str.lower() or "denied" in error_str.lower():
            _log_probe.warning(f"[RECOVERY_PROBE] Permission denied (non-recoverable): {type(e).__name__}")
            return False

        # Check if it's a network error
        if "connection" in error_str.lower() or "timeout" in error_str.lower():
            _log_probe.warning(f"[RECOVERY_PROBE] Network error (retryable): {type(e).__name__}")
            return False

        # Unknown error: don't auto-recover
        _log_probe.warning(f"[RECOVERY_PROBE] Unknown error: {type(e).__name__}: {error_str[:100]}")
        return False
