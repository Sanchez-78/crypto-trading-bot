# Patch 3: Firebase Retry Queue Heartbeat — Patch Plan (REVISED)

**Status**: ANALYSIS ONLY. No implementation yet. Pending user approval.

**Date**: 2026-04-25 (Revised per feedback)

**Goal**: Design safe, re-entry-proof heartbeat/auto-flush mechanism for `_RETRY_QUEUE` with explicit locking, conservative backoff on failures only, and comprehensive validation.

---

## Corrections Applied (vs Original Plan)

| # | Original | Revised |
|---|----------|---------|
| 1 | Direct save_batch() call from heartbeat | Three-tier: _enqueue_retry, _drain_retry_queue, _write_batches_direct |
| 2 | Lock strategy vague | Explicit: lock only during queue ops, not I/O |
| 3 | Backoff on empty queue | Backoff only on write failure/quota/exception |
| 4 | 200-item batches | 100-item batches (conservative default) |
| 5 | 30-second interval | 60-second interval (lower Firebase pressure) |
| 6 | Idempotent via flag | Flag + no-op return if already running |
| 7 | Daemon only | Daemon + threading.Event for graceful stop |
| 8 | All heartbeats logged | Log success if drained > 0, rate-limit to 60s |
| 9 | Vague on drop policy | Truncate to _MAX_RETRY_SIZE on overflow, log critical |
| 10 | No validation tests | Detailed validation commands for all invariants |

---

## Architecture: Three-Tier Separation

```
save_batch(new_trades)
  ├─ Drain retry queue via _drain_retry_queue()
  ├─ Call _write_batches_direct(batch, source="normal")
  │   ├─ Write to Firebase (async thread)
  │   └─ On failure: re-enqueue via _enqueue_retry()
  └─ Return count

Heartbeat Thread
  ├─ _heartbeat_loop() — infinite loop, sleep configurable
  │   └─ _heartbeat_step()
  │       ├─ _drain_retry_queue(max=RETRY_HEARTBEAT_MAX_BATCH)
  │       ├─ _write_batches_direct(batch, source="heartbeat")
  │       │   └─ On failure: re-enqueue via _enqueue_retry()
  │       └─ Backoff only on failure, log if success
  └─ Never calls save_batch() (no recursion risk)
```

**Key**: `_write_batches_direct` is the ONLY place that writes to Firebase.

---

## Module-Level Configuration

```python
# User-tunable constants
RETRY_HEARTBEAT_INTERVAL_SEC = 60      # heartbeat sleep interval
RETRY_HEARTBEAT_MAX_BATCH = 100        # max items per heartbeat flush
RETRY_HEARTBEAT_BACKOFF_MAX_SEC = 900  # max backoff (seconds)

# State (protected by _RETRY_QUEUE_LOCK)
_RETRY_QUEUE = []                       # existing: queued trades
_RETRY_QUEUE_LOCK = threading.Lock()    # NEW: guards queue access
_HEARTBEAT_RUNNING = False              # NEW: prevents duplicate threads
_HEARTBEAT_STOP = threading.Event()     # NEW: graceful shutdown signal
_HEARTBEAT_CONSECUTIVE_FAILURES = 0     # NEW: failure counter for backoff
_HEARTBEAT_LAST_LOG_TS = 0              # NEW: rate-limit logging
```

---

## New Helper Function Signatures

### 1. `_enqueue_retry(items: list, reason: str) -> None`

**Purpose**: Atomically add items to retry queue on failure.

**Lock behavior**: Held during list operations only.

**Pseudocode**:
```python
def _enqueue_retry(items: list, reason: str) -> None:
    with _RETRY_QUEUE_LOCK:
        _RETRY_QUEUE.extend(items)
        if len(_RETRY_QUEUE) > _MAX_RETRY_SIZE:
            dropped = len(_RETRY_QUEUE) - _MAX_RETRY_SIZE
            _RETRY_QUEUE[:] = _RETRY_QUEUE[-_MAX_RETRY_SIZE:]  # keep newest
            logging.critical(
                f"⚠️  Retry queue overflow (reason={reason}): "
                f"dropped {dropped} oldest items (limit={_MAX_RETRY_SIZE})"
            )
```

---

### 2. `_drain_retry_queue(max_items: int) -> list`

**Purpose**: Atomically remove and return up to max_items from queue.

**Lock behavior**: Held only during list slice/assignment.

**Pseudocode**:
```python
def _drain_retry_queue(max_items: int) -> list:
    with _RETRY_QUEUE_LOCK:
        if not _RETRY_QUEUE:
            return []
        to_drain = _RETRY_QUEUE[:max_items]
        _RETRY_QUEUE[:] = _RETRY_QUEUE[max_items:]
        return to_drain
```

---

### 3. `_write_batches_direct(items: list, source: str) -> bool`

**Purpose**: Write items to Firebase without touching _RETRY_QUEUE except via _enqueue_retry on failure.

**Lock behavior**: No lock during Firebase I/O; calls _enqueue_retry which acquires lock.

**Pseudocode**:
```python
def _write_batches_direct(items: list, source: str) -> bool:
    """
    source = "normal" (from save_batch) or "heartbeat" (from heartbeat)
    Returns: True if write succeeded, False if failed
    """
    if not db or not items:
        return True
    
    try:
        slimmed = [_slim_trade(t) for t in items]
        
        # Quota check (existing code)
        allowed, current, limit = _can_write(len(slimmed))
        if not allowed:
            logging.warning(f"[{source}] quota limit approaching ({current}/{limit}) — requeuing")
            _enqueue_retry(items, f"{source}:quota_limit")
            return False
        
        # Update local history cache (existing code)
        cache_limit = max(HISTORY_LIMIT, _HISTORY_CACHE.get("limit", 0) or HISTORY_LIMIT)
        _HISTORY_CACHE["data"] = (slimmed + _HISTORY_CACHE["data"])[:cache_limit]
        _HISTORY_CACHE["ts"] = time.time()
        _HISTORY_CACHE["limit"] = cache_limit
        
        # Async Firebase write (existing code)
        threading.Thread(
            target=_async_firebase_write,
            args=(slimmed, len(slimmed)),
            daemon=True
        ).start()
        
        _record_write(len(slimmed))
        return True
    
    except Exception as e:
        if "429" in str(e) or "Quota" in str(e):
            _mark_quota_exhausted(str(e))
        logging.error(f"[{source}] write failed: {safe_log_exception(e)} — requeuing")
        _enqueue_retry(items, f"{source}:exception")
        return False
```

---

### 4. `_heartbeat_step() -> int`

**Purpose**: Single heartbeat iteration.

**Returns**: Number of items written (0 if queue empty or write failed).

**Behavior**: Backoff only on failure, not on empty queue.

**Pseudocode**:
```python
def _heartbeat_step() -> int:
    global _HEARTBEAT_CONSECUTIVE_FAILURES, _HEARTBEAT_LAST_LOG_TS
    
    # Drain up to max
    batch = _drain_retry_queue(RETRY_HEARTBEAT_MAX_BATCH)
    
    if not batch:
        # Queue empty — sleep normal interval, no backoff, no log
        return 0
    
    # Try to write
    success = _write_batches_direct(batch, source="heartbeat")
    
    if success:
        # Reset failure counter
        _HEARTBEAT_CONSECUTIVE_FAILURES = 0
        
        # Log if rate-limit allows (every 60s)
        now = time.time()
        if now - _HEARTBEAT_LAST_LOG_TS >= 60:
            with _RETRY_QUEUE_LOCK:
                queue_len = len(_RETRY_QUEUE)
            logging.info(
                f"[HEARTBEAT] flushed {len(batch)}/{queue_len} items from retry queue"
            )
            _HEARTBEAT_LAST_LOG_TS = now
        
        return len(batch)
    else:
        # Write failed — increment failure counter (affects backoff in loop)
        _HEARTBEAT_CONSECUTIVE_FAILURES += 1
        logging.warning(
            f"[HEARTBEAT] write failed (consecutive_failures={_HEARTBEAT_CONSECUTIVE_FAILURES})"
        )
        return 0
```

---

### 5. `_heartbeat_loop() -> None`

**Purpose**: Infinite heartbeat loop with exponential backoff on failures.

**Backoff behavior**:
- Normal: 60s (RETRY_HEARTBEAT_INTERVAL_SEC)
- After 1st failure: 120s (60 * 2^1)
- After 2nd failure: 240s (60 * 2^2)
- Max: 900s (RETRY_HEARTBEAT_BACKOFF_MAX_SEC)
- On success: reset to 60s

**Pseudocode**:
```python
def _heartbeat_loop() -> None:
    global _HEARTBEAT_CONSECUTIVE_FAILURES
    
    current_interval = RETRY_HEARTBEAT_INTERVAL_SEC
    
    while not _HEARTBEAT_STOP.is_set():
        try:
            flushed = _heartbeat_step()
            
            # Adjust backoff based on result
            if flushed > 0:
                # Success — reset backoff
                current_interval = RETRY_HEARTBEAT_INTERVAL_SEC
                _HEARTBEAT_CONSECUTIVE_FAILURES = 0
            elif _HEARTBEAT_CONSECUTIVE_FAILURES > 0:
                # Empty queue but previous failure — apply backoff
                current_interval = min(
                    RETRY_HEARTBEAT_INTERVAL_SEC * (2 ** _HEARTBEAT_CONSECUTIVE_FAILURES),
                    RETRY_HEARTBEAT_BACKOFF_MAX_SEC
                )
            # else: empty queue, no failures — stay at normal interval
            
            # Sleep with stop-check (allows graceful shutdown)
            _HEARTBEAT_STOP.wait(current_interval)
        
        except Exception as e:
            logging.error(f"[HEARTBEAT] loop exception: {safe_log_exception(e)}")
            _HEARTBEAT_STOP.wait(5)  # brief sleep, then retry
```

---

### 6. `start_retry_heartbeat() -> bool`

**Purpose**: Start heartbeat thread idempotently.

**Returns**: True if started now, False if already running.

**Pseudocode**:
```python
def start_retry_heartbeat() -> bool:
    global _HEARTBEAT_RUNNING
    
    if _HEARTBEAT_RUNNING:
        return False  # already started
    
    _HEARTBEAT_RUNNING = True
    threading.Thread(
        target=_heartbeat_loop,
        daemon=True,
        name="firebase-retry-heartbeat"
    ).start()
    
    logging.info(
        f"[HEARTBEAT] started "
        f"(interval={RETRY_HEARTBEAT_INTERVAL_SEC}s, "
        f"max_batch={RETRY_HEARTBEAT_MAX_BATCH}, "
        f"backoff_max={RETRY_HEARTBEAT_BACKOFF_MAX_SEC}s)"
    )
    return True
```

---

## Refactored save_batch()

**Pseudocode**:
```python
def save_batch(batch):
    """Public API: save new trades. Requeue on failure."""
    if db is None:
        return
    
    # Step 1: Drain any previously failed batches
    queued = _drain_retry_queue(max_items=_MAX_RETRY_SIZE)
    if queued:
        batch = queued + batch  # prepend queued items to current batch
    
    # Step 2: Write combined batch
    success = _write_batches_direct(batch, source="normal")
    
    # Step 3: If write succeeded, update stats
    if success:
        slimmed = [_slim_trade(t) for t in batch]
        wins = sum(1 for t in slimmed if t.get("result") == "WIN")
        losses = sum(1 for t in slimmed if t.get("result") == "LOSS")
        timeouts = sum(1 for t in slimmed if ...)
        increment_stats(len(batch), wins, losses, timeouts)
        print(f"[FIREBASE_WRITE] queued {len(batch)} trades (async write, non-blocking)")
        return len(batch)
    else:
        # _write_batches_direct already requeued on failure
        return 0
```

**Key changes**:
- No direct `_RETRY_QUEUE.extend()` (only via _enqueue_retry)
- No direct `_RETRY_QUEUE.clear()` (only via _drain_retry_queue)
- Firebase write moved to _write_batches_direct (single source of truth)

---

## Modified Sections in firebase_client.py

### Section 1: Module-level variables (add after line 52)

```python
RETRY_HEARTBEAT_INTERVAL_SEC = 60
RETRY_HEARTBEAT_MAX_BATCH = 100
RETRY_HEARTBEAT_BACKOFF_MAX_SEC = 900

_RETRY_QUEUE_LOCK = threading.Lock()
_HEARTBEAT_RUNNING = False
_HEARTBEAT_STOP = threading.Event()
_HEARTBEAT_CONSECUTIVE_FAILURES = 0
_HEARTBEAT_LAST_LOG_TS = 0
```

### Section 2: Replace save_batch() (lines 399–470)

Replace entire function with refactored version (see pseudocode above).

### Section 3: Add new helper functions (after save_batch)

Add _enqueue_retry, _drain_retry_queue, _write_batches_direct, _heartbeat_step, _heartbeat_loop, start_retry_heartbeat.

**Total new lines**: ~150 (signatures + bodies)

### Section 4: Call start_retry_heartbeat() in init_firebase()

**Location**: Lines 277–279 (after `db = firestore.client()`)

```python
def init_firebase():
    global db
    if firebase_admin._apps:
        db = firestore.client()
        start_retry_heartbeat()  # ← ADD
        return db
    
    key = os.getenv("FIREBASE_KEY_BASE64")
    if not key:
        print("⚠️  Firebase disabled (no FIREBASE_KEY_BASE64)")
        return None
    
    cred = credentials.Certificate(json.loads(base64.b64decode(key)))
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("[Firebase] connected")
    start_retry_heartbeat()  # ← ADD
    return db
```

---

## Expected Logs

### Startup
```
[Firebase] connected
[HEARTBEAT] started (interval=60s, max_batch=100, backoff_max=900s)
```

### Normal operation (queue draining)
```
[HEARTBEAT] flushed 47/250 items from retry queue       # logged every 60s
[HEARTBEAT] flushed 0/10 items from retry queue         # (queue had items but drained in previous cycle)
```

### No queue log spam
```
(no log if queue empty)
```

### On write failure
```
[HEARTBEAT] write failed: Connection error — requeuing
[HEARTBEAT] write failed (consecutive_failures=1)
[HEARTBEAT] write failed (consecutive_failures=2)
```

### On queue overflow
```
⚠️  Retry queue overflow (reason=heartbeat:exception): dropped 47 oldest items (limit=50000)
```

---

## Validation Commands (After Implementation)

### 1. Syntax check
```bash
python -m py_compile src/services/firebase_client.py
```

### 2. Import check
```bash
python -c "from src.services.firebase_client import init_firebase; print('✓ OK')"
```

### 3. Lock presence
```bash
grep -c "_RETRY_QUEUE_LOCK" src/services/firebase_client.py
# Expected: >= 6 (enqueue, drain, heartbeat_step, heartbeat_loop, etc.)
```

### 4. Function presence
```bash
grep "^def _enqueue_retry\|^def _drain_retry_queue\|^def _write_batches_direct\|^def _heartbeat_step\|^def _heartbeat_loop\|^def start_retry_heartbeat" src/services/firebase_client.py
# Expected: 6 functions found
```

### 5. No save_batch recursion
```bash
# Verify _heartbeat_loop does NOT call save_batch()
grep "_heartbeat_loop" -A 50 src/services/firebase_client.py | grep -c "save_batch"
# Expected: 0
```

### 6. Module constants present
```bash
grep "RETRY_HEARTBEAT_INTERVAL_SEC\|RETRY_HEARTBEAT_MAX_BATCH\|RETRY_HEARTBEAT_BACKOFF_MAX_SEC" src/services/firebase_client.py
# Expected: all 3 present
```

### 7. Idempotency test (manual)
```python
from src.services.firebase_client import start_retry_heartbeat
result1 = start_retry_heartbeat()  # Should be True
result2 = start_retry_heartbeat()  # Should be False
print(f"First: {result1}, Second: {result2}")
# Expected: First: True, Second: False
```

### 8. Enqueue/Drain count preservation
```python
from src.services.firebase_client import _enqueue_retry, _drain_retry_queue

# Enqueue 50 items
_enqueue_retry([{"id": i} for i in range(50)], "test")

# Drain 30 items
batch1 = _drain_retry_queue(30)
assert len(batch1) == 30, f"Expected 30, got {len(batch1)}"

# Drain remaining 20
batch2 = _drain_retry_queue(50)
assert len(batch2) == 20, f"Expected 20, got {len(batch2)}"

# Verify empty
batch3 = _drain_retry_queue(50)
assert len(batch3) == 0, f"Expected 0, got {len(batch3)}"

print("✓ Enqueue/drain count preservation OK")
```

### 9. Empty queue no spam
```bash
# Run pre_live_audit, monitor for "HEARTBEAT" log spam with empty queue
# Expected: no "HEARTBEAT flushed 0/0" logs (if queue stays empty)
python bot2/main.py 2>&1 | grep -i "heartbeat flushed 0" | wc -l
# Expected: 0 (if queue is empty, no log)
```

### 10. Pre-live audit (regression gate)
```bash
python bot2/main.py
# Expected:
# - No errors in startup
# - Runtime version marker present
# - Pre-live audit passes (same canonical metrics as baseline)
# - Trade execution continues normally
```

---

## Risk Assessment (Post-Revision)

### Eliminated Risks
✅ **Re-entry recursion**: Heartbeat calls _drain/_write, NOT save_batch  
✅ **Race conditions**: Explicit lock on all queue operations  
✅ **Excessive backoff**: Only backoff on failure, not empty queue  
✅ **Log spam**: Rate-limited (60s), silent if queue empty  
✅ **Unbounded writes**: Batch size limited (100), backoff increases  
✅ **Duplicate threads**: Flag-based idempotency check  

### Remaining Risks (Mitigated)
⚠️ **Async write lag**: Async Firebase thread might not complete before heartbeat flushes  
  → Mitigation: Same as existing code; heartbeat just drains faster

⚠️ **Concurrent _async_firebase_write threads**: Multiple heartbeat + normal save_batch spawns  
  → Mitigation: Acceptable (Firestore handles batching); keep daemon count low

⚠️ **Backoff tuning**: 60s interval might be too frequent or too slow  
  → Mitigation: Configurable constants; user can tune; monitor logs for 24h

### No Risk To
✅ **EV/RDE**: Heartbeat is persistence-only  
✅ **Trading behavior**: Heartbeat only flushes already-recorded trades  
✅ **Firebase schema**: No schema changes  
✅ **Android dashboard**: No new fields  
✅ **Signal generation**: Unaffected  
✅ **Exit logic**: Unaffected  

---

## Summary of Changes

| Aspect | Before | After |
|--------|--------|-------|
| **Architecture** | Direct _RETRY_QUEUE access | Three-tier: enqueue/drain/write |
| **Locking** | None (⚠️ unsafe) | Explicit Lock (safe) |
| **Backoff** | On empty queue (wasteful) | On write failure only |
| **Interval** | 30s | 60s |
| **Batch size** | 200 items | 100 items |
| **Idempotency** | Implicit (risky) | Explicit flag (safe) |
| **Shutdown** | Daemon only | Daemon + Event |
| **Logging** | All operations | Selective (rate-limited, no spam) |
| **Drop policy** | Unclear | Explicit: truncate to max, log critical |
| **Validation** | None | 10 comprehensive commands |

---

## Notes

- **This plan addresses all 10 corrections from user feedback.**
- **Re-entry safety**: Heartbeat never calls save_batch, eliminating recursion risk entirely.
- **Conservative defaults**: 60s interval + 100-item batches stay well under Firebase quota.
- **Graceful degradation**: If heartbeat fails, normal save_batch still works (queue just accumulates slower).
- **Approval required** before implementation — confirm architecture, intervals, and validation commands acceptable.

