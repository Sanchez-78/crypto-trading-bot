# HOTFIX v2: Implementation Plan + Analysis

## Baseline Status
- **Branch**: v5/integrated-paper-firebase-quota-safe
- **Phase**: Phase 3 complete, Phase 4 validation ready
- **Services**: cryptomaster.service (legacy only)
- **Code state**: Phase 3 hooks integrated but P0 bugs identified

## P0 Bugs Identified

### BUG #1: Position Pop-Before-Processing (CRITICAL)
**Location**: `src/services/paper_trade_executor.py:1615-1720`  
**Severity**: CRITICAL - Trade loss on exception  
**Status**: ✅ CONFIRMED

```python
# Line 1615: Position removed
pos = _POSITIONS.pop(position_id)

# Lines 1616-1720: 100+ lines of processing
v5_bridge.record_close(close_event)  # Can fail
learning_update()                     # Can fail
metrics_save()                        # Can fail

# If ANY exception above, trade permanently lost!
```

**Fix**: Move `pop()` to END of function (after all processing succeeds)

### BUG #2: Dedup Check After Position Removed (CRITICAL - TOCTOU)
**Location**: `src/services/paper_trade_executor.py:1725-1729`  
**Severity**: CRITICAL - Dedup fails on retry  
**Status**: ✅ CONFIRMED

```python
# Line 1615: Position already popped
pos = _POSITIONS.pop(position_id)

# ... 110 lines of processing ...

# Line 1725: Dedup check AFTER position removed (too late!)
if position_id in _CLOSED_TRADES_THIS_SESSION:
    return closed_trade
_CLOSED_TRADES_THIS_SESSION.add(position_id)
```

**Fix**: Move dedup check BEFORE position removal

### BUG #3: V5 Bridge Close Exception Swallowed (CRITICAL)
**Location**: `src/services/paper_trade_executor.py:1718-1720`  
**Severity**: CRITICAL - Silent state divergence  
**Status**: ✅ CONFIRMED

```python
try:
    v5_bridge.record_close(close_event)
except Exception as e:
    log.error(f"[V5_BRIDGE] Paper close hook failed: {e}")
    # CODE CONTINUES - no rollback, position already popped!
```

**Fix**: Enqueue to outbox or fail-hard

### BUG #4: Starvation Discovery Accepts idle_s=0.0 (HIGH)
**Location**: `src/services/paper_training_sampler.py:1603-1606, 851-852`  
**Severity**: HIGH - Admission gate regression  
**Status**: ❌ NEEDS VERIFICATION (code logic seems correct, but logs show idle_s=0.0 acceptance)

**Analysis**:
- Line 1603-1606: On startup, `last_eligible_entry_ts = now`, so `idle_s = 0.0`
- Line 955-956: `idle_s = now - last_eligible_entry_ts` should be >= 600s
- Line 1781: After acceptance, `_update_starvation_discovery_idle(_ts_now)` resets `idle_s = 0.0`

**Potential issue**: Race condition or logic error where acceptance happens BEFORE idle check properly guards it.

**Fix**: Add explicit idle_s >= 600 guard BEFORE acceptance decision

### BUG #5: cost_edge_ok=False, cost_edge_bypassed=False But Entry Opens (HIGH)
**Location**: TBD (need to find where decision made)  
**Severity**: HIGH - Admission gate regression  
**Status**: ❌ NEEDS VERIFICATION

**From logs**: `cost_edge_ok=False cost_edge_bypassed=False bypass_reason=none` yet entry still opened.

### BUG #6: Dashboard ok=False Without Reason (MEDIUM)
**Location**: `bot2/main.py` (dashboard publishing)  
**Severity**: MEDIUM - Diagnostic gap  
**Status**: ❌ NEEDS VERIFICATION

**From logs**: `[DASHBOARD_SNAPSHOT_PUBLISH] ok=False ... save_ms=0` (no reason field)

## Implementation Steps

### Phase 1: Fix Critical Position Lifecycle Bugs

#### Step 1a: Move position pop() to END of close_paper_position()
- Read current close_paper_position logic
- Reorder: validate → process → pop
- Ensure all 100+ lines of processing complete before removal
- Test: position must survive exception and be retryable

#### Step 1b: Move dedup check BEFORE position pop
- Dedup first (fail fast)
- Then pop position (safe)
- Then process everything else

#### Step 1c: V5 bridge exception handling - enqueue to outbox
- On V5 bridge write failure, enqueue close event to outbox
- Do NOT update stats until outbox retry succeeds
- Return None/fail early (don't continue processing)

#### Step 1d: Add tests
- `test_close_paper_position_survives_v5_bridge_exception()`
- `test_close_paper_position_dedup_before_removal()`
- `test_close_paper_position_not_lost_on_any_exception()`

### Phase 2: Fix Starvation Discovery Gate

#### Step 2a: Add explicit idle_s >= 600 guard
- Before returning PAPER_STARVATION_DISCOVERY bucket
- Log current idle_s
- Reject if idle_s < 600

#### Step 2b: Verify idle_s calculation
- Audit `_update_starvation_discovery_idle()` calls
- Verify idle_s only resets AFTER successful entry (currently resets too early?)
- Consider moving reset to AFTER acceptance decision

#### Step 2c: Test
- `test_starvation_discovery_rejects_idle_less_than_600()`
- `test_starvation_discovery_idle_resets_only_after_open()`

### Phase 3: Fix Admission Gate (cost_edge)

#### Step 3a: Find where cost_edge_bypassed logic is
- Grep for `cost_edge_bypassed`
- Find where gate decision is made

#### Step 3b: Add guard
- If `cost_edge_ok=False` and `cost_edge_bypassed=False`, reject entry

#### Step 3c: Test
- `test_cost_edge_false_without_bypass_rejects_entry()`
- `test_cost_edge_false_with_bypass_and_reason_allows_entry()`

### Phase 4: Fix Dashboard Diagnostics

#### Step 4a: Add reason field to dashboard publish
- Find `[DASHBOARD_SNAPSHOT_PUBLISH]` log
- Add `reason=...` when ok=False
- Log specific failure reason (throttle/quota/firebase/etc)

#### Step 4b: Test
- `test_dashboard_publish_false_includes_reason()`

### Phase 5: Add All Tests

#### New test files:
- `tests/test_p11_close_lifecycle_safety.py` — close position safety (P0 bugs #1-3)
- `tests/test_p11_starvation_discovery_gate.py` — idle_s gate (P0 bug #4)
- `tests/test_p11_admission_gates.py` — cost_edge gate (P0 bug #5)
- `tests/test_p11_dashboard_diagnostics.py` — dashboard reason (P0 bug #6)

#### Run all tests:
```bash
python -m pytest tests/test_p11_*.py -v
```

### Phase 6: Verification

#### After implementing all fixes:
1. Run all tests: must pass 100%
2. Run legacy bot in PAPER_TRAIN mode
3. Monitor logs for expected gates/hooks
4. Generate report

## Files to Modify

1. **src/services/paper_trade_executor.py**
   - close_paper_position() — reorder pop/processing
   - dedup logic — move before pop
   - V5 bridge exception — enqueue to outbox

2. **src/services/paper_training_sampler.py**
   - _is_starvation_discovery_idle() or caller — add 600s guard
   - _update_starvation_discovery_idle() — verify reset timing
   - _get_training_bucket() — guard before returning PAPER_STARVATION_DISCOVERY
   - admission logic — verify cost_edge_bypassed logic

3. **bot2/main.py**
   - Dashboard snapshot publish — add reason field when ok=False

4. **tests/test_p11_*.py** (new files)
   - Comprehensive test coverage for all P0 fixes

## Success Criteria

- ✅ No position loss on V5 bridge exception
- ✅ Dedup works correctly on message retry
- ✅ Starvation discovery never accepts idle_s < 600
- ✅ cost_edge_ok=False without bypass rejects entry
- ✅ Dashboard ok=False includes reason
- ✅ All new tests pass (100%)
- ✅ Phase 4 validation verdicts reach LEGACY_V5_HYBRID_TRADING_AND_LEARNING

## Timeline

- **Part 1**: Position lifecycle fixes (Bugs #1-3) — 30 min
- **Part 2**: Starvation discovery gate (Bug #4) — 20 min
- **Part 3**: Admission gate (Bug #5) — 15 min
- **Part 4**: Dashboard (Bug #6) — 10 min
- **Part 5**: Tests — 30 min
- **Total**: ~2 hours

