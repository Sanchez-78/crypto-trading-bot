# CRITICAL BUG REPORT — 2026-04-20

**Status**: 17 bugs identified, 6 critical, 6 medium, 5 low priority  
**Impact**: Watchdog nonfunctional, drawdown protection broken, 3s blocking in event loop  
**Action**: Critical bugs MUST be fixed before production deployment

---

## 🔴 CRITICAL BUGS (Must Fix Before Deployment)

### BUG 1: last_trade_ts → last_trade_time mismatch
**File**: bot2/main.py L1124, L1384  
**Severity**: 🔴 CRITICAL — Watchdog completely broken

**Problem**:
```python
# L1124 — reads WRONG key:
idle_sec = safe_idle_seconds(METRICS.get("last_trade_ts"), now)

# learning_event.py L47 — actual key is:
"last_trade_time": 0.0,
```

**Impact**:
- `METRICS.get("last_trade_ts")` always returns `None`
- `safe_idle_seconds()` always returns `0.0`
- Watchdog never detects stall (stall_recovery never triggers)
- Emergency recovery never activates (thinks idle=0 always)
- **Multi-day dead periods without recovery activation** ← explains recent logs

**Fix**: Change `"last_trade_ts"` → `"last_trade_time"` on lines 1124, 1384

---

### BUG 2: METRICS missing drawdown/sharpe keys
**File**: trade_executor.py L1452–1453  
**Severity**: 🔴 CRITICAL — Drawdown protection nonfunctional

**Problem**:
```python
_dd_mc    = _gm().get("max_drawdown", 0.0)  # ← doesn't exist in METRICS
_sharpe   = _gm().get("sharpe", 0.0)        # ← doesn't exist in METRICS
```

**Impact**:
- Both always return `0.0`
- `meta_controller()` receives false inputs
- Drawdown protection always returns `1.0x` (never blocks)
- **Bot can trade through catastrophic losses** without protection

**Fix**: 
```python
_dd_mc = _gm().get("drawdown", 0.0)  # actual key in METRICS
_sharpe = 0.5  # compute actual sharpe or remove
```

---

### BUG 3: _flush() blocks event loop with 3s sleep
**File**: firebase_client.py L214–215  
**Severity**: 🔴 CRITICAL — Market stream completely stalls

**Problem**:
```python
except Exception as e:
    print(f"⚠️  save_batch failed ({e}) — retrying in 3 s …")
    time.sleep(3)   # ← BLOCKS MARKET STREAM THREAD
```

**Impact**:
- When Firestore fails, entire market stream thread sleeps 3 seconds
- Incoming price ticks are dropped (no on_price() calls)
- TP/SL not updated
- Open positions not monitored
- **During any Firestore issue, bot is blind for 3+ seconds**

**Fix**: Move retry to separate thread or use asyncio, don't block main thread

---

### BUG 4: bool_f used before definition (NameError risk)
**File**: trade_executor.py L2173  
**Severity**: 🔴 CRITICAL (intermittent)

**Problem**:
```python
try:
    from src.services.feature_weights import update_feature_weights as _ufw
    _active_fw = [k for k, v in bool_f.items() if v]  # ← bool_f not defined yet
```

`bool_f` is only defined at L2148, inside try block for lm_update. If that block fails, `bool_f` is undefined.

**Impact**:
- During Firebase import error → `NameError: name 'bool_f' is not defined`
- **Crashes on_price() entirely**
- Market stream handler dies, no signals processed

**Fix**: Define `bool_f = {}` before try block

---

### BUG 5: return None vs return (handle_signal)
**File**: trade_executor.py L1603  
**Severity**: 🔴 CRITICAL (logic error)

**Problem**:
```python
if _reg_n >= 25 and _reg_wr < 0.35:
    log.info(...)
    return None   # ← WRONG
```

**Impact**:
- Callers may check `if handle_signal(signal):` expecting bool or None distinction
- None vs no return value causes subtle caller logic errors
- Event bus subscribers may misinterpret result

**Fix**: Change `return None` → `return` (no value)

---

### BUG 6: Double-print of trade logs
**File**: trade_executor.py L2102–2108, L1704–1708  
**Severity**: 🔴 CRITICAL (data integrity)

**Problem**:
```python
# L2102–2103: direct print
print(f"    {icon} {short} {pos['action']} ...")
# L2106–2108: SECOND print via event bus
msg = (f"    {icon} {short} {pos['action']} ...")
get_event_bus().emit("LOG_OUTPUT", {"message": msg}, time.time())
```

**Impact**:
- Every closed trade logged twice in logs
- Logs become unreadable (massive duplication)
- Debugging nearly impossible
- Analytics see 2× trade count

**Fix**: Remove one of the two print paths (keep event bus, remove direct print)

---

## 🟡 MEDIUM PRIORITY (Should fix)

### BUG 7: Timeouts double-counted during bootstrap
**File**: learning_event.py L470, L472, L477  
**Impact**: Incorrect timeout metrics after bootstrap

### BUG 8: on_price() latency timer includes flush time
**File**: trade_executor.py L1829–1831  
**Impact**: False 50ms+ latency alarms when Firestore slow

### BUG 9: replace_if_better() result ignored
**File**: trade_executor.py L1225–1226  
**Impact**: Replacement logic inconsistent

### BUG 10: _regime_exposure desynchronization
**File**: trade_executor.py L2223–2224  
**Impact**: Concentration exposure miscalculated after restart

### BUG 11: Pyramiding entry not refreshed for move calculation
**File**: trade_executor.py L1935–1941  
**Impact**: Stale entry used in soft_exit check

### BUG 12: Circular import (trade_executor ↔ bot2.main)
**File**: trade_executor.py L1769  
**Impact**: Fragility, testability issues

---

## 🟢 LOW PRIORITY (Tech debt)

### BUG 13: Timestamp in trade dict (entry vs close time)
**File**: trade_executor.py L2127  
**Impact**: Trade history may sort incorrectly

### BUG 14: Multiple import paths for same module
**Impact**: Module duplication in sys.modules edge cases

### BUG 15: Unbounded _RETRY_QUEUE
**File**: firebase_client.py L221  
**Impact**: OOM risk during Firebase outages

### BUG 16: atomic_render() deduplication ineffective
**File**: bot2/main.py L220–224  
**Impact**: Unnecessary overhead

### BUG 17: safe_idle_seconds() clamps to 0 after 86400s
**File**: bot2/main.py L77–78  
**Impact**: Watchdog blind to > 24h idle periods

---

## FIX PRIORITY ORDER

**MUST FIX before production (today)**:
1. ✅ BUG 1 — last_trade_ts → last_trade_time (watchdog)
2. ✅ BUG 2 — max_drawdown key (drawdown protection)
3. ✅ BUG 3 — remove sleep(3) from event loop
4. ✅ BUG 4 — define bool_f before try
5. ✅ BUG 5 — return None → return
6. ✅ BUG 6 — remove double-print

**Should fix soon (next 24h)**:
7. BUG 7, 8, 9, 10, 11, 12

**Low priority (next week)**:
13, 14, 15, 16, 17

