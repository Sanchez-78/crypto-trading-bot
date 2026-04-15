# Claude Code Prompt — CryptoMaster V10.12i Final Stall/Idle Integration Patch

Apply an incremental patch to the existing Python trading bot project.

Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove protections unless explicitly stated.
Patch only the real active runtime integration points now proven by live logs and code search.

## GOAL

Fix the last confirmed active integration bugs that are still causing fake STALL/self-heal behavior and inconsistent Redis fallback.

The active runtime evidence now proves:

- `bot2/main.py` still contains:
  - `last_trade_ts = [0.0]`
  - raw watchdog checks like `if now - last_trade_ts[0] > 600`
  - raw watchdog checks like `if now - last_trade_ts[0] > 900`
- `signal_filter.py` still contains raw idle computation using `time.time() - ...`
- `state_manager.py` still needs full true-optional Redis behavior in all active paths

This means:
- the STALL bug is still alive in the active runtime path
- fake self-heal triggers still occur from invalid idle timestamps
- multiple modules are computing idle independently instead of using one safe path

---

## ROOT CAUSE SUMMARY

### 1. `bot2/main.py` is the primary source of fake STALL
It initializes:
```python
last_trade_ts = [0.0]
```

Then computes:
```python
now - last_trade_ts[0]
```

This causes:
- `time.time() - 0.0`
- giant unix-time-sized values
- immediate false STALL
- immediate false `SELF_HEAL: STALL`

### 2. `signal_filter.py` still uses raw idle arithmetic
This contaminates filtering / unblock behavior with the same bad timestamp assumptions.

### 3. `state_manager.py` still needs complete optional Redis behavior
`audit_worker.py` already has one-warning/backoff behavior, but `state_manager.py` still needs:
- cooldown disable window
- `_safe_client()`
- quiet cleanup failure
- no repeated noisy failures

---

## REQUIRED OUTCOME

After this patch:

1. No active runtime path may compute idle as `time.time() - 0.0`.
2. `STALL` logs must always be realistic.
3. `SELF_HEAL: STALL` must only fire on real inactivity.
4. `signal_filter.py` must use safe idle logic.
5. `state_manager.py` must degrade safely to in-memory mode without noisy repeated failures.
6. The bot must use one consistent stall/idle interpretation across main runtime paths.

---

# FILE 1 — PATCH `bot2/main.py`

## Objective
Fix the primary active STALL bug in the actual running watchdog path.

## Required changes

### A. Fix initialization
Find:
```python
last_trade_ts = [0.0]
```

Replace with one of:
```python
last_trade_ts = [time.time()]
```
or
```python
last_trade_ts = [None]
```

Choose the safer option based on surrounding architecture.
If code already imports `time as _time`, use `_time.time()` consistently.

### B. Add safe idle helper or import one
If practical and no circular import risk:
- import `safe_idle_seconds` from `src.services.realtime_decision_engine`

If that is risky or messy:
- add a local helper in `bot2/main.py` with the same semantics:

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
    if idle > 86400:
        return 0.0

    return idle
```

### C. Replace raw watchdog checks
Find all patterns like:
```python
if now - last_trade_ts[0] > 600:
```
and
```python
if now - last_trade_ts[0] > 900:
```

Replace with:
```python
idle_sec = safe_idle_seconds(last_trade_ts[0], now)
if idle_sec > 600:
    ...
if idle_sec > 900:
    ...
```

### D. Fix STALL logging
No log line should print giant unix-time-sized values.
Use:
```python
idle_sec = safe_idle_seconds(last_trade_ts[0], now)
```
for all STALL/self-heal logs.

### E. Keep behavior, fix triggers
Do NOT remove:
- watchdog checks
- boosting exploration
- reducing filter thresholds
- self-heal orchestration

Only fix:
- invalid timestamp handling
- idle calculation
- log correctness

---

# FILE 2 — PATCH `src/services/signal_filter.py`

## Objective
Remove remaining raw idle arithmetic from active filter logic.

## Required changes

### A. Find raw idle calculation
Your code search already showed raw time arithmetic around:
- line 116
- line 117

Patch any logic like:
```python
no_trades_sec = time.time() - last_trade_ts
```
or equivalent.

### B. Use safe helper
Either import from RDE:
```python
from src.services.realtime_decision_engine import safe_idle_seconds
```

Or add a local helper if circular dependency risk exists.

Then replace raw idle usage with:
```python
no_trades_sec = safe_idle_seconds(last_trade_ts)
```

### C. Preserve existing cooldown / unblock semantics
Do NOT redesign filtering.
Only remove invalid idle computation.

---

# FILE 3 — PATCH `src/services/state_manager.py`

## Objective
Finish true optional Redis mode for active state-manager paths.

## Required changes

### A. Add globals
Near client state add:

```python
_redis_client = None
_redis_disabled_until = 0.0
_redis_warned = False
```

### B. Add import
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

### E. Use `_safe_client()` where practical
Replace:
```python
r = await _get_client()
```
with:
```python
r = await _safe_client()
if r is None:
    return ...
```

Use correct fallback values:
- write ops → no-op
- read ops → empty dict/list/0/False/None depending on contract

### F. Quiet cleanup failure
Change:
```python
log.warning("clear_redis_state error: %s", exc)
```
to:
```python
log.debug("clear_redis_state skipped: %s", exc)
```

### G. Preserve semantics
Ensure:
- `clear_redis_state()` returns `0` when Redis unavailable
- `is_redis_available()` returns strict bool
- no Redis exception escapes into runtime

---

## CROSS-FILE RULES

1. Prefer one authoritative idle interpretation.
   Do not keep multiple raw `time.time() - last_trade_ts` paths alive.

2. Avoid circular imports.
   If importing `safe_idle_seconds` from RDE creates circular dependency risk,
   duplicate the helper locally in `bot2/main.py` and `signal_filter.py`.

3. Do not patch unrelated strategy logic.
   This is a runtime integration fix, not a strategy redesign.

4. Keep logs concise and reliable.
   Real STALL > fake STALL.

---

## ACCEPTANCE CRITERIA

The patch is successful only if all are true:

1. `bot2/main.py` no longer initializes active watchdog timestamp to `0.0`.
2. No active runtime watchdog path computes `now - 0.0`.
3. No log line shows STALL in unix-time-sized numbers.
4. `SELF_HEAL: STALL` only appears after real inactivity.
5. `signal_filter.py` no longer uses raw idle arithmetic.
6. Redis absence no longer causes repeated noisy state-manager failures.
7. Bot still starts and runs without Redis.
8. Existing protections remain intact.

---

## RETURN FORMAT

Return:
1. full code for each changed file:
   - `bot2/main.py`
   - `src/services/signal_filter.py`
   - `src/services/state_manager.py`
2. concise explanation per file
3. short root cause summary
4. short expected post-patch runtime behavior
5. any assumptions if real variable names differ

Do NOT return pseudo-code only.
Return real integrated Python code.
