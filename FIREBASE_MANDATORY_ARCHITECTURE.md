# V10.27: Firebase-Mandatory Knowledge Architecture

**Status:** ✅ IMPLEMENTED

**Date:** 2026-06-11

---

## Overview

Firebase is now the **MANDATORY source of knowledge** on every bot startup. If Firebase is unavailable, startup **fails hard** (no fallback).

This ensures all bot instances have:
- ✅ Consistent, authoritative knowledge state
- ✅ Deterministic behavior (no ambiguous local vs Firebase sources)
- ✅ Auditable knowledge chain (all decisions trace to Firebase source)

---

## Architecture

### Startup Sequence (V10.27)

```
Bot Startup
    ↓
1. MANDATORY Firebase Connection
    ├─ Load FIREBASE_KEY_BASE64
    ├─ Initialize Firestore client
    └─ FAIL HARD if unavailable → sys.exit(1)
    ↓
2. MANDATORY Knowledge Load from Firebase
    ├─ Load: Trade history (100 docs)
    ├─ Load: Calibration state (W/L by segment)
    ├─ Load: Entry gate weights
    ├─ Load: Running metrics (WR, PF, expectancy)
    └─ Cache results in Redis + local SQLite
    ↓
3. Ready for trading
    ├─ All decisions use Firebase-sourced knowledge
    ├─ Caches reduce subsequent Firebase reads
    └─ Learning updates continue to local SQLite (zero quota impact)
```

### Knowledge Sources During Runtime

| Knowledge Type | Primary | Backup | Quota Impact |
|---|---|---|---|
| **Learned Parameters** | Firebase (cached) | Redis | ~3 reads on startup, 0 thereafter |
| **Trade History** | Firebase (cached) | Local SQLite | ~1 read on startup, 0 thereafter |
| **Calibration State** | Firebase (cached) | Local JSON | ~1 read on startup, 0 thereafter |
| **Entry Gate Weights** | Firebase (cached) | Defaults | ~1 read on startup, 0 thereafter |
| **Learning Updates** | Local SQLite | Firebase 1x/hour | 0 Firebase reads, ~100 writes/day |

---

## Changes Made

### 1. firebase_client.py

**Added: `_load_mandatory_knowledge()`**
```python
def _load_mandatory_knowledge():
    """V10.27: Load all knowledge sources from Firebase (MANDATORY on startup).
    
    Loads:
    1. Trade history (last 100 trades)
    2. Calibration state (W/L by segment)
    3. Entry gate weights
    4. Running metrics (WR, PF, expectancy)
    """
    # Raises ConnectionError if Firebase unavailable
```

**Modified: `init_firebase()`**
```python
def init_firebase():
    """Initialize Firebase connection and MANDATORY load knowledge sources.
    
    V10.27: Firebase is now MANDATORY source of knowledge on startup.
    Raises ConnectionError if Firebase unavailable or knowledge load fails.
    """
    # Calls _load_mandatory_knowledge() after connection
    # Raises hard error if knowledge unavailable
```

**Removed: `get_local_metrics_fallback()`**
- No longer needed (Firebase is mandatory, not optional)
- Replaced with comment explaining the change

### 2. bot2/main.py

**Modified: Bootstrap sequence**
```python
print("  [4/7] Initializing Firebase (MANDATORY)...", file=sys.stderr, flush=True)
try:
    init_firebase()  # V10.27: Firebase is MANDATORY knowledge source
    print("  [4/7] Firebase initialized ✓", file=sys.stderr, flush=True)
except ConnectionError as e:
    print(f"\n✗ STARTUP FAILED: {e}", file=sys.stderr, flush=True)
    print(f"\nFirebase is MANDATORY for knowledge source on startup.", file=sys.stderr, flush=True)
    sys.exit(1)
```

**Behavior:**
- If Firebase unavailable → startup fails immediately
- Clear error message sent to stderr
- Process exits with code 1 (failure)
- No automatic restart (forces intervention)

### 3. learning_event.py

**Updated: Module docstring**
- Clarifies Firebase-mandatory architecture
- Documents caching strategy
- Explains local SQLite role (learning updates only)

**Updated: Import warning**
- Changed from "falling back to Firebase" to "learning updates will not be persisted locally"
- Reflects that local storage is now optional backup, not required fallback

---

## Quota Impact

### Per Startup

| Operation | Reads | Writes |
|-----------|-------|--------|
| Load trades | 1 | 0 |
| Load calibration | 1 | 0 |
| Load weights | 1 | 0 |
| Load metrics | 1 | 0 |
| Cache to Redis | 0 | 1 |
| Cache to SQLite | 0 | 1 |
| **Total** | **~4** | **~2** |

### Daily (Single Startup)

- **Firebase Reads:** 4/day (startup only)
- **Firebase Writes:** 2/day (startup cache)
- **Optional Backup Sync:** ~100 writes/day (1x/hour batch)
- **Total:** ~4 reads, ~102 writes/day (vs. 30k/10k quota)

**Safe margin:** 99.99% quota available for trading operations

---

## Error Handling

### Startup Failure Scenarios

| Scenario | Behavior | Message |
|----------|----------|---------|
| FIREBASE_KEY_BASE64 missing | Exit code 1 | "Firebase disabled: FIREBASE_KEY_BASE64 not set" |
| Firebase connection fails | Exit code 1 | "Firebase initialization failed: {error}" |
| Knowledge load fails | Exit code 1 | "Failed to load mandatory knowledge from Firebase: {error}" |
| Partial knowledge unavailable | Warning, continue | "Calibration/weights/metrics not found (new instance)" |

**Key difference:** Missing optional knowledge (calibration, weights) shows a warning but startup continues. Missing **required** knowledge (trades, metrics structure) fails startup.

---

## Verification

On successful startup, expect:
```
[4/7] Initializing Firebase (MANDATORY)...
[Firebase] connected
[KNOWLEDGE_LOAD] Loaded N trades from Firebase
[KNOWLEDGE_LOAD] Loaded calibration state
[KNOWLEDGE_LOAD] Loaded entry gate weights
[KNOWLEDGE_LOAD] Loaded running metrics
[KNOWLEDGE_LOAD] ✅ Mandatory knowledge loaded (trades=True, calibration=True, weights=True, metrics=True)
[4/7] Firebase initialized ✓
```

If Firebase is unavailable:
```
[4/7] Initializing Firebase (MANDATORY)...
✗ STARTUP FAILED: [STARTUP FATAL] Firebase initialization failed: {connection error}

Firebase is MANDATORY for knowledge source on startup.
Check FIREBASE_KEY_BASE64 environment variable and Firebase connectivity.
```

---

## Deployment Notes

1. **Environment Variables:** Ensure `FIREBASE_KEY_BASE64` is set before startup
2. **Firebase Connectivity:** Verify Firestore connection works from deployment environment
3. **Monitoring:** Alert on startup failures (exit code 1)
4. **Rollback:** If Firebase becomes unavailable, service will not start (fail-closed)

---

## Design Rationale

### Why Mandatory (Not Optional)

✅ **Consistency:** All instances load same knowledge on startup
✅ **Auditability:** No ambiguity about knowledge source
✅ **Safety:** Fails fast if data unavailable (rather than silently falling back)
✅ **Simplicity:** No complex fallback logic or sync resolution

### Why Not Continue with Local-First

❌ **Ambiguity:** Different instances could have different cached knowledge
❌ **Stale data:** Local cache might be old if server crashed
❌ **Hard to debug:** Knowledge source becomes non-deterministic
❌ **Quota still needed:** Even with local cache, startup needs Firebase read

---

## Future Enhancements

Potential improvements (not blocking deployment):
1. **Compressed knowledge snapshots:** Single "state.json" instead of 4 separate reads
2. **Warm standby:** Read knowledge from local cache in parallel during Firebase init
3. **Knowledge versioning:** Track knowledge version to detect stale caches
4. **Diagnostic dashboard:** Monitor knowledge load latency and success rates
