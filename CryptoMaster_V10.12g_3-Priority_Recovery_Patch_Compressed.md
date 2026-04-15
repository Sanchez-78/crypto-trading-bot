# Claude Code Prompt — CryptoMaster V10.12g / 3-Priority Recovery Patch (Compressed)

Apply an incremental patch to the existing Python trading bot project.
Do NOT rewrite the whole project.
Do NOT simplify architecture.
Do NOT remove protections unless explicitly stated below.
Patch the real integration points only.

## GOAL

Fix the 3 highest-priority runtime issues now present in the live bot:

### Priority 1 — Redis must become truly optional
Current behavior:
- Redis is unavailable on localhost:6379
- AuditWorker/state layer logs connection failures
- Redis should not spam logs or repeatedly reconnect every cycle
- System must degrade cleanly to in-memory / no-op mode

### Priority 2 — STALL / idle timestamp is wrong
Current behavior:
- `STALL 1776251170s > 900s`
- This indicates `last_trade_ts` or equivalent is 0 / invalid and idle is calculated as `time.time() - 0`
- Self-heal is firing immediately and misleading runtime diagnosis

### Priority 3 — Pipeline still stalls on no-signal loops
Current behavior:
- repeated `NO_SIGNALS`
- thresholds are being reduced repeatedly
- bot still needs a reliable observable final decision path
- after fixing idle bug, signal/debug visibility must be strong enough to show where candidates die

---

## REQUIRED OUTCOME

After this patch:
1. Redis failures are non-fatal and mostly silent after first warning.
2. Idle time is correct and never explodes to unix-time-sized numbers.
3. Self-heal only activates from real inactivity, not cold-start timestamp bugs.
4. Final signal/deadlock path is visible in logs.
5. Bot can continue operating without Redis.

---

# PRIORITY 1 — REDIS OPTIONAL MODE

## Patch `state_manager.py`

Keep Redis support, but convert it into true optional cache mode.

### Required behavior
- On first Redis connection failure:
  - log one warning
  - disable Redis temporarily for a cooldown window (e.g. 60s)
- During cooldown:
  - skip Redis operations immediately
  - return safe defaults
- When Redis comes back later:
  - allow retry after cooldown
- No repeated warning spam every cycle

### Apply this pattern

Add:
```python
import time
```

Add globals near client state:
```python
_redis_client = None
_redis_disabled_until = 0.0
_redis_warned = False
```

Replace `_get_client()` with logic equivalent to:
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

Add safe helper:
```python
async def _safe_client():
    try:
        return await _get_client()
    except Exception:
        return None
```

Then in Redis async functions, prefer:
```python
r = await _safe_client()
if r is None:
    return ...
```

Use correct fallback values:
- write ops: return None / no-op
- read ops: return empty dict/list/0/False as appropriate

### Logging rules
- only first Redis failure should be `warning`
- later failures during cooldown should be silent or debug
- `clear_redis_state()` must not warn loudly if Redis is absent

Change:
```python
log.warning("clear_redis_state error: %s", exc)
```
to:
```python
log.debug("clear_redis_state skipped: %s", exc)
```

### Return semantics
Ensure:
- `clear_redis_state()` returns integer deleted count or 0
- `is_redis_available()` returns strict bool
- no exception bubbles up to bot runtime

---

# PRIORITY 2 — FIX STALL / IDLE TIMESTAMP

Find the real code that computes:
- stall seconds
- no-trade duration
- `last_trade_ts`
- watchdog idle checks
- self-heal trigger

Current bug strongly suggests logic like:
```python
idle = time.time() - last_trade_ts
```
while `last_trade_ts == 0`.

## Required behavior
- idle seconds must never be computed from an invalid/zero timestamp
- cold start must not look like “900 seconds idle”
- watchdog should start from a safe baseline

### Patch pattern
Use logic equivalent to:

```python
def safe_idle_seconds(last_trade_ts: float | int | None, now: float | None = None) -> float:
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

    return max(0.0, now - ts)
```

Then replace direct idle computations with this helper.

### On cold boot
If the project initializes metrics/state on startup and no trade exists yet, either:
- keep `last_trade_ts = None` and idle = 0
or
- initialize `last_trade_ts = time.time()` at boot if that fits architecture better

Do NOT leave it as 0 if watchdog reads it as real inactivity.

### Logging fix
Current giant values like:
- `STALL 1776251170s`

must become realistic values only.
If no valid last trade timestamp exists, log either:
- no stall
or
- `STALL skipped: no valid last_trade_ts`

### Self-heal behavior
Self-heal must only run when:
- safe idle seconds >= threshold
not when timestamp is missing.

---

# PRIORITY 3 — FINAL NO-SIGNAL / DECISION VISIBILITY

After fixing idle and Redis, improve the final decision visibility so deadlocks are diagnosable.

Do NOT redesign strategy here unless necessary.
Focus on one authoritative final decision log line.

Find the real final candidate decision point and log:

- symbol
- regime
- unblock mode
- raw EV
- adjusted EV
- raw score
- adjusted score
- score threshold used
- EV threshold used
- timing penalty
- OFI penalty / size multiplier
- cooldown remaining
- fallback considered
- fallback used
- anti_deadlock used
- final decision reason

Example style:
```python
log.info(
    "decision=%s sym=%s reg=%s unblock=%s ev=%.4f->%.4f score=%.4f->%.4f "
    "thr_ev=%.4f thr_sc=%.4f timing=%.2f ofi=%.2f cooldown=%.1f "
    "fallback_considered=%s fallback_used=%s anti_deadlock=%s size=%.2f",
    decision, sym, reg, unblock, raw_ev, ev, raw_score, score,
    ev_thr, sc_thr, timing_mult, ofi_mult, cooldown_remaining,
    fallback_considered, fallback_used, anti_deadlock, size_mult,
)
```

### Required
- only one authoritative final decision line per evaluated candidate
- no noisy duplicate contradictory logs
- if there are zero real candidates, log that explicitly too:
```python
log.info("cycle_result=no_candidate symbols=%d unblock=%s idle=%.1f", n_symbols, unblock, idle_sec)
```

### Also fix dashboard/status display
If dashboard prints things like:
- `EV prah 0.000`
but actual threshold is different, correct it.

Status output should reflect real runtime values:
- current EV threshold
- current score threshold
- unblock mode active/inactive
- safe idle seconds
- Redis available yes/no

---

# IMPLEMENTATION NOTES

## Patch real files, likely including:
- `state_manager.py`
- watchdog / self-heal file
- metrics / anomaly file
- realtime decision engine
- status/dashboard output file
- possibly AuditWorker init if it directly pings Redis

## Keep these safety properties
Do NOT remove:
- RR validation
- spread hard checks
- exposure limits
- rate limits
- core risk guards

Redis may be skipped.
Risk must not be skipped.

---

# ACCEPTANCE CRITERIA

Implementation is successful only if all are true:

1. Bot starts with Redis absent and does not crash.
2. Only first Redis failure is a warning; later retries are silent/debug.
3. `STALL` no longer shows unix-time-sized numbers.
4. Self-heal only triggers from real inactivity.
5. Final decision logs make clear why signals are accepted/rejected.
6. Status output reflects true thresholds and Redis availability.

---

# RETURN FORMAT

Return:
1. full code for every changed file
2. concise explanation per file
3. root cause summary for each of the 3 priorities
4. exact behavior changes after patch
5. any assumptions if real code names differ

Do NOT return pseudo-code only.
Return real integrated Python code.
