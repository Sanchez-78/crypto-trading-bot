"""
state_manager.py — Redis State Persistence Layer (Phase 2 / Task 1)

Zero-loss cold-start architecture: all rolling ML metrics are flushed to
Redis on every update and re-hydrated from Redis on boot. A container
restart loses no accumulated learning data.

Data model
──────────
  learning_monitor state:
    KEY  "lm:ev_hist:{sym}:{reg}"       Redis LIST  (JSON floats, max 200)
    KEY  "lm:wr_hist:{sym}:{reg}"       Redis LIST  (JSON floats, max 200)
    KEY  "lm:pnl_hist:{sym}:{reg}"      Redis LIST  (JSON floats, max 200)
    KEY  "lm:bandit_hist:{sym}:{reg}"   Redis LIST  (JSON floats, max 200)
    KEY  "lm:count:{sym}:{reg}"         Redis STRING (int)
    KEY  "lm:sym_pnl:{sym}"             Redis LIST  (JSON floats, max 8)
    KEY  "lm:feature_stats"             Redis HASH  field=name val=JSON[w,t]

  realtime_decision_engine state:
    KEY  "rde:ev_history"               Redis LIST  (JSON floats, max 200)
    KEY  "rde:score_history"            Redis LIST  (JSON floats, max 200)
    KEY  "rde:combo_stats"              Redis HASH  field=combo val=JSON[wins,total]
    KEY  "rde:calibrator"               Redis HASH  field=bucket val=JSON[wins,total]
    KEY  "rde:edge_stats"               Redis HASH  field=key val=JSON[wins,total]

  learning_event (METRICS) state:
    KEY  "le:metrics"                   Redis STRING (JSON dict)
    KEY  "le:close_reasons"             Redis HASH
    KEY  "le:regime_stats"              Redis HASH  field=regime val=JSON{wins,trades}

Design principles:
  - All Redis I/O is async (redis.asyncio).
  - Synchronous shim (flush_sync / hydrate_sync) wraps asyncio.run() for
    callers that live in synchronous context (learning_monitor.lm_update,
    trade_executor.on_price). Thread-safe: asyncio.run() creates a fresh
    event loop per call — no conflict with the sync trading engine.
  - Maximum list length is enforced via LTRIM after every LPUSH.
  - Redis unavailability is fully tolerated: all functions swallow
    ConnectionError / ResponseError and return empty defaults so the
    system degrades gracefully to in-memory-only mode.
  - TTL=0 (no expiry) for persistent learning state. Adjust per ops policy.

Usage from learning_monitor:
    from src.services.state_manager import flush_lm_update, hydrate_lm

Usage from realtime_decision_engine:
    from src.services.state_manager import flush_rde_state, hydrate_rde_state

Usage from learning_event:
    from src.services.state_manager import flush_metrics, hydrate_metrics
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from typing import Any

log = logging.getLogger(__name__)

# ── Connection settings ────────────────────────────────────────────────────────

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# List length caps — mirror the in-memory caps in each module
_LIST_CAP = 200
_SYM_PNL_CAP = 8

# ── Lazy async client with cooldown window (V10.13n) ────────────────────────────
# FIXED: Event loop binding issue - create fresh client per call instead of persistent global
# Previous bug: _redis_client module variable created in one event loop, reused across
# multiple asyncio.run() calls that created new loops, causing "Event loop is closed" errors

_redis_disabled_until: float = 0.0      # timestamp when cooldown expires
_redis_warned: bool = False             # flag to log warning only once per cooldown


async def _get_client() -> Any:
    """
    Create and return a fresh async Redis client bound to the current event loop.
    
    V10.13n: FIXED - Client is created fresh on each call (not cached) to ensure
    it's always bound to the currently running event loop. This prevents
    "RuntimeError: Event loop is closed" when asyncio.run() creates new loops.
    
    V10.12g: After connection failure, Redis enters 60-second cooldown window.
    During cooldown, raises RuntimeError immediately without retry overhead.
    This prevents connection spam and allows graceful degradation.
    """
    global _redis_disabled_until, _redis_warned
    
    now = _time.time()
    
    # If cooldown active, reject immediately without trying
    if now < _redis_disabled_until:
        raise RuntimeError("Redis temporarily disabled (cooldown window active)")
    
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        client = aioredis.from_url(
            REDIS_URL,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        await client.ping()
        _redis_warned = False  # Reset warning flag on successful connection
        return client
    except ImportError as e:
        raise RuntimeError(
            "redis-py not installed. Run: pip install redis") from e
    except Exception as exc:
        # Connection failed: enter cooldown window
        _redis_disabled_until = now + 60  # 60-second cooldown
        
        # Log warning only on first failure, then silent for remaining cooldown
        if not _redis_warned:
            log.warning("Redis unavailable; falling back to in-memory mode: %s", exc)
            _redis_warned = True
        raise


async def _safe_client() -> Any | None:
    """
    V10.12g: Attempt to get Redis client; return None if unavailable.
    
    Used by all async Redis operations to enable graceful degradation
    when Redis is unreachable.
    """
    try:
        return await _get_client()
    except Exception:
        return None
def _run(coro: Any) -> Any:
    """Run a coroutine in a fresh event loop (sync shim, thread-safe)."""
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(coro)
    except Exception as exc:
        log.debug("state_manager._run error: %s", exc)
        return None
    finally:
        try:
            loop.close()
        except Exception:
            pass


# ── Internal async helpers ─────────────────────────────────────────────────────

async def _lpush_capped(r: Any, key: str, values: list[float], cap: int) -> None:
    """Push a fresh list atomically — delete old key, push all, trim."""
    pipe = r.pipeline()
    pipe.delete(key)
    for v in values[-cap:]:
        pipe.rpush(key, json.dumps(v))
    await pipe.execute()


async def _lrange_floats(r: Any, key: str) -> list[float]:
    """Fetch an entire Redis LIST as a Python list of floats."""
    raw: list[str] = await r.lrange(key, 0, -1)
    result = []
    for item in raw:
        try:
            result.append(float(json.loads(item)))
        except (json.JSONDecodeError, ValueError):
            pass
    return result


async def _hset_json(r: Any, hash_key: str, field: str, value: Any) -> None:
    await r.hset(hash_key, field, json.dumps(value))


async def _hgetall_json(r: Any, hash_key: str) -> dict[str, Any]:
    raw = await r.hgetall(hash_key)
    out: dict[str, Any] = {}
    for k, v in raw.items():
        try:
            out[k] = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            pass
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Task 1A — learning_monitor persistence
# ══════════════════════════════════════════════════════════════════════════════

async def _async_flush_lm_update(
    sym: str,
    reg: str,
    pnl_hist: list[float],
    wr_hist: list[float],
    ev_hist: list[float],
    bandit_hist: list[float],
    count: int,
    sym_pnl: list[float],
    feature_stats: dict[str, tuple[float, float]],
) -> None:
    """Persist all learning_monitor state after a single lm_update() call.

    V10.12i: Gracefully skip if Redis unavailable (no-op write).
    """
    log.debug(f"[FLUSH_LM_START] {sym}/{reg} count={count} pnl_len={len(pnl_hist)} wr_len={len(wr_hist)} ev_len={len(ev_hist)}")
    try:
        # V10.12i: Use safe client for graceful Redis absence
        r = await _safe_client()
        if r is None:
            log.warning(f"[FLUSH_LM_REDIS_NONE] {sym}/{reg} - Redis client is None, data LOST")
            return  # Redis unavailable; skip write silently
        pipe = r.pipeline()

        # Per-(sym, reg) lists — push fresh snapshot
        async def _push(suffix: str, lst: list[float], cap: int) -> None:
            key = f"lm:{suffix}:{sym}:{reg}"
            await _lpush_capped(r, key, lst, cap)

        await _push("pnl_hist",    pnl_hist,    _LIST_CAP)
        await _push("wr_hist",     wr_hist,     _LIST_CAP)
        await _push("ev_hist",     ev_hist,     _LIST_CAP)
        await _push("bandit_hist", bandit_hist, _LIST_CAP)

        # Count as plain string
        await r.set(f"lm:count:{sym}:{reg}", str(count))

        # Per-symbol recent PnL
        sym_key = f"lm:sym_pnl:{sym}"
        await _lpush_capped(r, sym_key, sym_pnl, _SYM_PNL_CAP)

        # Feature stats HASH  field=name  val=JSON[w, t]
        for fname, (w, t) in feature_stats.items():
            await r.hset("lm:feature_stats", fname, json.dumps([w, t]))
        
        log.debug(f"[FLUSH_LM_OK] {sym}/{reg} wrote count={count} to Redis")

    except Exception as exc:
        log.error(f"[FLUSH_LM_ERROR] {sym}/{reg}: {type(exc).__name__}: {exc}", exc_info=True)


def flush_lm_update(
    sym: str,
    reg: str,
    pnl_hist: list[float],
    wr_hist: list[float],
    ev_hist: list[float],
    bandit_hist: list[float],
    count: int,
    sym_pnl: list[float],
    feature_stats: dict[str, tuple[float, float]],
) -> None:
    """Synchronous shim — call from learning_monitor.lm_update() after state update."""
    _run(_async_flush_lm_update(
        sym, reg, pnl_hist, wr_hist, ev_hist, bandit_hist,
        count, sym_pnl, feature_stats,
    ))


async def _async_hydrate_lm() -> dict[str, Any]:
    """
    Re-hydrate all learning_monitor dicts from Redis on boot.
    Returns a dict with keys matching the module-level variables:
      {
        "lm_pnl_hist":    {(sym, reg): [float, ...]},
        "lm_wr_hist":     {(sym, reg): [float, ...]},
        "lm_ev_hist":     {(sym, reg): [float, ...]},
        "lm_bandit_hist": {(sym, reg): [float, ...]},
        "lm_count":       {(sym, reg): int},
        "sym_recent_pnl": {sym: [float, ...]},
        "lm_feature_stats": {name: (w, t)},
      }

    V10.12i: Return empty dict if Redis unavailable.
    """
    log.debug("[HYDRATE_LM_START] Starting learning state hydration from Redis")
    empty: dict[str, Any] = {
        "lm_pnl_hist": {}, "lm_wr_hist": {}, "lm_ev_hist": {},
        "lm_bandit_hist": {}, "lm_count": {}, "sym_recent_pnl": {},
        "lm_feature_stats": {},
    }
    try:
        # V10.12i: Use safe client for graceful fallback
        r = await _safe_client()
        if r is None:
            return empty

        # Scan for all lm:pnl_hist:* keys to discover which (sym, reg) pairs exist
        cursor: int = 0
        pair_keys: list[str] = []
        while True:
            cursor, batch = await r.scan(cursor, match="lm:pnl_hist:*", count=200)
            pair_keys.extend(batch)
            if cursor == 0:
                break

        for key in pair_keys:
            # key format: "lm:pnl_hist:{sym}:{reg}"
            parts = key.split(":", 3)
            if len(parts) != 4:
                continue
            sym, reg = parts[2], parts[3]
            pair = (sym, reg)

            empty["lm_pnl_hist"][pair]    = await _lrange_floats(r, f"lm:pnl_hist:{sym}:{reg}")
            empty["lm_wr_hist"][pair]     = await _lrange_floats(r, f"lm:wr_hist:{sym}:{reg}")
            empty["lm_ev_hist"][pair]     = await _lrange_floats(r, f"lm:ev_hist:{sym}:{reg}")
            empty["lm_bandit_hist"][pair] = await _lrange_floats(r, f"lm:bandit_hist:{sym}:{reg}")

            cnt_raw = await r.get(f"lm:count:{sym}:{reg}")
            empty["lm_count"][pair] = int(cnt_raw) if cnt_raw else 0

        # sym_recent_pnl
        cursor = 0
        while True:
            cursor, batch = await r.scan(cursor, match="lm:sym_pnl:*", count=200)
            for key in batch:
                sym = key.split(":", 2)[-1]
                empty["sym_recent_pnl"][sym] = await _lrange_floats(r, key)
            if cursor == 0:
                break

        # Feature stats
        fs_raw = await _hgetall_json(r, "lm:feature_stats")
        for name, val in fs_raw.items():
            if isinstance(val, list) and len(val) == 2:
                empty["lm_feature_stats"][name] = (float(val[0]), float(val[1]))
        
        n_pairs = len(empty["lm_count"])
        n_features = len(empty["lm_feature_stats"])
        log.debug(f"[HYDRATE_LM_OK] Loaded pairs={n_pairs} features={n_features} trades={sum(empty['lm_count'].values())}")

    except Exception as exc:
        log.error(f"[HYDRATE_LM_ERROR] {type(exc).__name__}: {exc}", exc_info=True)

    return empty


def hydrate_lm() -> dict[str, Any]:
    """Synchronous shim — call at module import time in learning_monitor.py."""
    return _run(_async_hydrate_lm()) or {}


# ══════════════════════════════════════════════════════════════════════════════
# Task 1B — realtime_decision_engine persistence
# ══════════════════════════════════════════════════════════════════════════════

async def _async_flush_rde_state(
    ev_history: list[float],
    score_history: list[float],
    combo_stats: dict[str, list[int]],
    calibrator_buckets: dict[float, list[int]],
    edge_stats: dict[str, list[int]],
) -> None:
    """Persist RDE state after calibrator/edge update.

    V10.12i: Gracefully skip if Redis unavailable (no-op write).
    """
    try:
        # V10.12i: Use safe client for graceful Redis absence
        r = await _safe_client()
        if r is None:
            return  # Redis unavailable; skip write silently

        await _lpush_capped(r, "rde:ev_history",    ev_history,    _LIST_CAP)
        await _lpush_capped(r, "rde:score_history",  score_history, _LIST_CAP)

        for combo_key, val in combo_stats.items():
            await r.hset("rde:combo_stats", combo_key, json.dumps(val))

        for bucket, val in calibrator_buckets.items():
            await r.hset("rde:calibrator", str(bucket), json.dumps(val))

        for stat_key, val in edge_stats.items():
            await r.hset("rde:edge_stats", stat_key, json.dumps(val))

    except Exception as exc:
        log.debug("flush_rde_state error: %s", exc)


def flush_rde_state(
    ev_history: list[float],
    score_history: list[float],
    combo_stats: dict[str, list[int]],
    calibrator_buckets: dict[float, list[int]],
    edge_stats: dict[str, list[int]],
) -> None:
    """Synchronous shim — call from realtime_decision_engine after each calibrator update."""
    _run(_async_flush_rde_state(
        ev_history, score_history, combo_stats, calibrator_buckets, edge_stats,
    ))


async def _async_hydrate_rde_state() -> dict[str, Any]:
    """Re-hydrate RDE state on boot.

    V10.12i: Return empty dict if Redis unavailable.
    """
    empty: dict[str, Any] = {
        "ev_history": [], "score_history": [],
        "combo_stats": {}, "calibrator_buckets": {}, "edge_stats": {},
    }
    try:
        # V10.12i: Use safe client for graceful fallback
        r = await _safe_client()
        if r is None:
            return empty

        empty["ev_history"]    = await _lrange_floats(r, "rde:ev_history")
        empty["score_history"] = await _lrange_floats(r, "rde:score_history")

        for key, label in [
            ("rde:combo_stats",  "combo_stats"),
            ("rde:edge_stats",   "edge_stats"),
        ]:
            raw = await _hgetall_json(r, key)
            empty[label] = {k: v for k, v in raw.items() if isinstance(v, list)}

        cal_raw = await _hgetall_json(r, "rde:calibrator")
        empty["calibrator_buckets"] = {
            float(k): v for k, v in cal_raw.items() if isinstance(v, list)
        }

    except Exception as exc:
        log.debug("hydrate_rde_state error: %s", exc)

    return empty


def hydrate_rde_state() -> dict[str, Any]:
    """Synchronous shim — call at module import in realtime_decision_engine.py."""
    return _run(_async_hydrate_rde_state()) or {}


# ══════════════════════════════════════════════════════════════════════════════
# Task 1C — learning_event METRICS persistence
# ══════════════════════════════════════════════════════════════════════════════

async def _async_flush_metrics(
    metrics: dict[str, Any],
    close_reasons: dict[str, int],
    regime_stats: dict[str, dict[str, int]],
) -> None:
    """Persist METRICS dict + close_reasons + regime_stats to Redis.

    V10.12i: Gracefully skip if Redis unavailable (no-op write).
    """
    try:
        # V10.12i: Use safe client for graceful Redis absence
        r = await _safe_client()
        if r is None:
            return  # Redis unavailable; skip write silently

        # TTL=300s: le:metrics is Firestore-derived; bootstrap_from_history()
        # rebuilds it on cold start.  lm:* and rde:* keep TTL=0 (zero-loss).
        await r.set("le:metrics", json.dumps(metrics), ex=300)

        for reason, count in close_reasons.items():
            await r.hset("le:close_reasons", reason, str(count))

        for regime, stats in regime_stats.items():
            await r.hset("le:regime_stats", regime, json.dumps(stats))

    except Exception as exc:
        log.debug("flush_metrics error: %s", exc)


def flush_metrics(
    metrics: dict[str, Any],
    close_reasons: dict[str, int],
    regime_stats: dict[str, dict[str, int]],
) -> None:
    """Synchronous shim — call from learning_event after every trade close."""
    _run(_async_flush_metrics(metrics, close_reasons, regime_stats))


async def _async_hydrate_metrics() -> dict[str, Any]:
    """Re-hydrate METRICS + close_reasons + regime_stats on boot.

    V10.12i: Return empty dict if Redis unavailable.
    """
    empty: dict[str, Any] = {
        "metrics": {}, "close_reasons": {}, "regime_stats": {},
    }
    try:
        # V10.12i: Use safe client for graceful fallback
        r = await _safe_client()
        if r is None:
            return empty

        m_raw = await r.get("le:metrics")
        if m_raw:
            empty["metrics"] = json.loads(m_raw)

        cr_raw = await r.hgetall("le:close_reasons")
        empty["close_reasons"] = {k: int(v) for k, v in cr_raw.items()}

        rs_raw = await _hgetall_json(r, "le:regime_stats")
        empty["regime_stats"] = {k: v for k, v in rs_raw.items()
                                  if isinstance(v, dict)}

    except Exception as exc:
        log.debug("hydrate_metrics error: %s", exc)

    return empty


def hydrate_metrics() -> dict[str, Any]:
    """Synchronous shim — call at module import in learning_event.py."""
    return _run(_async_hydrate_metrics()) or {}


# ══════════════════════════════════════════════════════════════════════════════
# V10.14.b — Generic Redis-as-cache with Firestore fallback
# ══════════════════════════════════════════════════════════════════════════════

async def _async_get_cached(key: str, ttl: int, fetch_fn: Any) -> Any:
    """
    Check Redis for *key*; on miss call fetch_fn() and cache the result for
    *ttl* seconds.  Redis unavailability is fully tolerated — falls through
    to fetch_fn every time.

    V10.12i: Use safe client for consistent non-fatal Redis handling.
    """
    # V10.12i: Try Redis read (safe, non-fatal on failure)
    try:
        r = await _safe_client()
        if r is not None:
            raw = await r.get(key)
            if raw is not None:
                return json.loads(raw)
    except Exception as exc:
        log.debug("get_cached Redis read error: %s", exc)

    # Cache miss or Redis unavailable
    try:
        result = fetch_fn()
        if result is not None:
            try:
                # V10.12i: Try Redis write (safe, non-fatal on failure)
                r = await _safe_client()
                if r is not None:
                    await r.set(key, json.dumps(result), ex=ttl)
            except Exception as exc:
                log.debug("get_cached Redis write error: %s", exc)
        return result
    except Exception as exc:
        log.debug("get_cached fetch_fn error: %s", exc)
        return None


def get_cached(key: str, ttl: int, fetch_fn: Any) -> Any:
    """
    Synchronous shim for _async_get_cached.

    Usage:
        data = get_cached("my:key", 300, lambda: fetch_from_firestore())

    Returns the cached (or freshly fetched) value, or None on total failure.
    TTL is in seconds; use 0 for no expiry (though prefer flush_* helpers for
    persistent learning state).
    """
    return _run(_async_get_cached(key, ttl, fetch_fn))


# ══════════════════════════════════════════════════════════════════════════════
# Health check
# ══════════════════════════════════════════════════════════════════════════════

async def _async_clear_redis_state() -> int:
    """Delete all lm:*, rde:*, le:* keys from Redis. Returns count deleted.

    V10.12i: Return 0 if Redis unavailable (graceful skip).
    """
    deleted = 0
    try:
        # V10.12i: Use safe client for graceful fallback
        r = await _safe_client()
        if r is None:
            return 0  # Redis unavailable; return 0 deleted

        for pattern in ("lm:*", "rde:*", "le:*"):
            cursor: int = 0
            while True:
                cursor, keys = await r.scan(cursor, match=pattern, count=200)
                if keys:
                    await r.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
    except Exception as exc:
        log.debug("clear_redis_state skipped: %s", exc)
    return deleted


def clear_redis_state() -> int:
    """
    Wipe all learning state from Redis (lm:*, rde:*, le:*).
    Call before reset_db.reset_firestore() for a full cold-start reset.
    Returns count of deleted keys.
    """
    result = _run(_async_clear_redis_state())
    return int(result) if result else 0


async def _async_ping() -> bool:
    try:
        r = await _get_client()
        return await r.ping()
    except Exception:
        return False


def is_redis_available() -> bool:
    """Returns True if Redis is reachable. Used for graceful degradation."""
    result = _run(_async_ping())
    return bool(result)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4 Task 3 — Defense efficiency counters
# ══════════════════════════════════════════════════════════════════════════════
# Tracks two independent rejection events:
#   "exec:l2_rejected"    — signals killed at entry by L2 wall gate (signal_engine)
#   "exec:corr_rejected"  — signals killed at entry by Correlation Shield (execution_engine)
#
# close_reasons (wall_exit, timeout) are already persisted via flush_metrics()
# in learning_event.py.  l2_rejected is a separate counter because it lives in
# signal_engine.py (never touches a trade document).

async def _async_increment_l2_rejected() -> None:
    """Atomically increment L2 rejection counter.

    V10.12i: Gracefully skip if Redis unavailable.
    """
    try:
        r = await _safe_client()
        if r is not None:
            await r.incr("exec:l2_rejected")
    except Exception as exc:
        log.debug("increment_l2_rejected error: %s", exc)


def increment_l2_rejected() -> None:
    """
    Atomically increment the L2 rejection counter in Redis.
    Called from signal_engine._sync_evaluate on each REJECTED_L2_WALL event.
    Sync shim — non-blocking (runs in fresh event loop).
    """
    _run(_async_increment_l2_rejected())


async def _async_get_l2_rejected() -> int:
    """Get L2 rejection counter.

    V10.12i: Return 0 if Redis unavailable.
    """
    try:
        r = await _safe_client()
        if r is None:
            return 0
        val = await r.get("exec:l2_rejected")
        return int(val) if val else 0
    except Exception:
        return 0


def get_l2_rejected() -> int:
    """Return the total number of L2-rejected signals since last Redis reset."""
    result = _run(_async_get_l2_rejected())
    return int(result) if result else 0


async def _async_increment_corr_rejected() -> None:
    """Atomically increment CORR rejection counter.

    V10.12i: Gracefully skip if Redis unavailable.
    """
    try:
        r = await _safe_client()
        if r is not None:
            await r.incr("exec:corr_rejected")
    except Exception as exc:
        log.debug("increment_corr_rejected error: %s", exc)


def increment_corr_rejected() -> None:
    """
    Atomically increment the Correlation Shield rejection counter in Redis.
    Called from execution_engine._handle_signal on each REJECTED_CORR_SHIELD event.
    Sync shim — non-blocking (runs in fresh event loop).
    """
    _run(_async_increment_corr_rejected())


async def _async_get_corr_rejected() -> int:
    """Get CORR rejection counter.

    V10.12i: Return 0 if Redis unavailable.
    """
    try:
        r = await _safe_client()
        if r is None:
            return 0
        val = await r.get("exec:corr_rejected")
        return int(val) if val else 0
    except Exception:
        return 0


def get_corr_rejected() -> int:
    """Return the total number of correlation-rejected signals since last Redis reset."""
    result = _run(_async_get_corr_rejected())
    return int(result) if result else 0
