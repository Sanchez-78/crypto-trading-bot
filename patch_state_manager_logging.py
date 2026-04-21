#!/usr/bin/env python3
"""
Patch state_manager.py to add diagnostic logging for learning pipeline.
This will help us trace if data is being written to Redis and read back correctly.
"""

with open(r'C:\Projects\CryptoMaster_srv\src\services\state_manager.py', encoding='utf-8') as f:
    content = f.read()

# 1. Add logging at the START of _async_flush_lm_update
old1 = '''async def _async_flush_lm_update(
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
    try:
        # V10.12i: Use safe client for graceful Redis absence
        r = await _safe_client()
        if r is None:
            return  # Redis unavailable; skip write silently'''

new1 = '''async def _async_flush_lm_update(
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
            return  # Redis unavailable; skip write silently'''

content = content.replace(old1, new1)

# 2. Add logging AFTER successful writes (before except)
old2 = '''        for fname, (w, t) in feature_stats.items():
            await r.hset("lm:feature_stats", fname, json.dumps([w, t]))

    except Exception as exc:
        log.debug("flush_lm_update error: %s", exc)'''

new2 = '''        for fname, (w, t) in feature_stats.items():
            await r.hset("lm:feature_stats", fname, json.dumps([w, t]))
        
        log.debug(f"[FLUSH_LM_OK] {sym}/{reg} wrote count={count} to Redis")

    except Exception as exc:
        log.error(f"[FLUSH_LM_ERROR] {sym}/{reg}: {type(exc).__name__}: {exc}", exc_info=True)'''

content = content.replace(old2, new2)

# 3. Add logging at START of _async_hydrate_lm
old3 = '''async def _async_hydrate_lm() -> dict[str, Any]:
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
    empty: dict[str, Any] = {'''

new3 = '''async def _async_hydrate_lm() -> dict[str, Any]:
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
    empty: dict[str, Any] = {'''

content = content.replace(old3, new3)

# 4. Add logging at the end of _async_hydrate_lm
old4 = '''        for name, val in fs_raw.items():
            if isinstance(val, list) and len(val) == 2:
                empty["lm_feature_stats"][name] = (float(val[0]), float(val[1]))

    except Exception as exc:
        log.debug("hydrate_lm error: %s", exc)

    return empty'''

new4 = '''        for name, val in fs_raw.items():
            if isinstance(val, list) and len(val) == 2:
                empty["lm_feature_stats"][name] = (float(val[0]), float(val[1]))
        
        n_pairs = len(empty["lm_count"])
        n_features = len(empty["lm_feature_stats"])
        log.debug(f"[HYDRATE_LM_OK] Loaded pairs={n_pairs} features={n_features} trades={sum(empty['lm_count'].values())}")

    except Exception as exc:
        log.error(f"[HYDRATE_LM_ERROR] {type(exc).__name__}: {exc}", exc_info=True)

    return empty'''

content = content.replace(old4, new4)

# Write back
with open(r'C:\Projects\CryptoMaster_srv\src\services\state_manager.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("[OK] Patched state_manager.py with comprehensive logging")
print("  - Added [FLUSH_LM_START] and [FLUSH_LM_OK] logging")
print("  - Changed exception logging from debug to ERROR with exc_info")
print("  - Added [HYDRATE_LM_START] and [HYDRATE_LM_OK] logging")
print("  - Will now show Redis connection issues and counts")
