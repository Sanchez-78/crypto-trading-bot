# V10.15 Mammon — Compatibility Map (Phase C)

**Date**: 2026-04-25  
**Approach**: 4-patch incremental strategy  
**Risk**: LOW (additive only; no behavior changes)

---

## Patch Strategy Overview

| Patch | Component | Purpose | Claude/Codex | Risk |
|---|---|---|---|---|
| **1** | Core helpers | DecisionFrame, ErrorCode, ErrorRegistry | Codex | NONE (pure Python) |
| **2** | Canonical logging | Canonical decision log formatter | Codex | NONE (logging only) |
| **3** | Lifecycle helper | OrderLifecycle state machine | Codex | NONE (pure state tracking) |
| **4** | Integration | Emit logs after RDE/executor/close | Claude | LOW (wrapped in try/except) |

---

## Detailed Compatibility Matrix

### PATCH 1: Core Helpers (CODEX_SAFE)

**New files**:
```
src/core/decision_frame.py (200 lines, ~no deps)
src/core/error_registry.py (150 lines, pure enums)
```

**Specification**:

| Component | Current | Change | Reason | Test |
|---|---|---|---|---|
| **DecisionFrame** | N/A (new) | Add class | wrap signal→decision flow | serialize to dict |
| **GateResult** | N/A (new) | Add dataclass | represent gate eval | JSON-safe dict |
| **ErrorCode enum** | N/A (new) | Add enum | standardize error codes | can reference in logs |
| **ErrorRegistry** | N/A (new) | Add dict registry | map error codes → descriptions | for canonical log |

**Code safety**:
- Pure Python, no external deps
- JSON-safe dict serialization
- Backward compatible (dict signals unchanged)
- No side effects
- Test: serialize/deserialize identity

**Allowed changes to other files**: NONE (additive only)

**Rollback**: `git rm src/core/decision_frame.py src/core/error_registry.py`

---

### PATCH 2: Canonical Logging (CODEX_SAFE)

**New file**:
```
src/monitoring/canonical_decision_log.py (100 lines)
```

**Specification**:

| Component | Current | Change | Reason | Test |
|---|---|---|---|---|
| **format_decision_log** | N/A (new) | Add function | one-line stable log output | no crashes on missing fields |
| **format_lifecycle_log** | N/A (new) | Add function | order lifecycle milestone | no crashes on missing fields |
| **DEFAULT_REGISTRY** | N/A (new) | Add const | error code lookup | maps all ErrorCode enum |

**Contract**:
- Input: dict (from signal/decision/trade)
- Output: single-line string (stable format)
- Resilience: missing fields must not crash (use "?" placeholder)
- Format example: `CANON_DECISION id=xxx sym=BTCUSDT reg=BULL_TREND decision=APPROVE ev=+0.123 gates=OK`

**Allowed changes to other files**: NONE (additive only)

**Rollback**: `git rm src/monitoring/canonical_decision_log.py`

---

### PATCH 3: Lifecycle Helper (CODEX_SAFE)

**New file**:
```
src/execution/order_lifecycle.py (150 lines)
```

**Specification**:

| Component | Current | Change | Reason | Test |
|---|---|---|---|---|
| **OrderState enum** | N/A (new) | Add enum | state transitions | all states distinct |
| **OrderLifecycle** | N/A (new) | Add class | track milestones | can replay state history |

**States**:
```
SIGNAL_CREATED
DECISION_STARTED
FEATURES_LOCKED
REGIME_LOCKED
EV_COMPUTED
GATES_EVALUATED
DECISION_APPROVED / DECISION_REJECTED
ORDER_ARMED
PREFIRE_VALIDATED
ORDER_SENT
ORDER_FILLED
POSITION_OPENED
EXIT_TRIGGERED
POSITION_CLOSED
PNL_ATTRIBUTED
LEARNING_UPDATED
FIREBASE_STATE_UPDATED
```

**Pure helper**: No side effects, no I/O.

**Allowed changes to other files**: NONE (additive only)

**Rollback**: `git rm src/execution/order_lifecycle.py`

---

### PATCH 4: Read-Only Integration (CLAUDE_ONLY)

**Files to modify**:
```
src/services/realtime_decision_engine.py (RDE)
src/services/trade_executor.py (executor)
src/services/learning_event.py (learning/close)
```

**Integrations**:

#### 4.1 RDE — Emit canonical decision log (5 lines added)

**Current code** (no logs after decision):
```python
# in RDE, after decision computed
decision = {"symbol": sym, "decision": APPROVE, "ev": ev, ...}
# → decision published to event bus
```

**Change**:
```python
# After decision computed, BEFORE publishing:
try:
    from src.monitoring.canonical_decision_log import format_decision_log
    log_line = format_decision_log(decision)
    logging.getLogger("canonical").info(log_line)
except Exception:
    logging.debug("canonical log failed", exc_info=True)
```

**Behavior change**: NONE (logging only, no decision change)  
**Risk**: Exception in format_decision_log → caught, decision proceeds  
**Test**: decision output unchanged  

#### 4.2 Executor — Emit lifecycle log on order sent (5 lines added)

**Current code**:
```python
# in executor, after order placed
# no logging; just proceed to position tracking
```

**Change**:
```python
# After order sent:
try:
    from src.execution.order_lifecycle import OrderLifecycle
    lc = OrderLifecycle.from_order(order, position)
    lc.mark_state("ORDER_SENT", timestamp=now)
    log_line = lc.format_log()
    logging.getLogger("lifecycle").info(log_line)
except Exception:
    logging.debug("lifecycle log failed", exc_info=True)
```

**Behavior change**: NONE (tracking only, no execution change)  
**Risk**: Exception in lifecycle → caught, order proceeds  
**Test**: position state unchanged  

#### 4.3 Learning — Emit lifecycle log on trade close (5 lines added)

**Current code**:
```python
# in learning_event, after trade closed
# updates METRICS; saves to Firebase
```

**Change**:
```python
# After METRICS updated:
try:
    from src.execution.order_lifecycle import OrderLifecycle
    lc = OrderLifecycle.from_closed_trade(trade)
    lc.mark_state("PNL_ATTRIBUTED", timestamp=now)
    log_line = lc.format_log()
    logging.getLogger("lifecycle").info(log_line)
except Exception:
    logging.debug("lifecycle log failed", exc_info=True)
```

**Behavior change**: NONE (logging only, no metrics change)  
**Risk**: Exception in lifecycle → caught, metrics proceed  
**Test**: metrics state unchanged  

---

## Integration Safety Checks

### Invariants Preserved

✅ **Signal flow**: signal → RDE → executor → learning (unchanged)  
✅ **Decision logic**: gates, EV, thresholds (unchanged)  
✅ **Execution**: order placement, exit logic (unchanged)  
✅ **Learning**: METRICS update, calibration (unchanged)  
✅ **Firebase**: writes, quota checks (unchanged)  
✅ **TP/SL/Trailing/Timeout**: exit pricing + timing (unchanged)  
✅ **Risk gates**: loss streak, DD halt, freq cap (unchanged)  

### Test Plan (Post-Integration)

| Test | Scenario | Expected | Risk if fails |
|---|---|---|---|
| signal → RDE decision | normal case | decision made, canonical log emitted | logging is silent if broken |
| executor order placement | normal case | order sent, lifecycle log emitted | order still placed |
| trade close + learning | normal case | trade closed, metrics updated, lifecycle log | metrics still updated |
| decision + logging exception | format_decision_log raises | decision proceeds, exception caught + logged | none (caught) |
| lifecycle + exception | OrderLifecycle.from_order raises | order proceeds, exception caught | none (caught) |
| no performance regression | 100 trades/hour | latency < 10ms added | marginal |

---

## Rollback Plan

If any patch breaks tests or causes issues:

```bash
# Patch 1 rollback
git rm src/core/decision_frame.py src/core/error_registry.py
git commit -m "Rollback: remove core helpers"

# Patch 2 rollback
git rm src/monitoring/canonical_decision_log.py
git commit -m "Rollback: remove canonical log"

# Patch 3 rollback
git rm src/execution/order_lifecycle.py
git commit -m "Rollback: remove lifecycle helper"

# Patch 4 rollback (if integration goes wrong)
git checkout -- src/services/realtime_decision_engine.py
git checkout -- src/services/trade_executor.py
git checkout -- src/services/learning_event.py
git commit -m "Rollback: remove canonical/lifecycle logging"
```

---

## Claude vs Codex Split

### Codex Tasks (Safe)
- **Patches 1–3**: implement pure helpers (dataclasses, enums, serializers, tests)
- **Allowed files**: src/core/decision_frame.py, src/core/error_registry.py, src/monitoring/canonical_decision_log.py, src/execution/order_lifecycle.py
- **Forbidden files**: realtime_decision_engine.py, trade_executor.py, learning_event.py, firebase_client.py, main.py

### Claude Tasks (Sensitive)
- **Patch 4 integration**: add try/except logging calls to RDE/executor/learning
- **Architecture decisions**: what logs to emit, when, format
- **Safety validation**: ensure no behavior changes
- **Final verification**: tests pass, invariants held

---

## Risk Summary

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Logging exception crashes decision | Very Low | Medium | wrapped in try/except |
| Format function missing field → KeyError | Very Low | Medium | all handlers check existence |
| Performance regression from logging | Very Low | Low | logging is async, < 1ms |
| Firebase quota hit by logging | Very Low | Low | logging uses stderr, not Firestore |
| Circular imports in new modules | Low | High | verify imports before commit |
| Tests fail (pre-existing issues) | Low | Low | documented baseline, no regression |
| Codex touches forbidden files | Very Low | High | pre-flight code review |

**Overall Risk**: ✅ **LOW**

---

## Next Steps

1. Create Codex task prompt for Patches 1–3
2. Codex implements core helpers + logging + lifecycle
3. Run tests: `python -m pytest tests/ -q`
4. Claude implements Patch 4 integration
5. Run final verification
6. Deploy incrementally (one patch at a time if possible)
