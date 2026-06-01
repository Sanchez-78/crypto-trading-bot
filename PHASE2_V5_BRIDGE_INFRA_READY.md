# CryptoMaster — Phase 2 V5 Bridge Infrastructure Inside Legacy Report

## Verdict
**PHASE2_V5_BRIDGE_INFRA_READY**

All Phase 2 acceptance criteria met. V5 bridge infrastructure implemented and tested. Ready for Phase 3: hooking into live PAPER_ENTRY/PAPER_EXIT lifecycle.

---

## Single-bot baseline

- **cryptomaster.service**: Active, ready for integration testing
- **cryptomaster-v5-paper.service**: Masked/inactive (no parallel writers)
- **REAL disabled**: ✅ REAL_ORDERS_ALLOWED=false enforced at config load and throughout
- **Repo state**: Commit 51901e7 → Phase 2 (all components, 25 tests passing)

---

## Implemented components

### 1. quota.py ✅
- **Class**: `V5LegacyQuotaGuard`
- **Location**: `src/services/v5_legacy_bridge/quota.py` (~300 lines)
- **Features**:
  - Internal read cap: 20,000/day
  - Internal write cap: 10,000/day
  - Safety reserves: 500 (close) + 200 (lifecycle) + 100 (emergency)
  - Entry blocking when total_reserve > writes_remaining
  - Blocks new entries but never blocks closes (allow outbox persistence)
  - Symbol/global position limits: 1/2
- **Database**: SQLite at `/opt/cryptomaster/runtime/v5_quota_usage.sqlite` (600 perms)
- **Methods**: `check_can_read/write()`, `check_entry_allowed()`, `record_read/write()`, `snapshot()`
- **Tests**: 9 test cases (all passing)

### 2. outbox.py ✅
- **Class**: `DurableOutbox`
- **Location**: `src/services/v5_legacy_bridge/outbox.py` (~280 lines)
- **Features**:
  - Event persistence with idempotency: unique(event_type, idempotency_key)
  - Retry logic with exponential backoff (60s → 300s → 900s)
  - Max 3 retry attempts before giving up
  - Never loses closed PAPER trades if Firebase fails
  - Event types: paper_open, paper_close, learning_update, dashboard_publish, readiness_publish, quota_publish
- **Database**: SQLite at `/opt/cryptomaster/runtime/v5_trade_outbox.sqlite` (600 perms)
- **Methods**: `enqueue()`, `get_pending()`, `mark_sent()`, `mark_failed()`, `pending_count()`, `flush()`
- **Tests**: 8 test cases (all passing, idempotency verified)

### 3. firebase_writer.py ✅
- **Class**: `V5LegacyFirebaseWriter`
- **Location**: `src/services/v5_legacy_bridge/firebase_writer.py` (~350 lines)
- **Features**:
  - All writes checked via quota guard before attempting
  - On write failure: automatically enqueue to outbox
  - Close events critical: always enqueue if Firebase fails
  - Idempotent trade docs by `trade_id`
  - Flush outbox on demand with exponential backoff
  - No raw ticks, no secret logging
- **Methods**: `write_open()`, `write_close()`, `write_learning_update()`, `write_dashboard()`, `write_readiness()`, `write_quota()`, `flush_outbox()`
- **Firebase Paths**:
  - `v5_trades/{trade_id}`
  - `v5_dashboard/current`
  - `v5_readiness/current`
  - `v5_quota/{yyyy-mm-dd}`

### 4. learning_bridge.py ✅
- **Class**: `V5LearningBridge`
- **Location**: `src/services/v5_legacy_bridge/learning_bridge.py` (~160 lines)
- **Features**:
  - Builds normalized learning snapshots from paper closes
  - Readiness eligibility determination (profitable, learning_eligible, not excluded exit reason)
  - Does NOT replace legacy learning (legacy continues unchanged)
  - REAL_ORDERS_ALLOWED=false enforced with error check
  - Source field: "legacy_v5_bridge"
- **Methods**: `build_learning_update()`, `apply_learning_from_close()`, `check_readiness_eligible()`
- **Output**: Complete learning dict with trade_id, symbol, side, regime, pnl, duration, learning_eligible, readiness_eligible, timestamp

### 5. metrics_publisher.py ✅
- **Class**: `V5MetricsPublisher`
- **Location**: `src/services/v5_legacy_bridge/metrics_publisher.py` (~320 lines)
- **Features**:
  - Builds dashboard metrics with all Android required fields
  - Builds readiness status (NOT_READY, TESTING, READY)
  - Builds quota metrics with utilization percentages
  - Bounded aggregates only (no raw ticks, no streaming)
  - Czech labels for Android UI
- **Methods**: `build_dashboard_metrics()`, `build_readiness_metrics()`, `build_quota_metrics()`, `prepare_publish_payload()`
- **Android Contract**: service_name, mode, real_orders_allowed, legacy_runtime, v5_bridge_enabled, open_positions, closed_today, entries_attempted, entries_accepted, quota_state, readiness_status, learning_updates

### 6. __init__.py (updated) ✅
- **Class**: `V5LegacyBridge` (refactored)
- **Location**: `src/services/v5_legacy_bridge/__init__.py` (~200 lines)
- **Features**:
  - Initializes all components (quota, outbox, firebase_writer, learning_bridge, metrics_publisher)
  - Exposes public API: `can_open_new_position()`, `record_open()`, `record_close()`, `publish_metrics()`, `get_quota_status()`, `flush_outbox()`
  - Safe no-ops with error logging if components unavailable
  - Initialization log: `[V5_BRIDGE_INIT] enabled=true real_orders_allowed=false service=cryptomaster.service`
- **Global Functions**: `get_v5_bridge()`, `initialize_v5_bridge()`

---

## Safety behavior

### Internal quota caps
- **Reads**: 20,000/day (verified, test passing)
- **Writes**: 10,000/day (verified, test passing)
- **Actual expected usage**: ~400-1,200 reads/day, ~300-600 writes/day (3-6% utilization)

### Entry close-reserve
- **Mechanism**: `check_entry_allowed(open_global, open_for_symbol)` blocks new entries if:
  ```
  writes_remaining < (QUOTA_CLOSE_RESERVE + lifecycle_writes + QUOTA_EMERGENCY_RESERVE)
  ```
- **Never blocks closes**: Closes can always be outboxed if Firebase fails
- **Test**: `test_quota_blocks_new_entry_when_close_reserve_insufficient` passing

### Outbox persistence
- **Durability**: Closed PAPER trades persisted to SQLite if Firebase unavailable
- **Idempotency**: `unique(event_type, idempotency_key)` prevents duplicate learning on retry
- **Test**: `test_outbox_unique_idempotency_key_prevents_duplicate_close` passing

### Firebase failure handling
- **On write failure**: Event enqueued to outbox
- **Retry strategy**: Exponential backoff (60s, 300s, 900s), max 3 attempts
- **Success path**: `mark_sent(id)` removes from outbox after successful write
- **Test**: Outbox flush, retry scheduling, mark_failed all tested

### Runtime permissions
- **Directory**: `/opt/cryptomaster/runtime` (mode 700, service user owner)
- **SQLite files**: mode 600 (rw-------)
- **Never**: 777, 666, root-owned service runtime files
- **Verification**: Enforced in `_ensure_runtime_dir()` and `_init_db()`

### REAL disabled
- **Config assertion**: `assert not ENABLE_REAL_ORDERS`
- **Config assertion**: `assert PAPER_ONLY_MODE`
- **Config assertion**: `assert TRADING_MODE == "paper_train"`
- **Learning check**: `if close_event.real_orders_allowed: error(REAL_DISABLED)`
- **Test**: `test_learning_update_real_orders_false` passing

---

## Tests

### Quota tests (9 passing)
- `test_quota_internal_caps_reads_20000_writes_10000` ✅
- `test_quota_check_can_read` ✅
- `test_quota_check_can_write` ✅
- `test_quota_blocks_new_entry_when_close_reserve_insufficient` ✅
- `test_quota_does_not_block_close_outbox` ✅
- `test_quota_enforces_symbol_limits` ✅
- `test_quota_enforces_global_limits` ✅
- `test_quota_snapshot_provides_state` ✅
- `test_quota_helpers` ✅

### Outbox tests (8 passing)
- `test_outbox_persists_event_and_replays_idempotently` ✅
- `test_outbox_unique_idempotency_key_prevents_duplicate_close` ✅
- `test_outbox_mark_sent_removes_entry` ✅
- `test_outbox_mark_failed_schedules_retry` ✅
- `test_outbox_retry_count_increments` ✅
- `test_outbox_prevents_max_retries` ✅
- `test_outbox_different_event_types` ✅
- `test_outbox_multiple_trades_separate` ✅

### Learning & metrics tests (8 passing)
- `test_learning_update_real_orders_false` ✅
- `test_learning_update_fails_if_real_orders_true` ✅
- `test_learning_update_includes_required_fields` ✅
- `test_learning_determines_readiness_eligible` ✅
- `test_metrics_publish_contains_android_required_fields` ✅
- `test_readiness_metrics_determines_status` ✅
- `test_quota_metrics_includes_utilization` ✅
- `test_metrics_payload_includes_all_sections` ✅

### Summary
- **Total tests**: 25
- **Passing**: 25 (100%)
- **Failures**: 0
- **Warnings**: Deprecation notices for utcnow() (non-blocking, cosmetic)

---

## Not done in this phase

- ❌ No PAPER_ENTRY hook yet (Phase 3)
- ❌ No PAPER_EXIT hook yet (Phase 3)
- ❌ No service restart (Phase 3 only after approval)
- ❌ No strategy changes
- ❌ No standalone V5 service
- ❌ No Firebase reset/delete

---

## Architecture diagram

```
Legacy Bot Runtime (cryptomaster.service)
├─ Signal Loop
│  └─ Decision Engine
│     └─ PAPER_ENTRY
│        └─ [Phase 3 Hook] → V5LegacyBridge.record_open(event)
│           ├─ quota_guard.check_can_read/write()
│           └─ firebase_writer.write_open()
│              ├─ Attempt: Firebase set(v5_trades/{trade_id})
│              └─ Failure: Fallback to outbox.enqueue()
│
├─ Close Loop
│  └─ Exit Strategy
│     └─ PAPER_EXIT
│        └─ [Phase 3 Hook] → V5LegacyBridge.record_close(event)
│           ├─ firebase_writer.write_close()
│           ├─ learning_bridge.apply_learning_from_close()
│           │  └─ firebase_writer.write_learning_update()
│           └─ [Periodic] publish_metrics()
│              ├─ build_dashboard_metrics()
│              ├─ build_readiness_metrics()
│              ├─ build_quota_metrics()
│              └─ Write to Firebase (with outbox fallback)
│
└─ Persistence
   ├─ SQLite: /opt/cryptomaster/runtime/v5_quota_usage.sqlite (quota state)
   └─ SQLite: /opt/cryptomaster/runtime/v5_trade_outbox.sqlite (durable events)
```

---

## Next step

**Phase 3 (When operator approves)**:

1. Hook `V5LegacyBridge.record_open()` at legacy PAPER_ENTRY point
2. Hook `V5LegacyBridge.record_close()` at legacy PAPER_EXIT point
3. Hook `V5LegacyBridge.publish_metrics()` in periodic metrics loop
4. Test legacy paper trading with V5 bridge active
5. Verify Firebase writes occur correctly
6. Verify outbox fallback on Firebase failure
7. Verify learning updates and readiness tracking

Do NOT proceed to Phase 3 until this report is explicitly approved.

---

## Implementation dates

- **Phase 2 Start**: 2026-06-01
- **Phase 2 Complete**: 2026-06-01
- **Commits**:
  - quota.py, outbox.py: Initial implementation
  - firebase_writer.py, learning_bridge.py, metrics_publisher.py: Complete components
  - __init__.py: Wiring all components
  - Test files and Phase 2 verification

---

## Acceptance verdict

✅ **PHASE2_V5_BRIDGE_INFRA_READY**

All acceptance criteria satisfied:
- ✅ quota.py implemented with internal caps and reserve logic
- ✅ outbox.py implemented with idempotency and retry
- ✅ firebase_writer.py implemented with quota guard and fallback
- ✅ learning_bridge.py implemented with readiness determination
- ✅ metrics_publisher.py implemented with Android contract
- ✅ __init__.py wired all components
- ✅ REAL disabled tests pass
- ✅ No standalone V5 service active
- ✅ 25/25 Phase 2 tests passing
- ✅ Runtime permissions enforced (700/600)
- ✅ Closed trades never lost (outbox durability)

**Status**: Ready for Phase 3 hooking and integration testing.
