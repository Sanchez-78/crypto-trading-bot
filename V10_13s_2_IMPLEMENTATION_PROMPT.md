# V10.13s.2 Implementation Prompt — Remaining Startup Fixes

**Target**: AI Codex (Claude API) implementation patch  
**Scope**: 3 remaining issues from V10.13s log analysis  
**Language**: Czech (user preference)

---

## Context

System: CryptoMaster HF trading bot (V10.13x stabilized)  
Latest patch: V10.13s.1 (canonical state oracle)  
Current problem: 3 remaining startup issues from V10.13s log analysis

Log analysis file: `logs_extracted_tmp/V10_13s_Startup_Runtime_Analysis_2026_04_25.md`

---

## Task 1: Duplicate Event Subscription Guard

### Problem
Log shows:
```
Subscribed: price_tick -> on_price
Subscribed: price_tick -> on_price
```

Same handler registered twice → potential duplicate evaluation + overhead.

### Required Changes

**File**: `src/core/event_bus.py`

1. Add duplicate detection in `subscribe()`:
   ```python
   def subscribe(event, handler):
       key = f"{event}_{handler.__module__}_{handler.__name__}"
       
       # Check if already subscribed
       existing = _subscribers.get(event, [])
       if handler in existing:
           print(f"[!] Duplicate subscription prevented: {event} -> {handler.__name__}")
           return
       
       _subscribers.setdefault(event, []).append(handler)
       print(f"[OK] Subscribed: {event} -> {handler.__name__}")
   ```

2. Ensure all internal subscriptions use `subscribe_once()` instead of `subscribe()`

3. Search codebase for where `on_price` / `price_tick` is subscribed and confirm it's only once

### Deliverable
- Updated `event_bus.py` with duplicate guard
- No duplicate subscriptions in logs on next run

---

## Task 2: Firebase Quota Log Severity Fix

### Problem
Log shows:
```
CRITICAL: Firebase reads: 100/50,000 (0.2%)
```

This is classified as CRITICAL but it's only 0.2% of limit.  
Correct severity mapping should be: < 50% = INFO, 50-80% = WARNING, > 80% = CRITICAL

### Required Changes

**File**: `src/services/firebase_client.py`

Find Firebase quota logging (around lines 42-110 per CLAUDE.md reference).

Update severity mapping:
```python
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
        return "INFO"  # Not critical for <50%
```

Update log output:
```python
# Old:
log.warning(f"🔴 CRITICAL: Firebase reads: {used}/50000 (0.2%)")

# New:
severity = _get_quota_severity(reads_pct, writes_pct)
if severity == "INFO":
    log.info(f"Firebase quota: reads {reads_pct:.1%}, writes {writes_pct:.1%}")
elif severity == "WARNING":
    log.warning(f"Firebase approaching limit: reads {reads_pct:.1%}, writes {writes_pct:.1%}")
elif severity == "CRITICAL":
    log.critical(f"Firebase quota critical: reads {reads_pct:.1%}, writes {writes_pct:.1%}")
```

### Deliverable
- Updated quota logging in firebase_client.py
- 0.2% usage shows as INFO not CRITICAL
- Correct severity for 50-80% (WARNING) and >80% (HIGH_WARNING/CRITICAL)

---

## Task 3: Integrate Canonical State into Remaining Subsystems

### Problem
V10.13s.1 created canonical_state.py and integrated into execution.py.  
Other subsystems still use their own trade count logic:
- learning.py
- risk_engine.py
- diagnostics.py

### Required Changes

**File**: `src/services/learning.py`
- Replace manual trade count checks with `get_authoritative_trade_count()`
- Use `get_maturity()` for threshold relaxation decisions
- Update any hardcoded `< 50` or `< 100` checks

**File**: `src/services/risk_engine.py` (if exists, else skip)
- Replace `METRICS["trades"]` with `get_authoritative_trade_count()`
- Use `is_bootstrap_active()` for position sizing

**File**: `src/services/diagnostics.py`
- Add diagnostic print showing canonical state
- Display "runtime trades" vs "dashboard trades" vs "maturity trades"

**File**: `bot2/main.py`
- Import canonical_state
- Add call to `invalidate_cache()` after state-changing events:
  - After trade completion
  - After metrics flush
  - After learning update
- Print canonical state in monitoring loop

### Deliverable
- All subsystems use canonical_state for truth
- No more conflicting trade count logic
- Consistent state across all decision-making

---

## Task 4: Test & Verify

### Tests to Run

```bash
# 1. Duplicate subscription
python -c "
from src.core.event_bus import subscribe, _subscribers
initial = len(_subscribers)
# Try to subscribe twice to same event+handler
# Should prevent second subscription
"

# 2. Firebase quota severity
python -c "
from src.services.firebase_client import get_quota_status
# Verify status shows correct severity at different levels
"

# 3. Canonical state integration
python -c "
from src.services.execution import bootstrap_mode, is_bootstrap
from src.services.canonical_state import get_canonical_state
# Verify bootstrap_mode uses canonical state
"

# 4. Full startup test
# Run bot2/main.py and check:
# - No duplicate Subscribed messages
# - Firebase quota shows INFO for <50%
# - Canonical state printed in logs
# - No 'trades=0' with bootstrap=True contradictions
```

### Success Criteria
- ✅ No duplicate subscription warnings in logs
- ✅ Firebase quota 0.2% shows as INFO not CRITICAL
- ✅ All subsystems use canonical_state
- ✅ No startup state mismatches reported
- ✅ Maturity oracle never returns trades=0 when data exists

---

## Implementation Order

1. **First**: Event bus duplicate guard (safest, no state changes)
2. **Second**: Firebase quota severity (log-only fix)
3. **Third**: Canonical state integration (touch multiple files, test thoroughly)
4. **Fourth**: Test & verify all 3 together

---

## Files to Modify

| File | Changes | Risk |
|------|---------|------|
| src/core/event_bus.py | Add duplicate detection | LOW |
| src/services/firebase_client.py | Update severity mapping | LOW |
| src/services/learning.py | Use canonical_state | MEDIUM |
| src/services/risk_engine.py | Use canonical_state | MEDIUM |
| src/services/diagnostics.py | Display canonical_state | LOW |
| bot2/main.py | Integrate canonical_state | MEDIUM |

---

## Deliverable Format

When implementing, provide:

1. **Code changes** (git diff format preferred)
2. **Test results** (actual test output)
3. **Documentation** (what changed, why, impact)
4. **Verification** (proof that success criteria met)

---

## Czech Context (for AI clarity)

- Systém: CryptoMaster vysokofrekvenční trading bot
- Verze: V10.13s.1 + bugfixy (V10.13s.2)
- Měna: BTC, ETH, ADA, BNB, DOT, SOL, XRP
- Problém: Startup state confusion, log noise, quota severity mismatch
- Řešení: Canonical state oracle + logging fixes + subsystem integration

V10.13s.1 opravil maturity oracle.  
V10.13s.2 fixuje zbývající startup problémy.  
Pak V10.13s.3 bude SCRATCH_EXIT forensics (ta vyžaduje trusted state).

---

## Notes

- Fallback gracefully if canonical_state unavailable
- No breaking changes to public APIs
- All changes must be backward compatible
- Cache invalidation critical (use invalidate_cache() after state changes)
