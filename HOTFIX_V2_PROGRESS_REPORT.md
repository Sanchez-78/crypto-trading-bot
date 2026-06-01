# HOTFIX v2 Progress Report

## Implementation Status

### ✅ COMPLETED (Part 1/4)

#### P0 Bug #1: Position Pop-Before-Processing
- **File**: `src/services/paper_trade_executor.py:1612-1625 & 1800-1803`
- **Fix**: Moved `_POSITIONS.pop(position_id)` from start to END of `close_paper_position()`
- **Change**: Read with `_POSITIONS[id]` → process all hooks/learning/metrics → pop on success
- **Result**: Position survives any exception during close and can be retried
- **Commit**: `4d618d0` HOTFIX v2 P0: Fix critical close_paper_position lifecycle bugs #1-3

#### P0 Bug #2: Dedup TOCTOU Race Condition  
- **File**: `src/services/paper_trade_executor.py:1612-1623 & 1728-1729`
- **Fix**: Moved dedup check from line 1725 to line 1612 (before position read)
- **Change**: Check `_CLOSED_TRADES_THIS_SESSION` FIRST → return None immediately → mark as processed AFTER read
- **Result**: Dedup works correctly on message retry; prevents duplicate learning
- **Commit**: `4d618d0` (same commit as #1)

#### P0 Bug #3: V5 Bridge Close Exception Handling
- **File**: `src/services/paper_trade_executor.py:1718-1742`
- **Fix**: On `v5_bridge.record_close()` failure, enqueue to durable outbox for retry
- **Change**: Log error → try to import outbox → enqueue close_event with idempotency_key=trade_id
- **Result**: No silent state divergence; bridge failures automatically retry
- **Commit**: `4d618d0` (same commit as #1)

### ✅ VERIFIED (Background)

#### PAPER_ENTRY Hook Location
- **File**: `src/services/paper_trade_executor.py:972-994`
- **Status**: ✅ Hook IS in live path (after [PAPER_ENTRY] log, calls v5_bridge.record_open())
- **Log marker**: `[V5_BRIDGE_OPEN_SAVED]` should appear after each PAPER entry
- **No change needed**

### ❌ PENDING (Part 2/4)

#### P0 Bug #4: Starvation Discovery idle_s >= 600 Gate
- **File**: `src/services/paper_training_sampler.py:843-852, 951-956`
- **Issue**: Logs show `[PAPER_STARVATION_DISCOVERY_ACCEPTED] idle_s=0.0` 
- **Required fix**:
  - Add explicit `idle_s >= 600` check BEFORE returning PAPER_STARVATION_DISCOVERY bucket
  - Verify `last_eligible_entry_ts` reset timing (currently resets at line 1781 AFTER acceptance)
  - Consider moving reset to AFTER decision is final
- **Test needed**: `test_starvation_discovery_rejects_idle_less_than_600()`

#### P0 Bug #5: cost_edge_ok=False without bypass_reason Gate
- **File**: TBD (need to find admission gate logic)
- **Issue**: Logs show `cost_edge_ok=False cost_edge_bypassed=False bypass_reason=none` yet entry opened
- **Required fix**:
  - Find where bucket decision is made
  - Add guard: IF `cost_edge_ok=False AND cost_edge_bypassed=False` → REJECT
  - OR verify if this is intentional recovery admission (different path)
- **Test needed**: `test_cost_edge_false_without_bypass_rejects_entry()`

#### P0 Bug #6: Dashboard ok=False without reason  
- **File**: `bot2/main.py` (dashboard snapshot publishing)
- **Issue**: `[DASHBOARD_SNAPSHOT_PUBLISH] ok=False` has no reason field
- **Required fix**:
  - Add `reason=...` field to dashboard publish log
  - Include specific failure reason (throttle/quota/firebase/serialization)
  - Consider renaming to "skipped" if it's expected (not a failure)
- **Test needed**: `test_dashboard_publish_false_includes_reason()`

### 📋 Test Infrastructure Needed

#### New Test Files
1. `tests/test_p11_close_lifecycle_safety.py` — P0 bugs #1-3
   - `test_close_position_survives_v5_bridge_exception()`
   - `test_close_position_dedup_prevents_retry_processing()`
   - `test_close_position_not_lost_on_learning_failure()`

2. `tests/test_p11_starvation_discovery_gate.py` — P0 bug #4
   - `test_starvation_discovery_rejects_idle_less_than_600()`
   - `test_starvation_discovery_idle_resets_after_entry()`

3. `tests/test_p11_admission_gates.py` — P0 bug #5
   - `test_cost_edge_false_without_bypass_rejects()`
   - `test_recovery_admission_allows_cost_edge_false()`

4. `tests/test_p11_dashboard_diagnostics.py` — P0 bug #6
   - `test_dashboard_publish_false_has_reason()`

## Diff Summary vs. CryptoMaster_Hotfix_v2 Prompt

### What's Been Done
| Requirement | Status | Location | Notes |
|-----------|--------|----------|-------|
| V5 bridge hook in live path | ✅ Verified | paper_trade_executor.py:972-994 | No change needed |
| Position pop-before-processing | ✅ Fixed | paper_trade_executor.py | Moved pop to end |
| Dedup TOCTOU | ✅ Fixed | paper_trade_executor.py | Moved check to start |
| V5 bridge failure with outbox | ✅ Fixed | paper_trade_executor.py:1718-1742 | Enqueue on failure |
| Runtime permissions check | ✅ Verified | N/A | Bridge creates dirs 700, files 600 |

### What's Still Required
| Requirement | Status | Priority | Work Est. |
|-----------|--------|----------|-----------|
| Starvation idle_s >= 600 | ❌ Pending | P0 | 20 min |
| cost_edge false gate | ❌ Pending | P0 | 15 min |
| Dashboard ok=False reason | ❌ Pending | P0 | 10 min |
| Close lifecycle tests | ❌ Pending | P0 | 30 min |
| Starvation gate tests | ❌ Pending | P0 | 20 min |
| Admission gate tests | ❌ Pending | P0 | 20 min |
| Dashboard test | ❌ Pending | P0 | 10 min |

## Next Steps

1. **Investigate starvation discovery gate** — determine why idle_s=0.0 acceptance occurs
2. **Find admission gate for cost_edge** — locate decision logic
3. **Add dashboard reason field** — modify publish log
4. **Write comprehensive tests** — ensure all fixes verified
5. **Generate final runtime validation report**

## Timeline

- Part 1 (bugs #1-3): ✅ Complete (30 min)
- Part 2 (bugs #4-6): ⏳ In progress (45 min)
- Part 3 (tests): ⏳ Pending (2 hours)
- Part 4 (validation): ⏳ Pending (1 hour)

**Total**: ~4 hours

