# Claude Code Prompt — CryptoMaster V10.12h Final Integration Patch (adaptive_recovery + main + state_manager)

Apply an incremental patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove protections unless explicitly stated.
Patch only the real runtime integration points now proven to be active.

## GOAL

Fix the final runtime integration bugs that remain after V10.12g.

Evidence already established:
- `realtime_decision_engine.py` contains `safe_idle_seconds()`, `log_decision()`, `log_cycle_result()`
- but live runtime still shows:
  - `🚨 ANOMALY: STALL 1776256666s > 900s`
  - repeated `NO_SIGNALS`
  - `SELF_HEAL: STALL ...`
- therefore the real STALL / self-heal path is NOT using the patched RDE helper
- real integration points are now identified as:
  - `src/services/adaptive_recovery.py`
  - `bot2/main.py`
  - `src/services/state_manager.py`

Your task is to patch those three files so runtime behavior matches the intended V10.12g design.

---

## ROOT CAUSE SUMMARY

### 1. STALL bug is in active recovery path, not in RDE
`adaptive_recovery.py` contains the active `StallRecovery` logic and is logging STALL conditions directly.
It is still computing or accepting invalid idle durations, causing unix-time-sized values.

### 2. `bot2/main.py` is the active orchestration layer
It calls adaptive recovery, watchdog, and self-heal logic.
Even if RDE has safe helpers, main runtime still uses old recovery flow.

### 3. `state_manager.py` is still only partially optional
`audit_worker.py` already shows one-warning/backoff behavior, but `state_manager.py` still needs true optional Redis mode with cooldown + silent fallback.

---

## REQUIRED OUTCOME

After this patch:

1. `STALL` values are always realistic.
2. No unix-time-sized idle values can ever reach logs.
3. `SELF_HEAL: STALL` only fires on real inactivity.
4. `NO_SIGNALS` recovery logs remain, but are tied to valid cycle state.
5. Redis is truly optional across state_manager.
6. Runtime logs clearly show cycle-level health even if no candidates pass.

---

# FILE 1 — PATCH `src/services/adaptive_recovery.py`

## Objective
Make `StallRecovery` use safe idle computation.
No direct raw `time.time() - last_trade_ts` logic may remain in active stall detection.

## Required changes

### A. Add safe idle helper
If the file does not already have one, add:

```python
def safe_idle_seconds(last_trade_ts, now=None):
    import time as _time
    now = now or _time.time()

    if not last_trade_ts:
        return 0.0

    try:
        ts = float(last_trade_ts)
    except Exception:
        return 0.0

    if ts <= 0:
        return 0.0

    if ts > now:
        return 0.0

    idle = max(0.0, now - ts)

    # bug guard — unix-time-sized or corrupted values
    if idle > 86400:
        return 0.0

    return idle
```

### B. Patch `StallRecovery`
Find the real place where stall detection uses `no_trade_time`, `last_trade_ts`, or equivalent.

Current behavior likely resembles:
```python
if no_trade_time > self.stall_threshold:
    log.warning(f"🚨 STALL {no_trade_time}s > {self.stall_threshold}s")
```

Patch it so:
- `no_trade_time` is computed via `safe_idle_seconds(...)`
- invalid timestamps produce `0.0`
- STALL logging only happens when idle is valid and exceeds threshold

### C. Add log hygiene
If no valid timestamp exists, do NOT log fake STALL.
Optionally log at debug:
```python
log.debug("STALL check skipped: no valid last_trade_ts")
```

### D. Preserve existing recovery semantics
Do NOT remove:
- stall threshold logic
- recovery triggers
- exploration boost
- filter relaxation behavior

Only fix invalid idle computation and log accuracy.

---

# FILE 2 — PATCH `bot2/main.py`

## Objective
Make the active runtime orchestration use validated stall data and add cycle-level visibility.

## Required changes

### A. Ensure adaptive recovery uses safe idle result
Find the code around:
- watchdog
- `update_adaptive_recovery(...)`
- `stall_status = ...`
- `SELF_HEAL: STALL ...`
- `SELF_HEAL: NO_SIGNALS ...`

Patch so:
- STALL self-heal only fires if safe idle >= threshold
- not when timestamp is missing/zero/corrupt

### B. Add cycle-level no-candidate log if missing
If the active orchestration layer does not already print a cycle summary, add one authoritative log line such as:

```python
print(
    f"cycle_result={'no_candidate' if passed == 0 else 'has_candidate'} "
    f"symbols={symbols_count} passed={passed} "
    f"unblock={unblock_mode} idle={idle_sec:.1f} redis={'available' if redis_ok else 'unavailable'}"
)
```

Use the actual active variables from the runtime path.

### C. Prevent duplicate contradictory health logs
Do NOT allow:
- one layer to say STALL from invalid idle
- another layer to say idle is healthy

Main runtime should use one trusted idle value.

### D. Keep current self-heal behavior
Do NOT remove:
- boosting exploration
- reducing filter thresholds
- no-signal recovery
- existing watchdog checks

Only fix:
- when they fire
- what they log
- whether they use valid idle state

---

# FILE 3 — PATCH `src/services/state_manager.py`

## Objective
Finish true optional Redis mode.

## Required changes

### A. Add cooldown globals
Near Redis client state add:

```python
_redis_client = None
_redis_disabled_until = 0.0
_redis_warned = False
```

### B. Import time
Add:
```python
import time
```

### C. Replace `_get_client()` logic
Patch to:

```python
async def _get_client():
    global _redis_client, _redis_disabled_until, _redis_warned

    now = time.time()
    if now < _redis_disabled_until:
        raise RuntimeError("Redis temporarily disabled")

    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(
                REDIS_URL,
                socket_connect_timeout=1,
                socket_timeout=1,
                decode_responses=True,
            )
            await _redis_client.ping()
            _redis_warned = False
        except ImportError as e:
            raise RuntimeError("redis-py not installed. Run: pip install redis") from e
        except Exception as exc:
            _redis_client = None
            _redis_disabled_until = now + 60
            if not _redis_warned:
                log.warning("Redis unavailable; falling back to in-memory mode: %s", exc)
                _redis_warned = True
            raise

    return _redis_client
```

### D. Add `_safe_client()`
```python
async def _safe_client():
    try:
        return await _get_client()
    except Exception:
        return None
```

### E. Use `_safe_client()` in active Redis ops
Where practical, change:
```python
r = await _get_client()
```
to:
```python
r = await _safe_client()
if r is None:
    return ...
```

Use correct fallback:
- write ops → no-op
- read ops → `{}`, `[]`, `0`, `False`, or `None` depending on function contract

### F. Quiet down cleanup log
Change:
```python
log.warning("clear_redis_state error: %s", exc)
```
to:
```python
log.debug("clear_redis_state skipped: %s", exc)
```

### G. Preserve return semantics
Ensure:
- `clear_redis_state()` returns `0` on Redis absence
- `is_redis_available()` returns strict bool
- no Redis exception escapes into runtime

---

## CROSS-FILE INTEGRATION RULES

1. Do not patch `realtime_decision_engine.py` unless strictly necessary.
   The problem is not that the helper does not exist; it is that active runtime paths are not using the right logic.

2. If `adaptive_recovery.py` needs to import `safe_idle_seconds()` from RDE, that is acceptable.
   But avoid circular imports.
   If circular risk exists, duplicate the helper locally in `adaptive_recovery.py`.

3. `bot2/main.py` should use one authoritative idle value from the active recovery path.
   Do not compute raw idle in multiple places.

4. Keep logging concise but decisive.
   One real STALL log is better than many misleading ones.

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. Bot starts without Redis and does not crash.
2. Only first Redis failure is a warning; later retries are silent/debug.
3. No log line shows STALL values in unix-time-sized numbers.
4. STALL only appears after genuine inactivity above threshold.
5. `SELF_HEAL: STALL` only occurs when idle is real.
6. `NO_SIGNALS` logs still work, but are no longer contaminated by fake idle bug.
7. At least one cycle-level summary line exists showing candidate flow / no-candidate state.
8. State manager degrades safely to in-memory mode.

---

## RETURN FORMAT

Return:
1. full code for each changed file
   - `src/services/adaptive_recovery.py`
   - `bot2/main.py`
   - `src/services/state_manager.py`
2. concise explanation per file
3. short root cause summary
4. short post-patch expected runtime behavior
5. any assumptions if actual variable names differ

Do NOT return pseudo-code only.
Return real integrated Python code.
