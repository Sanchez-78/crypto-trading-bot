# Android Firestore Source of Truth

**Status:** P1.1AP Complete
**Date:** 2026-05-21
**Target:** CryptoMaster_app v2.0+

## Overview

The bot now publishes canonical Firestore snapshots for the Android app to consume. These are the source-of-truth documents for all mobile UI displays.

## Published Documents

### 1. `dashboard_snapshot/latest` — Mobile Dashboard

**Cadence:** Every 30 seconds (max)  
**Heartbeat:** Every 5 minutes (forces write if unchanged)  
**Schema Version:** `dashboard_snapshot_v1`

**Top-level Fields:**
```json
{
  "generated_at_ts": 1716316800.5,           // Unix timestamp (float)
  "runtime": {
    "last_heartbeat_ts": 1716316800.5,       // Session start timestamp
    "session_duration_s": 3600.0,             // Seconds since session start
    "is_training": true,                      // Paper training enabled?
    "portfolio_allocation": "BTC=0.5,ETH=0.3" // String format
  },
  "trading": {
    "status": "ACTIVE",                       // IDLE, ACTIVE, HALTED, WAITING
    "symbol_count": 12,                       // Symbols being monitored
    "exposure": 0.45,                         // Current portfolio exposure (0-1)
    "open_positions": 3,                      // Number of open positions
    "watchlist": ["BTCUSDT", "ETHUSDT", ...] // Array of monitored symbols
  },
  "metrics": {
    "equity": 10500.00,                       // Portfolio equity USD
    "drawdown": 0.12,                         // Current drawdown (0-1)
    "balance": 10500.00,                      // Current balance USD
    "unrealized_pnl": 250.50,                 // Open position unrealized PnL
    "realized_pnl": 500.00,                   // Closed trades realized PnL
    "total_pnl": 750.50,                      // Total realized + unrealized
    "win_rate": 0.65,                         // Win rate (0-1)
    "profit_factor": 1.8,                     // Profit factor (wins/losses)
    "sharpe_ratio": 1.2,                      // Sharpe ratio
    "avg_edge": 0.015,                        // Average edge per trade (%)
    "failure_score": 1.2                      // System health score (0=OK, 3+=HALT)
  },
  "learning": {
    "training_mode": "PAPER_TRAIN",           // PAPER_TRAIN, LIVE_PAPER, LIVE_REAL, DISABLED
    "trades_completed": 42,                   // Total closed training trades
    "training_quality": {
      "recent_accuracy": 0.67,                // Last 10 trades accuracy
      "recent_precision": 0.72,               // Precision (TP / TP+FP)
      "recent_recall": 0.61,                  // Recall (TP / TP+FN)
      "cumulative_accuracy": 0.63,            // All-time accuracy
      "attribution_gaps": 3                   // Trades without outcome labels
    },
    "calibration_status": "CALIBRATED",       // UNCALIBRATED, CALIBRATING, CALIBRATED
    "ev_threshold": -0.015,                   // Current EV threshold for entries
    "inference_pct": 42                       // % of signals from ML inference
  },
  "recent_trades": [
    {
      "trade_id": "T001",
      "symbol": "BTCUSDT",
      "side": "BUY",
      "entry": 42500.0,
      "exit": 42750.0,
      "profit": 250.0,
      "outcome": "WIN",
      "closed_at_ts": 1716316000.5,           // Unix timestamp when trade closed
      "duration_s": 600                        // Seconds position held
    },
    // ... up to 20 most recent trades
  ],
  "all_time_stats": {
    "total_trades": 123,
    "winning_trades": 80,
    "losing_trades": 43,
    "consecutive_wins": 5,
    "consecutive_losses": 2,
    "best_trade": 1500.00,
    "worst_trade": -800.00,
    "avg_win": 187.50,
    "avg_loss": -185.00,
    "total_profit": 15000.00,
    "total_loss": -7955.00,
    "net_pnl": 7045.00
  }
}
```

**How Android Should Use:**
- Refresh UI every 5 seconds (polling)
- Check `generated_at_ts`: if > 30s old, show "stale data" warning
- Use `metrics.*` for dashboard widgets
- Display `recent_trades` in scrollable list
- Track `learning.training_quality` for calibration progress
- Use `training.status` to show connection state

---

### 2. `signal_summary/latest` — Signal Log & Pipeline State

**Cadence:** Every 60 seconds (max)  
**Heartbeat:** Every 10 minutes (forces write if unchanged)  
**Schema Version:** `signal_summary_v1`

**Top-level Fields:**
```json
{
  "generated_at_ts": 1716316800.5,
  "runtime": {
    "last_heartbeat_ts": 1716316800.5,
    "session_duration_s": 3600.0
  },
  "signal_pipeline": {
    "window_s": 300,                          // Aggregation window (5 min)
    "total_signals_received": 450,            // Total signals in window
    "signals_evaluated": 420,                 // Passed basic filters
    "signals_passed_ev_gate": 120,            // Passed EV > threshold
    "signals_entered": 3,                     // Actually entered as trades
    "rejection_breakdown": {
      "REJECT_NEGATIVE_EV": 280,              // Rejected: ev < threshold
      "REJECT_INSUFFICIENT_CAPITAL": 15,     // Rejected: not enough balance
      "REJECT_SYMBOL_BLOCKED": 20,            // Rejected: symbol in blacklist
      "REJECT_OPEN_LIMIT": 10,                // Rejected: too many open
      "REJECT_TIME_OF_DAY": 8,                // Rejected: outside trading hours
      "UNKNOWN": 5                            // Rejected: other reasons
    },
    "last_entered_trade": {
      "signal_ts": 1716316700.5,
      "trade_id": "T042",
      "symbol": "ETHUSDT",
      "side": "BUY",
      "entry": 2300.00,
      "ev": 0.025,
      "bucket": "P0_PRIMARY",
      "source": "MOVING_AVERAGE_CROSS"
    },
    "top_rejected_symbol": {
      "symbol": "XRPUSDT",
      "reason_code": "REJECT_SYMBOL_BLOCKED",
      "count": 12
    },
    "top_rejected_reason": {
      "reason_code": "REJECT_NEGATIVE_EV",
      "count": 280
    }
  },
  "learning": {
    "training_mode": "PAPER_TRAIN",
    "total_signals_trained": 50,              // Total signals used in paper training
    "training_quality": {
      "recent_accuracy": 0.67,
      "cumulative_accuracy": 0.63
    },
    "inference_adoption": {
      "inference_enabled": true,
      "inference_pct": 42,                    // % of entered trades from ML
      "inference_accuracy": 0.71              // ML model accuracy
    }
  }
}
```

**How Android Should Use:**
- Display signal pipeline gauge (total → evaluated → entered)
- Show top rejections in a "Why Signals Failed" widget
- Track `signal_pipeline.signals_entered` to detect signal flow issues
- Monitor `learning.inference_adoption` to show ML model health
- Check `generated_at_ts` for freshness (warn if > 60s old)

---

### 3. `app_metrics/latest` — System Metrics (Existing)

**Cadence:** Every 300 seconds (5 min)  
**Heartbeat:** Every 30 minutes (forces write if unchanged)  
**Schema Version:** `app_metrics_v1`

**Fields:**
```json
{
  "generated_at_ts": 1716316800.5,
  "runtime": {
    "last_heartbeat_ts": 1716316800.5,
    "uptime_s": 86400.0,
    "process_memory_mb": 245.6,
    "cpu_usage_pct": 12.5,
    "firebase_quota_reads_pct": 18.0,
    "firebase_quota_writes_pct": 22.0
  },
  "trading": {
    "active_symbols": 15,
    "open_positions": 3,
    "pending_orders": 2,
    "last_trade_ts": 1716316700.5
  },
  "learning": {
    "trades_completed": 42,
    "training_mode": "PAPER_TRAIN"
  }
}
```

---

## Field Descriptions & Freshness

| Field | Source | Update Frequency | Critical? | Stale Threshold |
|-------|--------|---|---|---|
| `dashboard_snapshot/latest` | bot main loop | 30s | YES | 60s |
| `signal_summary/latest` | bot main loop | 60s | YES | 120s |
| `app_metrics/latest` | bot main loop | 300s | NO | 600s |
| `generated_at_ts` | All snapshots | Per document | YES | N/A |
| `runtime.last_heartbeat_ts` | All snapshots | Per document | NO | N/A |

---

## How Android Should Determine Freshness

```typescript
// In Android code
const DASHBOARD_STALE_THRESHOLD_S = 60;
const SIGNAL_SUMMARY_STALE_THRESHOLD_S = 120;

function isDashboardStale(doc: DocumentSnapshot): boolean {
  const generatedAt = doc.data()?.generated_at_ts || 0;
  const ageS = (Date.now() / 1000) - generatedAt;
  return ageS > DASHBOARD_STALE_THRESHOLD_S;
}

function isSignalSummaryStale(doc: DocumentSnapshot): boolean {
  const generatedAt = doc.data()?.generated_at_ts || 0;
  const ageS = (Date.now() / 1000) - generatedAt;
  return ageS > SIGNAL_SUMMARY_STALE_THRESHOLD_S;
}
```

---

## Verification Checklist

**After deploying bot with P1.1AP:**

1. **Wait 30+ seconds** for first dashboard_snapshot write
2. **Check Firestore Console:**
   - Navigate to `dashboard_snapshot/latest`
   - Verify `generated_at_ts` is recent (within last 30s)
   - Verify `metrics.equity > 0`
   - Verify `recent_trades` array has data (if trades exist)

3. **Check signal_summary:**
   - Navigate to `signal_summary/latest`
   - Verify `generated_at_ts` is recent (within last 60s)
   - Verify `signal_pipeline.total_signals_received > 0`
   - Verify `signal_pipeline.rejection_breakdown` populated

4. **In Android app:**
   - Open Dashboard screen
   - Verify data appears (not "No data available")
   - Verify timestamps update every 30s
   - Navigate to Signal Log screen
   - Verify signal counts and rejection reasons appear

5. **Test stale detection:**
   - Stop the bot
   - Wait 90 seconds
   - Android should show "data is stale" warning on Dashboard

---

## Troubleshooting

### Snapshots Not Updating

**Symptom:** `generated_at_ts` hasn't changed in 5+ minutes

**Check:**
```bash
# 1. Verify bot is running
ps aux | grep python | grep bot2

# 2. Check bot logs for publish errors
tail -f logs/bot2.log | grep -E "DASHBOARD|SIGNAL|SNAPSHOT|ERROR"

# 3. Verify Firestore quota status
python -c "from src.services.firebase_client import get_quota_status; print(get_quota_status())"

# 4. If quota exhausted, wait until midnight PT (reset time)
# Midnight PT = 09:00 GMT+2 = 07:00 UTC
```

### Android Shows Stale Data

**Symptom:** Dashboard shows old metrics, timestamps old

**Check:**
1. Verify Firestore documents exist and are recent (see above)
2. Verify Android has Firestore read permission
3. Check Android logcat: `adb logcat | grep -i firestore`
4. Verify network connectivity to Firebase
5. Clear Android app cache and retry

### Missing Fields in Snapshots

**Symptom:** Android can't find `learning.training_quality` or other fields

**Check:**
```python
# In bot logs, search for [DASHBOARD_SNAPSHOT_SAVE] or [SIGNAL_SUMMARY_SAVE]
# Verify builder functions are working:
from src.services.dashboard_snapshot_contract import build_dashboard_snapshot
snap = build_dashboard_snapshot(recent_trades=[], all_time_stats={})
print(snap.keys())  # Verify expected keys present
```

---

## Implementation Timeline

| Phase | Work | Status | Deploy |
|-------|------|--------|--------|
| Phase 1 | Add dashboard_snapshot_contract.py | Complete | Commit 0d9dfdd |
| Phase 2 | Add signal_summary_contract.py | Complete | Commit 0d9dfdd |
| Phase 3 | Add firebase_client publish functions | Complete | Commit 0d9dfdd |
| Phase 4 | Wire publish calls into main loop | **COMPLETE** | **This commit (P1.1AP)** |
| Phase 5 | Android: Read dashboard_snapshot/latest | **Next Sprint** | — |
| Phase 6 | Android: Read signal_summary/latest | **Next Sprint** | — |
| Phase 7 | Android: Implement freshness UI indicators | **Next Sprint** | — |

---

## Code Locations

**Bot (Server-Side):**
- Snapshot publishing: `src/services/firebase_client.py:907-930` (dashboard), `src/services/firebase_client.py:999-1024` (signal_summary)
- Main loop wiring: `bot2/main.py:1967-1983`
- Snapshot building: `src/services/dashboard_snapshot_contract.py`, `src/services/signal_summary_contract.py`

**Android (Client-Side):**
- Dashboard UI: `CryptoMaster_app/app/src/main/java/com/example/cryptomasterapp/ui/DashboardFragment.kt` (to be created)
- Signal Log UI: `CryptoMaster_app/app/src/main/java/com/example/cryptomasterapp/ui/SignalLogFragment.kt` (to be created)
- Firestore listener: `CryptoMaster_app/app/src/main/java/com/example/cryptomasterapp/data/FirestoreRepository.kt` (to be created)

---

**Questions?** Check ARCHITECTURE.md or reach out to the team.
