# V5 Bot Metrics API - Android App Integration

## API Endpoints

Base URL: `http://your-server:5000`

### 1. GET `/metrics` - Complete Metrics Snapshot

**Response (200 OK):**
```json
{
  "running": true,
  "epoch_id": "epoch_20260529_123550",
  "timestamp": "2026-05-29T12:39:00Z",
  "feed_connected": true,
  "symbols_with_data": 5,
  "open_positions": 3,
  "open_notional_usd": 1250.50,
  "max_open_global": 3,
  "entries_attempted": 12,
  "entries_successful": 9,
  "entries_rejected_by_gate": 3,
  "trades_closed": 2,
  "total_net_pnl_usd": 45.75,
  "net_pnl_pct": 3.66,
  "win_rate": 0.67,
  "profit_factor": 2.15,
  "average_cost_bps": 2.5,
  "signals": {
    "BTCUSDT": "ACCEPTED: tight_spread_entry",
    "ETHUSDT": "ACCEPTED: tight_spread_entry",
    "BNBUSDT": "ACCEPTED: tight_spread_entry",
    "ADAUSDT": "REJECTED: spread_too_wide",
    "XRPUSDT": "ACCEPTED: tight_spread_entry"
  },
  "current_regime": "ranging_normal_vol",
  "firebase_writes": 45,
  "firebase_failures": 0,
  "quota_reads_used": 3250,
  "quota_reads_limit": 20000,
  "quota_writes_used": 1200,
  "quota_writes_limit": 10000,
  "quota_state": "NORMAL",
  "reconnect_count": 2,
  "stale_events_rejected": 15,
  "book_spreads": {
    "BTCUSDT": 0.01,
    "ETHUSDT": 0.05,
    "BNBUSDT": 0.15,
    "ADAUSDT": 4.31,
    "XRPUSDT": 0.76
  },
  "mid_prices": {
    "BTCUSDT": 73258.55,
    "ETHUSDT": 1999.205,
    "BNBUSDT": 636.305,
    "ADAUSDT": 0.23215,
    "XRPUSDT": 1.3071
  },
  "learning_updates": 3,
  "strategies_being_evaluated": 5,
  "eligible_closes_today": 2,
  "min_closes_for_eligibility": 30,
  "uptime_seconds": 540,
  "logs_per_second": 85.5,
  "cpu_percent": 8.5,
  "memory_mb": 125
}
```

---

### 2. GET `/health` - Health Check

**Response (200 OK):**
```json
{
  "status": "healthy",
  "running": true,
  "feed_connected": true,
  "firebase_quota_ok": true
}
```

**Response (503 Service Unavailable):**
```json
{
  "status": "unhealthy",
  "reason": "Collector not initialized"
}
```

---

### 3. GET `/metrics/dashboard` - Dashboard Summary

**Response (200 OK):**
```json
{
  "status": {
    "running": true,
    "timestamp": "2026-05-29T12:39:00Z",
    "feed_connected": true,
    "symbols_with_data": 5
  },
  "positions": {
    "open": 3,
    "notional_usd": 1250.50
  },
  "performance": {
    "total_pnl_usd": 45.75,
    "win_rate": 0.67,
    "profit_factor": 2.15
  },
  "trading": {
    "entries_attempted": 12,
    "entries_successful": 9,
    "trades_closed": 2
  }
}
```

---

### 4. GET `/metrics/trading` - Trading Details

**Response (200 OK):**
```json
{
  "entries": {
    "attempted": 12,
    "successful": 9,
    "rejected_by_gate": 3
  },
  "positions": {
    "open_count": 3,
    "open_notional_usd": 1250.50,
    "max_open": 3
  },
  "results": {
    "trades_closed": 2,
    "total_pnl_usd": 45.75,
    "net_pnl_pct": 3.66,
    "win_rate": 0.67,
    "profit_factor": 2.15,
    "average_cost_bps": 2.5
  },
  "uptime_seconds": 540
}
```

---

### 5. GET `/metrics/firebase` - Quota & Sync Status

**Response (200 OK):**
```json
{
  "quota": {
    "reads": {
      "used": 3250,
      "limit": 20000,
      "percent_used": 16.3
    },
    "writes": {
      "used": 1200,
      "limit": 10000,
      "percent_used": 12.0
    },
    "state": "NORMAL"
  },
  "sync": {
    "writes": 45,
    "failures": 0
  }
}
```

**Quota States:**
- `NORMAL`: < 70% of limit
- `WARNING`: 70-90% of limit
- `EXHAUSTED`: > 90% of limit

---

### 6. GET `/metrics/signals` - Current Signals

**Response (200 OK):**
```json
{
  "current_regime": "ranging_normal_vol",
  "signals": {
    "BTCUSDT": "ACCEPTED: tight_spread_entry",
    "ETHUSDT": "ACCEPTED: tight_spread_entry",
    "BNBUSDT": "ACCEPTED: tight_spread_entry",
    "ADAUSDT": "REJECTED: spread_too_wide",
    "XRPUSDT": "ACCEPTED: tight_spread_entry"
  },
  "spreads_bps": {
    "BTCUSDT": 0.01,
    "ETHUSDT": 0.05,
    "BNBUSDT": 0.15,
    "ADAUSDT": 4.31,
    "XRPUSDT": 0.76
  },
  "mid_prices": {
    "BTCUSDT": 73258.55,
    "ETHUSDT": 1999.205,
    "BNBUSDT": 636.305,
    "ADAUSDT": 0.23215,
    "XRPUSDT": 1.3071
  },
  "timestamp": "2026-05-29T12:39:00Z"
}
```

---

### 7. GET `/metrics/learning-history` - Detailed Learning History with Timestamps

**Response (200 OK):**
```json
{
  "total_trades_closed": 9,
  "total_wins": 6,
  "total_losses": 2,
  "total_flats": 1,
  "win_rate": 0.67,
  "total_net_pnl_usd": 45.75,
  "total_fees_usd": 3.50,
  "avg_pnl_per_trade": 5.08,
  "per_symbol_summary": {
    "BTCUSDT": {
      "symbol": "BTCUSDT",
      "trades_closed": 3,
      "wins": 2,
      "losses": 1,
      "flats": 0,
      "win_rate": 0.67,
      "total_pnl_usd": 22.50,
      "avg_pnl_per_trade": 7.50,
      "total_fees_usd": 1.20,
      "best_trade_pnl_usd": 15.30,
      "worst_trade_pnl_usd": -3.25
    },
    "ETHUSDT": {
      "symbol": "ETHUSDT",
      "trades_closed": 3,
      "wins": 2,
      "losses": 1,
      "flats": 0,
      "win_rate": 0.67,
      "total_pnl_usd": 18.25,
      "avg_pnl_per_trade": 6.08,
      "total_fees_usd": 1.15,
      "best_trade_pnl_usd": 12.45,
      "worst_trade_pnl_usd": -2.80
    },
    "BNBUSDT": {
      "symbol": "BNBUSDT",
      "trades_closed": 3,
      "wins": 2,
      "losses": 0,
      "flats": 1,
      "win_rate": 0.67,
      "total_pnl_usd": 5.00,
      "avg_pnl_per_trade": 1.67,
      "total_fees_usd": 1.15,
      "best_trade_pnl_usd": 8.50,
      "worst_trade_pnl_usd": 0.00
    }
  },
  "closed_trades": [
    {
      "trade_id": "trade_a1b2c3d4",
      "symbol": "BTCUSDT",
      "entry_side": "BUY",
      "entry_price": 73258.55,
      "exit_price": 73350.25,
      "qty": 0.1,
      "entry_timestamp": "2026-05-29T12:34:15Z",
      "exit_timestamp": "2026-05-29T12:45:30Z",
      "hold_seconds": 675,
      "gross_pnl_usd": 16.50,
      "gross_pnl_pct": 0.225,
      "net_pnl_usd": 15.30,
      "net_pnl_pct": 0.209,
      "total_costs_usd": 1.20,
      "entry_fee_usd": 0.65,
      "exit_fee_usd": 0.55,
      "funding_cost_usd": 0.00,
      "entry_notional_usd": 7325.86,
      "outcome": "WIN"
    },
    {
      "trade_id": "trade_e5f6g7h8",
      "symbol": "ETHUSDT",
      "entry_side": "BUY",
      "entry_price": 1999.205,
      "exit_price": 2015.850,
      "qty": 0.5,
      "entry_timestamp": "2026-05-29T12:50:22Z",
      "exit_timestamp": "2026-05-29T13:05:45Z",
      "hold_seconds": 923,
      "gross_pnl_usd": 8.32,
      "gross_pnl_pct": 0.416,
      "net_pnl_usd": 7.10,
      "net_pnl_pct": 0.355,
      "total_costs_usd": 1.22,
      "entry_fee_usd": 0.62,
      "exit_fee_usd": 0.60,
      "funding_cost_usd": 0.00,
      "entry_notional_usd": 999.60,
      "outcome": "WIN"
    },
    {
      "trade_id": "trade_i9j0k1l2",
      "symbol": "BNBUSDT",
      "entry_side": "BUY",
      "entry_price": 636.305,
      "exit_price": 636.305,
      "qty": 0.15,
      "entry_timestamp": "2026-05-29T13:10:33Z",
      "exit_timestamp": "2026-05-29T13:20:15Z",
      "hold_seconds": 582,
      "gross_pnl_usd": 0.00,
      "gross_pnl_pct": 0.0,
      "net_pnl_usd": -1.08,
      "net_pnl_pct": -0.11,
      "total_costs_usd": 1.08,
      "entry_fee_usd": 0.54,
      "exit_fee_usd": 0.54,
      "funding_cost_usd": 0.00,
      "entry_notional_usd": 95.45,
      "outcome": "FLAT"
    }
  ],
  "timestamp": "2026-05-29T13:25:00Z"
}
```

---

## Android App Implementation Guide

### Required Dependencies
```gradle
dependencies {
    implementation 'com.squareup.retrofit2:retrofit:2.9.0'
    implementation 'com.squareup.retrofit2:converter-gson:2.9.0'
    implementation 'com.squareup.okhttp3:okhttp:4.10.0'
}
```

### Kotlin Data Classes
```kotlin
// For /metrics endpoint
data class MetricsSnapshot(
    val running: Boolean,
    val epoch_id: String?,
    val timestamp: String,
    val feed_connected: Boolean,
    val symbols_with_data: Int,
    val open_positions: Int,
    val open_notional_usd: Float,
    val entries_attempted: Int,
    val entries_successful: Int,
    val trades_closed: Int,
    val total_net_pnl_usd: Float,
    val win_rate: Float?,
    val profit_factor: Float?,
    val signals: Map<String, String>,
    val current_regime: String?,
    val quota_state: String,
    val book_spreads: Map<String, Float>,
    val mid_prices: Map<String, Float>,
    val uptime_seconds: Int
)

// For /metrics/dashboard endpoint
data class DashboardMetrics(
    val status: StatusData,
    val positions: PositionsData,
    val performance: PerformanceData,
    val trading: TradingData
)

data class StatusData(
    val running: Boolean,
    val timestamp: String,
    val feed_connected: Boolean,
    val symbols_with_data: Int
)

data class PositionsData(
    val open: Int,
    val notional_usd: Float
)

data class PerformanceData(
    val total_pnl_usd: Float,
    val win_rate: Float?,
    val profit_factor: Float?
)

data class TradingData(
    val entries_attempted: Int,
    val entries_successful: Int,
    val trades_closed: Int
)

// For /metrics/learning-history endpoint
data class TradeRecord(
    val trade_id: String,
    val symbol: String,
    val entry_side: String,
    val entry_price: Float,
    val exit_price: Float,
    val qty: Float,
    val entry_timestamp: String,
    val exit_timestamp: String,
    val hold_seconds: Int,
    val gross_pnl_usd: Float,
    val gross_pnl_pct: Float,
    val net_pnl_usd: Float,
    val net_pnl_pct: Float,
    val total_costs_usd: Float,
    val entry_fee_usd: Float,
    val exit_fee_usd: Float,
    val funding_cost_usd: Float,
    val entry_notional_usd: Float,
    val outcome: String  // "WIN", "LOSS", "FLAT"
)

data class PerSymbolLearning(
    val symbol: String,
    val trades_closed: Int,
    val wins: Int,
    val losses: Int,
    val flats: Int,
    val win_rate: Float?,
    val total_pnl_usd: Float,
    val avg_pnl_per_trade: Float?,
    val total_fees_usd: Float,
    val best_trade_pnl_usd: Float?,
    val worst_trade_pnl_usd: Float?
)

data class LearningHistory(
    val total_trades_closed: Int,
    val total_wins: Int,
    val total_losses: Int,
    val total_flats: Int,
    val win_rate: Float?,
    val total_net_pnl_usd: Float,
    val total_fees_usd: Float,
    val avg_pnl_per_trade: Float?,
    val per_symbol_summary: Map<String, PerSymbolLearning>,
    val closed_trades: List<TradeRecord>,
    val timestamp: String
)
```

### Retrofit Service Interface
```kotlin
interface V5BotApi {
    @GET("/metrics")
    suspend fun getMetrics(): MetricsSnapshot

    @GET("/health")
    suspend fun getHealth(): HealthResponse

    @GET("/metrics/dashboard")
    suspend fun getDashboard(): DashboardMetrics

    @GET("/metrics/trading")
    suspend fun getTrading(): TradingMetrics

    @GET("/metrics/firebase")
    suspend fun getFirebase(): FirebaseMetrics

    @GET("/metrics/signals")
    suspend fun getSignals(): SignalsMetrics

    @GET("/metrics/learning-history")
    suspend fun getLearningHistory(): LearningHistory
}
```

### Usage Example
```kotlin
val retrofit = Retrofit.Builder()
    .baseUrl("http://your-server:5000/")
    .addConverterFactory(GsonConverterFactory.create())
    .build()

val api = retrofit.create(V5BotApi::class.java)

// Fetch metrics every 2 seconds
viewModelScope.launch {
    while (true) {
        try {
            val metrics = api.getMetrics()
            updateUI(metrics)
        } catch (e: Exception) {
            showError(e.message)
        }
        delay(2000)  // Poll every 2 seconds
    }
}

// Fetch learning history every 10 seconds
viewModelScope.launch {
    while (true) {
        try {
            val learning = api.getLearningHistory()
            displayLearningMetrics(learning)
            // learning.closed_trades contains all historical trades with timestamps
            // learning.per_symbol_summary gives per-symbol success metrics
        } catch (e: Exception) {
            showError(e.message)
        }
        delay(10000)  // Poll every 10 seconds
    }
}
```

---

## Error Handling

All endpoints may return errors:

**503 Service Unavailable** - Collector not initialized
```json
{
  "error": "Collector not initialized"
}
```

**500 Internal Server Error** - Server error
```json
{
  "error": "Internal server error"
}
```

---

## Recommended Update Frequencies

- **Dashboard**: Every 2-3 seconds
- **Trading metrics**: Every 1 second
- **Signals**: Every 1 second
- **Firebase quota**: Every 10 seconds
- **Learning history**: Every 10 seconds (when viewing detailed trade history)
- **Health check**: Every 5 seconds (background)

---

## Colors for Android UI

```kotlin
object MetricsColors {
    // Status
    val statusHealthy = Color(0xFF4CAF50)  // Green
    val statusWarning = Color(0xFFFFC107)  // Amber
    val statusError = Color(0xFFF44336)    // Red

    // Performance
    val pnlPositive = Color(0xFF4CAF50)    // Green
    val pnlNegative = Color(0xFFF44336)    // Red

    // Quota
    val quotaNormal = Color(0xFF4CAF50)     // Green
    val quotaWarning = Color(0xFFFFC107)    // Amber
    val quotaExhausted = Color(0xFFF44336)  // Red
}
```
