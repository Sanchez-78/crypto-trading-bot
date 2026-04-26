# EMERGENCY: Firebase Read Quota Containment Patch Plan

**Status**: ANALYSIS & PLAN ONLY. Do not implement yet. Read quota exceeded before 11:00 UTC.

**Date**: 2026-04-25

**Severity**: CRITICAL — 50k read quota exceeded mid-day. Previous emergency at 6000 reads/36min (240k/day equivalent).

---

## Root Cause Analysis

### Evidence of High-Frequency Reads

**File**: `src/services/realtime_decision_engine.py`, lines 28-30:
```python
# V10.15 QUOTA EMERGENCY FIX: Cache history at module level
# Prevents calling load_history() on every signal (was causing 6000 reads/36min!)
_cached_history = {"data": None, "ts": 0, "ttl": 21600}  # 6 hour cache
```

**Previous runaway rate**: 6000 reads in 36 minutes = **240k/day** vs. 50k/day limit.

**Current cache TTLs** (firebase_client.py, lines 257-259):
- HISTORY_TTL: 21600s (6 hours) — conservative
- WEIGHTS_TTL: 3600s (1 hour) — potentially too short
- SIGNALS_TTL: 3600s (1 hour) — potentially too short

### Identified High-Frequency Read Sites

| # | File | Function | Query Type | Frequency | Est. Reads/Day | Critical |
|---|------|----------|-----------|-----------|---|---|
| 1 | realtime_decision_engine.py | _get_cached_history() | .stream() (trades) | Max 1/6hrs (cached) | ~4 | YES |
| 2 | firebase_client.py:371 | load_history() | .stream() .order_by() .limit() | On cache miss | ~5-10 | YES |
| 3 | firebase_client.py:644 | load_all_signals() | .stream() .order_by() .limit() | On cache miss (1hr) | ~24 | NO |
| 4 | firebase_client.py:585 | load_old_trades() | .stream() .order_by() .limit() | Periodic (auto_cleaner) | ~20-50 | NO |
| 5 | firebase_client.py:234 | _read_doc_dict() | .get() (single doc) | Multiple per minute | ~100-200 | MEDIUM |
| 6 | firebase_client.py:520 | load_stats() | .get() (system/stats) | On call | ~10-50 | YES |
| 7 | firebase_client.py:566 | load_model_state() | .get() (model_state) | Periodic | ~50-100 | YES |
| 8 | firebase_client.py:661 | load_weights() | .get() (weights/model) | On cache miss (1hr) | ~24 | YES |

### Estimated Top 5 Read-Cost Sources

1. **_read_doc_dict() generic wrapper** (~100-200 reads/day)
   - Called by load_config, load_advice, load_weights, load_push_token
   - No unified rate-limiting
   - TTL sometimes very short (120s for WEIGHTS)

2. **load_history() unbounded .stream()** (~50-100 reads/day)
   - Each call reads up to HISTORY_LIMIT docs
   - Cache miss forces full collection scan
   - On quota limit, still tries to read

3. **load_old_trades() in auto_cleaner.py** (~20-50 reads/day)
   - Periodic cleanup reads oldest trades
   - No limit enforcement
   - Could be triggered by external system

4. **load_all_signals() in ML retrainer** (~20-30 reads/day)
   - Reads up to 200 signal documents
   - TTL only 1 hour
   - ML training might trigger frequently

5. **load_model_state() for learning updates** (~30-50 reads/day)
   - Called from adaptive recovery, learning engine
   - Could be in decision loop if cache expires

### Current Problems

| Problem | Impact | Evidence |
|---------|--------|----------|
| **No unified quota enforcement** | Reads continue even when quota warning | firebase_client.py line 116: stops at 80% (40k reads) |
| **Cache TTLs too short for non-critical reads** | Unnecessary re-reads | WEIGHTS_TTL=3600s (1hr) → ~24 reads/day |
| **No "degraded mode"** | No graceful fallback | Code tries to read even when quota critical |
| **.stream() without fallback** | Full collection scans expensive | load_history() expensive; no fast-fail |
| **External integrations unknown** | Could be polling dashboard | Android app, metrics endpoints not in repo |
| **Auto-cleanup runs blind** | Could spike reads periodically | auto_cleaner.py calls load_old_trades() unthrottled |

---

## Emergency Containment Design

### A) Unified Quota Enforcement Wrapper

**New function**: `safe_get_with_quota_bypass(path, fallback, ttl_sec, label)`

```python
def safe_get_with_quota_bypass(path: str, fallback: dict, ttl_sec: int, label: str) -> dict:
    """
    Read single document with graceful degradation on quota limit.
    
    Behavior:
    - If quota < 50%: read normally, cache
    - If quota 50-70% (WARNING): read if cache miss, otherwise use cache
    - If quota 70-90% (DEGRADED): skip non-critical reads, use cache
    - If quota > 90% (CRITICAL): NO reads, cache only
    
    label classifies read criticality:
      "critical": never skip (e.g., load_stats for trading)
      "normal": skip at DEGRADED
      "optional": skip at WARNING+
    """
    severity = _get_quota_severity_reads()  # OK|WARNING|DEGRADED|CRITICAL
    
    # Check cache first
    if cache_valid(path, ttl_sec):
        return get_cache(path)
    
    # At DEGRADED/CRITICAL, skip non-critical reads
    if severity in ("DEGRADED", "CRITICAL") and label != "critical":
        logging.info(f"[QUOTA_{severity}] skipping {label} read (using cache)")
        return get_cache(path) or fallback
    
    # At CRITICAL, skip all non-critical
    if severity == "CRITICAL" and label != "critical":
        return get_cache(path) or fallback
    
    # Attempt read
    try:
        result = db.document(path).get().to_dict() or fallback
        _record_read(1)
        cache_set(path, result, ttl_sec)
        return result
    except Exception as e:
        if "429" in str(e):
            _mark_quota_exhausted(e)
        return get_cache(path) or fallback
```

### B) Ban Unbounded .stream() in Runtime

**Rule**: No `.stream()` without explicit `.limit()` in live code.

**Current violations**:
- ✅ firebase_client.py:371: load_history() — has .limit(limit)
- ✅ firebase_client.py:644: load_all_signals() — has .limit(SIGNALS_LIMIT)
- ❌ firebase_client.py:585: load_old_trades() — HAS .limit() ✓ (ok)
- ❌ reset_db.py:92: `.stream()` in ADMIN/maintenance script (ok to keep)

**Immediate action**: Verify no unbounded .stream() in runtime paths:

```bash
grep -n "\.stream()" src/services/realtime_decision_engine.py src/services/trade_executor.py src/services/signal_engine.py src/services/execution_engine.py
# Expected: 0 matches
```

### C) Read Budget States with Graceful Degradation

**New states** (replacing current OK/WARNING/HIGH_WARNING/CRITICAL):

```python
_QUOTA_READ_SEVERITY = "OK"  # OK | WARNING | DEGRADED | CRITICAL

# Thresholds
OK: < 50% (< 25,000 reads)
WARNING: 50–70% (25k–35k reads)
DEGRADED: 70–90% (35k–45k reads)
CRITICAL: > 90% (> 45k reads)

# Behavior by state
OK: All reads allowed, normal cache TTL
WARNING: All reads allowed, log warning, increase cache TTL (2x)
DEGRADED: Non-critical reads skipped, use cache, log critical
CRITICAL: Only critical reads, cache only, emergency alert
```

**Implementation**:

```python
def _get_quota_severity_reads() -> str:
    """Determine read quota severity."""
    pct = _QUOTA_READS / _QUOTA_MAX_READS * 100
    if pct >= 90:
        return "CRITICAL"
    elif pct >= 70:
        return "DEGRADED"
    elif pct >= 50:
        return "WARNING"
    else:
        return "OK"

def _apply_degradation_strategy():
    """Apply quotient behavior at each severity level."""
    severity = _get_quota_severity_reads()
    
    if severity == "CRITICAL":
        # LOCK: only critical reads
        # Signal to skip non-critical operations:
        # - Skip load_all_signals
        # - Skip load_old_trades (auto_cleaner can wait)
        # - Skip load_weights if cache valid
        # - Use in-memory cached metrics
        logging.critical("[QUOTA_CRITICAL] Firestore read mode: LOCAL CACHE ONLY")
        return False  # signal to skip non-critical
    
    elif severity == "DEGRADED":
        # Skip optional reads, warn
        logging.warning("[QUOTA_DEGRADED] Reducing Firestore read frequency")
        return False  # skip optional
    
    elif severity == "WARNING":
        # Increase cache TTL, log
        logging.warning("[QUOTA_WARNING] Firestore read quota at 50-70%")
        return True  # allow, but TTL increased
    
    return True  # OK
```

### D) Revised Cache Strategy

**Current TTLs** (too short for non-critical):
- HISTORY_TTL: 21600s (6h) — ✓ good
- WEIGHTS_TTL: 3600s (1h) — too short for DEGRADED
- SIGNALS_TTL: 3600s (1h) — too short

**New TTLs**:
- HISTORY_TTL: 21600s (6h) — keep, trading-critical
- WEIGHTS_TTL: 7200s (2h) in PERF_MODE, 3600s (1h) in normal — increase
- SIGNALS_TTL: 7200s (2h) — increase
- METRICS_TTL: 300s (5min) — add new, short for freshness
- CONFIG_TTL: 600s (10min) — increase from 300s

**At WARNING+**: Double all TTLs (except critical ones)

```python
def get_effective_ttl(key: str, severity: str) -> int:
    """Get TTL adjusted for quota severity."""
    base_ttls = {
        "history": 21600,
        "weights": 3600,
        "signals": 3600,
        "metrics": 300,
        "config": 600,
    }
    ttl = base_ttls.get(key, 300)
    if severity in ("WARNING", "DEGRADED"):
        ttl *= 2  # double TTL at WARNING+
    return ttl
```

### E) Android/Dashboard Mitigation

**Root problem**: External system may be polling Firestore directly or via metrics endpoints.

**Strategy**:
1. Dashboard should aggregate metrics into ONE document (metrics/latest)
2. Refresh interval minimum 60s (preferably 120-300s)
3. No history tab auto-load unless user explicitly opens
4. Paginate history with explicit page token (not full scan)

**If dashboard code exists in repo**: Add request throttling, aggregate reads.

**If dashboard is external Android app**: Cannot fix directly, but monitor metrics endpoint hits.

---

## Minimal Emergency Patch Plan

### Phase 1: Immediate Containment (0–2 hours)

**Goal**: Prevent further quota overage during current day.

**Changes** (minimal, reversible):

1. **firebase_client.py** (lines 112–120): Tighten _can_read() threshold
   ```python
   # BEFORE: stop at 80% (40k reads)
   if _QUOTA_READS >= _QUOTA_MAX_READS * 0.8:
       return False, _QUOTA_READS, _QUOTA_MAX_READS
   
   # AFTER: stop at 65% (32.5k reads) - emergency brake
   if _QUOTA_READS >= _QUOTA_MAX_READS * 0.65:
       return False, _QUOTA_READS, _QUOTA_MAX_READS
   ```
   **Rationale**: Earlier cutoff prevents overage. Non-critical reads fall back to cache.

2. **firebase_client.py** (lines 257–259): Increase non-critical TTLs immediately
   ```python
   # BEFORE
   HISTORY_TTL    = 300 if PERF_MODE else 21600
   WEIGHTS_TTL    = 120 if PERF_MODE else 3600
   SIGNALS_TTL    = 600 if PERF_MODE else 3600
   
   # AFTER (emergency)
   HISTORY_TTL    = 300 if PERF_MODE else 21600   # keep
   WEIGHTS_TTL    = 120 if PERF_MODE else 7200    # 1h → 2h
   SIGNALS_TTL    = 600 if PERF_MODE else 7200    # 1h → 2h
   CONFIG_TTL     = 300  # add: cap refresh to 5min
   ```
   **Rationale**: Doubles TTL for weights/signals → ~50% fewer reads.

3. **auto_cleaner.py** (call site): Throttle load_old_trades() to once per hour
   ```python
   # Add check: only run if 1 hour has passed since last cleanup
   _LAST_CLEANUP_TS = 0
   
   def cleanup():
       global _LAST_CLEANUP_TS
       now = time.time()
       if now - _LAST_CLEANUP_TS < 3600:  # 1 hour throttle
           return
       _LAST_CLEANUP_TS = now
       trades = load_old_trades(200)  # ok to read once/hour
       # ... cleanup logic
   ```
   **Rationale**: Reduces cleanup reads from potentially 50/day to ~24/day.

4. **realtime_decision_engine.py** (line 55): No change needed (already caching 6 hours)

### Phase 2: Monitoring & Logs (parallel, 2–4 hours)

Add read quota diagnostics:

**firebase_client.py**: Enhance logging

```python
def _record_read(count=1):
    global _QUOTA_READS
    _QUOTA_READS += count
    import logging
    reads_pct = _QUOTA_READS/_QUOTA_MAX_READS*100
    severity = _get_quota_severity_reads()
    
    # Log at WARNING+
    if reads_pct >= 50:
        logging.warning(
            f"[QUOTA_{severity}] Firebase reads: {_QUOTA_READS}/50000 ({reads_pct:.1f}%)"
        )
```

**Command to monitor quota state**:
```bash
python -c "
from src.services.firebase_client import get_quota_status
print(get_quota_status())
"
# Expected output: {'reads': 35000, 'writes': 5000, 'severity': 'DEGRADED', ...}
```

### Phase 3: Post-Emergency Review (4+ hours)

After quota resets at midnight PT (09:00 GMT+2):

1. Analyze which reads contributed most
2. Check if Android/dashboard was polling excessively
3. Implement Phase 2 below (unified wrapper)

---

## Extended Patch (Phase 2 — Post-Emergency)

**Only after quota reset and current crisis contained.**

### Add safe_get_with_quota_bypass() wrapper

Replace direct `.get()` calls in non-critical paths with quota-aware wrapper.

**Files affected**:
- firebase_client.py: load_weights(), load_config(), load_advice()
- notifier.py: load_push_token()

**Benefit**: Graceful degradation at CRITICAL quota.

---

## Files to Change

| File | Change | Lines | Urgency |
|------|--------|-------|---------|
| src/services/firebase_client.py | Tighten _can_read() threshold (65% not 80%) | 116 | IMMEDIATE |
| src/services/firebase_client.py | Increase WEIGHTS_TTL, SIGNALS_TTL | 258–259 | IMMEDIATE |
| src/services/auto_cleaner.py | Add 1-hour throttle to cleanup call | ~7 | IMMEDIATE |
| src/services/firebase_client.py | Add/enhance quota logging (optional) | +10 | 2–4 HOURS |

---

## Validation Commands

### 1. No unguarded .stream() in runtime

```bash
grep -rn "\.stream()" src/services/realtime_decision_engine.py src/services/trade_executor.py src/services/signal_engine.py src/services/execution_engine.py 2>/dev/null
# Expected: 0 matches
```

### 2. TTL values changed

```bash
grep "WEIGHTS_TTL\|SIGNALS_TTL" src/services/firebase_client.py
# Expected: WEIGHTS_TTL = ... 7200 ..., SIGNALS_TTL = ... 7200 ...
```

### 3. _can_read() threshold lowered

```bash
grep "_QUOTA_MAX_READS \* 0" src/services/firebase_client.py
# Expected: 0.65 (not 0.8)
```

### 4. Auto-cleaner throttled

```bash
grep -n "_LAST_CLEANUP\|cleanup()" src/services/auto_cleaner.py
# Expected: throttle check present
```

### 5. Compile check

```bash
python -m py_compile src/services/firebase_client.py src/services/auto_cleaner.py
# Expected: OK
```

### 6. Quota status command

```bash
python -c "from src.services.firebase_client import get_quota_status; import json; print(json.dumps(get_quota_status(), indent=2))"
# Expected: reads, writes, severity, etc.
```

---

## Expected Outcome

**If implemented immediately**:
- ✅ Emergency quota brake at 65% (32.5k reads) prevents overage
- ✅ Increased TTLs reduce read frequency by ~40-50%
- ✅ Auto-cleaner throttle reduces reads by ~20-30 reads/day
- ✅ Total reduction: ~50-60 reads/day → should prevent future storms
- ✅ EV/RDE trading behavior unaffected (caches still feed decision engine)

**Expected daily read budget after patch**:
- Current (storm): ~50k+ (exceeded)
- Post-patch: ~30-35k (safe, under 50k limit with margin)

---

## Rollback Plan

If patch causes regressions:

```bash
# Revert firebase_client.py and auto_cleaner.py changes
git diff HEAD~1 src/services/firebase_client.py src/services/auto_cleaner.py
git checkout HEAD -- src/services/firebase_client.py src/services/auto_cleaner.py
git commit -m "ROLLBACK: Revert emergency read quota containment"
```

**Rollback markers**: 
- Look for "EMERGENCY" comments in code
- TTL changes will be obvious in git diff

---

## Whether to Pause Bot/Dashboard

**Recommendation**: **DO NOT PAUSE BOT or trading.**

- ✅ Caching strategy means stale data is acceptable for non-critical reads
- ✅ Trading decision engine uses 6-hour cached history (already protected)
- ✅ Trade execution (signal_engine, trade_executor) unaffected by quota
- ✅ Emergency patch prevents further overage without blocking trades

**Only pause if**:
- Quota hit 100% (hard failure, not fixable by caching)
- Trading logic breaks from cache misses (unlikely)

---

## Next Steps

1. **Approve this emergency patch plan** (no changes yet)
2. **If approved**: Implement Phase 1 (~30 minutes)
3. **Monitor**: Watch quota state for next 24 hours
4. **After reset**: Implement Phase 2 (unified wrapper) if needed
5. **Root cause**: Investigate why quota spiked despite previous fixes

---

## Questions for Investigation (Parallel)

While patch is deploying, answer:
1. Is Android app polling metrics/trades endpoint excessively?
2. Are there external cron jobs hitting Firestore (not in this repo)?
3. Did signal_engine or realtime_decision_engine have recent changes?
4. Is PERF_MODE enabled? (would reduce some cache TTLs)
5. Any recent Firebase indexing changes?

