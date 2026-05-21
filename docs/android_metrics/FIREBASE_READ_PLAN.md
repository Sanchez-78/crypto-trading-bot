# Firebase Plán Čtení pro Android App

**Verze:** 1.0  
**Cíl:** Efektivní čtení bez překročení 50k daily read limitu  
**Strategie:** Minimalizovat queries, maximalizovat caching  

---

## 1. Firebase Collections Mapping

### Collection: `trades`

```
Firestore path: /trades/{trade_id}
Document fields:
- trade_id: string (uuid)
- symbol: string
- side: string (BUY/SELL)
- entry_ts: timestamp
- exit_ts: timestamp (null if open)
- entry_price: number
- exit_price: number (null if open)
- pnl_pct: number
- pnl_usd: number
- hold_seconds: number
- reason: string (TP/SL/Timeout/Manual)
- outcome: string (WIN/LOSS/FLAT)
- mode: string (live_real/paper_train)
- status: string (open/closed)
- mfe_pct: number
- mae_pct: number
- bucket: string
- training_bucket: string
- regime: string
- ... (other fields)

Expected document count: ~5,000-10,000 (grows over time)
Document size: ~800 bytes avg
Collection size: ~4-8 MB

Indexes required (Firestore auto-creates):
- trades: [exit_ts DESC, status]
- trades: [mode, status, exit_ts DESC]
- trades: [symbol, regime, status]
```

### Collection: `open_positions`

```
Firestore path: /open_positions/{trade_id}
Document fields:
- trade_id: string (uuid) [PRIMARY KEY]
- symbol: string
- side: string
- entry_price: number
- current_price: number (updated every 5 min by bot)
- entry_ts: timestamp
- hold_seconds: number
- tp_pct: number
- sl_pct: number
- size_usd: number
- unrealized_pnl_pct: number
- regime: string
- bucket: string
- cost_edge_ok: boolean
- geometry_calibrated: boolean
- ... (other fields)

Expected document count: 0-10 at any time
Document size: ~600 bytes
Collection size: ~6 KB max

Strategy: Fetch ALL (single collection read) every 10s or on demand
No pagination needed (max 10 docs)
```

### Document: `bot_config/health`

```
Firestore path: /bot_config/health
Singleton document fields:
- status: string (running/paused/error)
- pid: number
- uptime_seconds: number (derived from start_ts)
- last_heartbeat_ts: timestamp
- git_head: string
- version_marker: string
- last_error: string
- restart_count_24h: number
- config_loaded: boolean

Strategy: Fetch once per 10s
Single document read = 1 quota unit
Caches well locally
```

### Document: `market_health/feed_status`

```
Firestore path: /market_health/feed_status
Document fields:
- status: string (connected/fallback/offline)
- last_tick_ts: timestamp
- ws_connected: boolean
- ws_reconnect_count: number
- active_symbols: [array of symbol strings]
- symbols_detail: {
    BTCUSDT: { last_price: 42500, last_tick_ts: 1716129600000, spread_pct: 0.01 },
    ETHUSDT: { last_price: 2350, last_tick_ts: 1716129600000, spread_pct: 0.015 },
    ...
  }

Strategy: Fetch once per 10s
Single document read
Can contain up to 100 symbols safely
```

### Document: `trading_summary/{mode}`

```
Firestore path: /trading_summary/live_real
Aggregated metrics document fields:
- total_trades: number
- closed_trades: number
- open_count: number
- win_count: number
- loss_count: number
- flat_count: number
- winrate_pct: number
- net_pnl_pct: number
- max_drawdown_pct: number
- last_trade_ts: timestamp
- last_trade_symbol: string
- ... (other aggregates)

Similar structure for: /trading_summary/paper_train

Strategy: Fetch both documents (2 reads) once per 30s
Caches well
Can be pre-computed by bot before push to Firestore
```

### Document: `learning_state/canonical`

```
Firestore path: /learning_state/canonical
LearningMonitor state document:
- lm_total_trades: number
- lm_health_pct: number
- lm_count_by_symbol_regime: {
    "BTCUSDT:TRENDING": 32,
    "BTCUSDT:CHOPPY": 20,
    "ETHUSDT:TRENDING": 25,
    ...
  }
- lm_wr_by_symbol_regime: {
    "BTCUSDT:TRENDING": 0.56,
    "BTCUSDT:CHOPPY": 0.52,
    ...
  }
- cold_start_active: boolean
- last_lm_update_ts: timestamp
- canonical_training_trade_count: number

Strategy: Fetch once per 30s
Single document read
Large but essential for learning tab
```

### Document: `quota_metrics/status`

```
Firestore path: /quota_metrics/status
Firebase quota tracking document:
- firestore_read_count_day: number
- firestore_write_count_day: number
- read_quota_pct: number
- write_quota_pct: number
- quota_state: string (normal/warning/exhausted)
- last_reset_ts: timestamp (midnight PT = 09:00 GMT+2)
- retry_queue_size: number
- failed_write_count: number

Strategy: Fetch once per 60s
Single document read
Can be cached aggressively (rarely changes)
```

---

## 2. Read Frequency Plan

### Dashboard Tab

| Metric | Source | Frequency | Reads/min | Cache |
|--------|--------|-----------|-----------|-------|
| Bot status | bot_config/health | 10s | 6 | 10s |
| Trading summary (live) | trading_summary/live_real | 10s | 6 | 10s |
| Open positions | open_positions (collection) | 10s | 1 | 5s |
| Market feed status | market_health/feed_status | 10s | 6 | 10s |
| Quota | quota_metrics/status | 60s | 1 | 60s |
| Learning health | learning_state/canonical | 30s | 2 | 30s |
| **Subtotal** | | | **22** | |

### Trading Tab

| Metric | Source | Frequency | Reads/min | Cache |
|--------|--------|-----------|-----------|-------|
| Open positions detail | open_positions | 30s | 2 | 10s |
| Trade history (recent 50) | trades collection | On-demand | 1 (paginated) | 5m |
| Trade detail | trades/{id} | On-demand | 1 per tap | - |
| **Subtotal (active)** | | | **2-3** | |

### Learning Tab

| Metric | Source | Frequency | Reads/min | Cache |
|--------|--------|-----------|-----------|-------|
| Learning state | learning_state/canonical | 30s | 2 | 30s |
| Per-symbol breakdown | learning_state/canonical | 30s | (included above) | - |
| **Subtotal** | | | **2** | |

### Signals Tab

| Metric | Source | Frequency | Reads/min | Cache |
|--------|--------|-----------|-----------|-------|
| Signal stats | Signal logs (journalctl) | 60s | 0 (logs only) | Local |
| Recent signals | Signal stream (WebSocket) | Real-time | 0 | - |
| **Subtotal** | | | **0** | |

### Diagnostics Tab

| Metric | Source | Frequency | Reads/min | Cache |
|--------|--------|-----------|-----------|-------|
| Error logs | Logs (journalctl) | On-demand | 0 | - |
| Audit results | scripts/p11ag_quality_audit.sh | Manual | 0 | - |
| **Subtotal** | | | **0** | |

### **Total Estimated Reads**

- **Per minute (normal):** ~26-27 reads/min
- **Per hour:** ~1,560 reads/hour
- **Per day:** ~37,440 reads/day ✅ (well under 50k limit)
- **Headroom:** ~12,560 reads/day (~25% unused)

---

## 3. Caching Strategy

### Cache Layers

#### Layer 1: Local Device Cache (SQLite)

**Purpose:** Survive network outages, fast UI response

**Contents:**
- All dashboard metrics (10s TTL)
- Last 100 trades (5m TTL)
- Open positions (5s TTL)
- Market feed data (10s TTL)
- Learning state (30s TTL)
- Quota status (60s TTL)

**Implementation:**
```kotlin
// Pseudocode
class MetricsCache(context: Context) {
  private val db = Room.databaseBuilder(context, MetricsDb.class, "metrics.db")
  
  fun saveMetric(key: String, value: String, ttl_ms: Long) {
    db.insert(CachedMetric(key, value, System.currentTimeMillis() + ttl_ms))
  }
  
  fun getMetric(key: String): String? {
    val cached = db.query(key)
    if (cached != null && cached.expires_at > System.currentTimeMillis()) {
      return cached.value
    }
    db.delete(key) // Clean expired
    return null
  }
}
```

#### Layer 2: In-Memory Cache (RAM)

**Purpose:** Ultra-fast UI access during same session

**Contents:**
- Current tab metrics (5s TTL)
- User scrolling position
- Chart data (for current day)

**Implementation:**
```kotlin
class MemoryCache {
  private val cache = HashMap<String, CachedValue>()
  
  fun put(key: String, value: Any, ttl_ms: Long = 5000) {
    cache[key] = CachedValue(value, System.currentTimeMillis() + ttl_ms)
  }
  
  fun get(key: String): Any? {
    val cached = cache[key] ?: return null
    if (cached.expires_at < System.currentTimeMillis()) {
      cache.remove(key)
      return null
    }
    return cached.value
  }
}
```

#### Layer 3: Network (Firestore)

**Purpose:** Fetch fresh data when cache expires

**Strategy:**
- Batch reads where possible (read multiple fields in 1 document)
- Use collection queries sparingly (paginate large collections)
- Prefer single-document reads over collection queries
- Use field value filtering on client (avoid complex server-side queries)

---

## 4. Pagination Strategy

### Trade History

**Problem:** trades collection may grow to 10,000+ documents

**Solution:** Client-side pagination

```kotlin
class TradeHistoryRepository(firestore: FirebaseFirestore) {
  private val pageSize = 50
  private var lastVisible: DocumentSnapshot? = null
  
  fun fetchNextPage(): List<Trade> {
    var query: Query = firestore.collection("trades")
      .orderBy("exit_ts", Query.Direction.DESCENDING)
      .limit(pageSize + 1)  // +1 to detect end
    
    if (lastVisible != null) {
      query = query.startAfter(lastVisible)
    }
    
    val snapshot = query.get().await()
    lastVisible = snapshot.documents.lastOrNull()
    
    return snapshot.documents.take(pageSize).map { parseDocument(it) }
  }
}
```

**Quota impact:**
- First page: 1 read
- Each additional page: 1 read
- User typical session: 1-3 pages = 2-4 reads total

---

## 5. Offline Cache Strategy

### Minimal Offline Mode

**Goal:** Show last-known state if bot goes offline

**TTL:** 5 minutes (stale data warning after 1 minute)

**Contents:**
- Dashboard snapshot
- Last trade
- Last 10 open positions
- Last learning state

**UI Behavior:**

```
┌────────────────────────┐
│ ⚠️ OFFLINE MODE        │
│                        │
│ Poslední data:         │
│ • Dashboard: 2m zpět   │
│ • Obchody: 5m zpět     │
│ • Učení: 5m zpět       │
│                        │
│ Data mohou být stálá!  │
│ [Reconnect] [Settings] │
└────────────────────────┘
```

**Implementation:**

```kotlin
class OfflineMetricsManager(context: Context) {
  fun getCachedOrNull(key: String, staleWarningMs: Long = 60000): MetricValue? {
    val cached = getFromDb(key) ?: return null
    
    val age = System.currentTimeMillis() - cached.timestamp
    if (age > staleWarningMs) {
      cached.isStale = true  // Mark for UI
    }
    if (age > 5 * 60000) {  // 5 min
      deleteFromDb(key)
      return null
    }
    
    return cached
  }
}
```

---

## 6. Efficient Data Loading Patterns

### Pattern 1: Batch Document Reads

**Wrong way (3 reads):**
```firestore
bot_health = db.collection("bot_config").document("health").get()
trading_summary = db.collection("trading_summary").document("live_real").get()
market_status = db.collection("market_health").document("feed_status").get()
// = 3 quota units
```

**Right way (3 reads, but smaller payload):**
```
Combine reading into single parent document:
/bot_state
  - health: { status, pid, uptime, ... }
  - trading_summary: { total_trades, winrate, ... }
  - market: { status, last_tick_ts, ... }
// Still 1 read (1 quota unit), larger document but acceptable
```

**Note:** Firestore charges per document read, not per field, so combining is better.

---

### Pattern 2: Collection Subscriptions (Real-time Listeners)

**For Dashboard (high frequency updates):**

```kotlin
class DashboardRepository(firestore: FirebaseFirestore) {
  fun observeOpenPositions(): Flow<List<Position>> = callbackFlow {
    val listener = firestore.collection("open_positions")
      .addSnapshotListener { snapshot, error ->
        if (error != null) {
          close(error)
        } else {
          val positions = snapshot?.documents?.map { parsePosition(it) } ?: emptyList()
          trySend(positions)
        }
      }
    awaitClose { listener.remove() }
  }
}
```

**Quota impact:** Real-time listeners cost 1 read per snapshot
- Firestore limit: Up to 100 active listeners
- Strategy: Use for critical real-time metrics only (open positions, last heartbeat)
- Alternative: Polling every 10s if listener count is concern

---

### Pattern 3: Aggregated Snapshots (Server-Computed)

**Problem:** Computing winrate % from 10,000 trades is expensive

**Solution:** Pre-compute on bot, push to Firestore

Bot should maintain `/trading_summary/{mode}` document with:
- total_trades
- win_count / loss_count
- calculated winrate %
- max_drawdown
- net_pnl %

Android reads 1 document = 1 read unit

---

## 7. Avoiding Quota Overages

### Red Flags

| Situation | Problem | Fix |
|-----------|---------|-----|
| User repeatedly taps same button | Duplicate requests | Debounce (500ms) |
| List view + auto-scroll | Every item = read | Paginate, cache pages |
| Network retry loop | Exponential reads | Exponential backoff |
| Multiple listeners on same collection | Duplicate reads | Single listener + broadcast |
| Parsing raw logs in app | Large payloads | Aggregate on server |

### Quota Monitoring

```kotlin
class QuotaMonitor(firestore: FirebaseFirestore) {
  private var dailyReads = 0
  private val readLimit = 50000
  
  fun beforeRead(estimate: Int = 1) {
    dailyReads += estimate
    if (dailyReads > readLimit * 0.8) {
      logger.warn("Quota: ${dailyReads} / ${readLimit} (80%)")
      triggerWarning()
    }
    if (dailyReads > readLimit * 0.95) {
      logger.error("Quota CRITICAL: ${dailyReads} / ${readLimit} (95%)")
      enterDegradedMode()
    }
  }
}
```

---

## 8. Recommended Indexes

Firestore can auto-create these, but explicit creation helps:

```
Collection: trades
- Index 1: [exit_ts DESC, status] → for sorting historical trades
- Index 2: [mode, status, exit_ts DESC] → for filtering by mode
- Index 3: [symbol, regime, status] → for per-symbol breakdown

Collection: open_positions
- No indexes needed (small collection, fetch all)

Collection: bot_config, learning_state, trading_summary, market_health
- No indexes needed (single document collections)
```

---

## 9. Data Refresh Priorities

### P0 (Critical, refresh fast)
- Open positions (10s)
- Bot health (10s)
- Quota status (60s)

### P1 (Important, refresh moderate)
- Trading summary (10-30s)
- Learning state (30s)
- Market feed (10s)

### P2 (Nice-to-have, refresh slow)
- Trade history (on-demand)
- Error logs (on-demand)
- Audit results (manual)

---

## 10. Migration Plan

### Phase 1 (Immediate)
- Implement local SQLite cache
- Fetch 6 essential metrics per 10s
- Measure actual quota usage

### Phase 2 (Week 2)
- Add real-time listeners for open positions
- Optimize bot to pre-compute trading_summary
- Implement pagination for trade history

### Phase 3 (Week 3+)
- Add offline mode
- Implement signal stream (WebSocket)
- Advanced filtering + export

---

**Konec Firebase plán čtení V1.0**
