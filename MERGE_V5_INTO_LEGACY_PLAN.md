# CryptoMaster: V5 Functions Merge into Legacy Bot
## Execution Plan - 2026-06-01

### Current State Analysis

**Legacy Runtime**: `/opt/cryptomaster/bot2/main.py` (2167 lines)
- Runtime service: `cryptomaster.service` (ACTIVE/RUNNING)
- Entry/exit logic: embedded in main loop
- Learning engine: `bot2/learning_engine.py`
- No explicit PAPER_ENTRY/PAPER_EXIT markers

**V5 Runtime**: `/opt/cryptomaster_v5_validation/src/v5_bot/` (separate service)
- Service: `cryptomaster-v5-paper.service` (RUNNING)
- Entry logic: `src/v5_bot/paper/runner.py` with explicit entry signals
- Dashboard: Czech language metrics with entry operations log
- Bridge ready: Comprehensive entry_log collection, open_positions tracking, per-symbol metrics

### Merge Strategy

**Phase 1: Disable Standalone V5**
- Stop and mask `cryptomaster-v5-paper.service`
- V5 becomes library only

**Phase 2: Create Legacy→V5 Bridge Package**
- Location: `src/services/v5_legacy_bridge/`
- Maps legacy lifecycle events to V5-compatible persistence
- Quota guard, outbox, Firebase writer, learning bridge, metrics publisher

**Phase 3: Integrate into Legacy Runtime**
- Hook into legacy entry/exit points
- Replace dashboard (or augment with V5 metrics)
- Add quota guard before new entries

**Phase 4: Testing & Validation**
- Verify single writer (legacy only)
- Verify REAL disabled
- Test outbox recovery
- Acceptance: `LEGACY_V5_HYBRID_TRADING_AND_LEARNING`

---

### Phase 1: Inventory & Baseline

**Legacy structure to preserve:**
- `bot2/main.py` - primary trading loop
- `bot2/learning_engine.py` - legacy learner
- `data/` - trading state
- `src/services/` - infrastructure layer

**V5 modules to adapt:**
```
src/v5_bot/firebase/
  ├── quota_guard.py      → src/services/v5_legacy_bridge/quota.py
  ├── repository.py       → src/services/v5_legacy_bridge/firebase_writer.py
  ├── outbox.py          → src/services/v5_legacy_bridge/outbox.py
  └── schema.py          → reuse as-is

src/v5_bot/util/
  └── czech_dashboard.py → reuse for reporting

src/v5_bot/paper/
  ├── paper_broker.py    → reference for position model
  └── runner.py          → learn entry_log structure (NOT run as service)
```

**V5 modules to NOT run:**
```
cryptomaster-v5-paper.service
src/v5_bot/paper/runner.py async loop
src/v5_bot/market/binance_usdm_feed.py standalone
```

---

### Phase 2: Bridge Package Design

**New directory structure:**
```
src/services/v5_legacy_bridge/
  ├── __init__.py
  ├── config.py                    # caps, flags
  ├── event_models.py              # LegacyPaperOpenEvent, LegacyPaperCloseEvent
  ├── quota.py                     # quota_guard (from v5)
  ├── outbox.py                    # durable outbox (from v5)
  ├── firebase_writer.py           # idempotent persistence
  ├── learning_bridge.py           # learning updates + readiness
  ├── metrics_publisher.py         # dashboard/readiness/quota publishing
  ├── android_metrics_registry.py  # contract for Android
  └── tests/
      ├── test_bridge_events.py
      ├── test_quota_guard.py
      ├── test_outbox.py
      └── test_learning_idempotence.py
```

**Config (constants):**
```python
V5_ACTIVE_HARD_READS_CAP_PER_DAY = 20000
V5_ACTIVE_HARD_WRITES_CAP_PER_DAY = 10000
MAX_PAPER_ENTRIES_PER_DAY = 50
MAX_OPEN_GLOBAL = 2
MAX_OPEN_PER_SYMBOL = 1
DASHBOARD_SNAPSHOT_INTERVAL_S = 300
REAL_ORDERS_ALLOWED = False
PAPER_ONLY_MODE = True
```

**Event Models:**
```python
class LegacyPaperOpenEvent:
    trade_id: str
    symbol: str
    side: str
    entry_ts: float
    entry_price: float
    size: float
    cost_edge_ok: bool
    real_orders_allowed: bool = False

class LegacyPaperCloseEvent:
    trade_id: str
    exit_ts: float
    exit_price: float
    exit_reason: str
    gross_pnl: float
    net_pnl: float
    learning_eligible: bool
    real_orders_allowed: bool = False
```

---

### Phase 3: Integration Points in Legacy

**Legacy main loop touch points:**

1. **On entry decision** (TBD - find exact line in bot2/main.py):
   ```python
   v5_bridge.record_open(LegacyPaperOpenEvent(...))
   ```

2. **On exit execution** (TBD):
   ```python
   v5_bridge.record_close(LegacyPaperCloseEvent(...))
   v5_bridge.apply_learning_from_close(event)
   v5_bridge.publish_metrics()
   ```

3. **Before new entry attempt** (add quota check):
   ```python
   if not v5_bridge.quota.can_open_new_position():
       reject_entry_reason = "QUOTA_CLOSE_RESERVE"
       continue
   ```

4. **On startup** (legacy init):
   ```python
   v5_bridge.initialize()
   ```

---

### Phase 4: Logging Requirements

All bridge operations must emit specific tags:

```
[V5_BRIDGE_OPEN_SAVED]        trade_id=X symbol=Y side=BUY
[V5_BRIDGE_CLOSE_SAVED]       trade_id=X pnl=+0.0123 reason=TARGET_HIT
[V5_BRIDGE_LEARNING_UPDATE]   trade_id=X eligible=true
[V5_BRIDGE_DASHBOARD_PUBLISH] open_positions=2 quota_remaining=9950
[V5_BRIDGE_QUOTA_STATE]       reads=1050/20000 writes=250/10000
[V5_BRIDGE_OUTBOX_RETRY]      pending=3 attempt=2
[V5_BRIDGE_REAL_DISABLED]     confirmed=true
```

---

### Phase 5: Safety Checks

**Must verify BEFORE any restart:**

1. ✅ V5 service masked
2. ✅ Legacy service still active
3. ✅ Quota guard initialized
4. ✅ Outbox tables created (SQLite)
5. ✅ Firebase credentials valid
6. ✅ REAL_ORDERS_ALLOWED=False
7. ✅ Open positions recoverable

**Deployment sequence:**
```bash
# On Hetzner:
1. Create v5_legacy_bridge package
2. Add to src/services/
3. Update legacy main loop with hooks
4. systemctl restart cryptomaster.service
5. Wait 5 min, verify logs
6. systemctl mask cryptomaster-v5-paper.service
```

---

### Acceptance Criteria

Final state must show:

✅ Legacy creates PAPER entry/exit  
✅ V5 bridge persists to Firebase  
✅ Learning updates recorded  
✅ Dashboard published  
✅ Quota tracked  
✅ No dual writers  
✅ No REAL enabled  
✅ Only cryptomaster.service active

**Verdict on success**: `LEGACY_V5_HYBRID_TRADING_AND_LEARNING`

---

### Next Steps

1. Read full legacy bot2/main.py to find entry/exit hooks
2. Create v5_legacy_bridge package structure
3. Implement quota guard + outbox
4. Implement Firebase writer with idempotency
5. Hook into legacy main
6. Write tests
7. Deploy to Hetzner
